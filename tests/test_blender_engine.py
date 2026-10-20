"""Unit tests for Blender headless previs engine."""
import json
import os
import subprocess
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from aistudio.engines.blender import (
    DEFAULT_BLENDER_PATHS,
    build_command,
    find_blender,
    run_previs,
)


class TestBlenderEngine(TestCase):
    def test_find_blender_configured_valid(self):
        with patch("os.path.isfile", return_value=True), \
             patch("os.access", return_value=True):
            self.assertEqual(
                find_blender(configured="/custom/bin/blender"),
                "/custom/bin/blender",
            )

    def test_find_blender_configured_invalid_falls_through(self):
        # Configured doesn't exist, but PATH has blender
        def mock_isfile(path):
            return str(path) == "/usr/bin/blender"

        with patch("os.path.isfile", side_effect=mock_isfile), \
             patch("os.access", return_value=True), \
             patch("shutil.which", return_value="/usr/bin/blender"):
            self.assertEqual(
                find_blender(configured="/nonexistent/blender"),
                "/usr/bin/blender",
            )

    def test_find_blender_from_path(self):
        with patch("shutil.which", return_value="/bin/blender"):
            self.assertEqual(find_blender(), "/bin/blender")

    def test_find_blender_macos_fallback(self):
        def mock_isfile(p):
            return str(p) == "/Applications/Blender.app/Contents/MacOS/Blender"

        with patch("shutil.which", return_value=None), \
             patch("os.path.isfile", side_effect=mock_isfile), \
             patch("os.access", return_value=True):
            self.assertEqual(
                find_blender(),
                "/Applications/Blender.app/Contents/MacOS/Blender",
            )

    def test_find_blender_missing(self):
        with patch("shutil.which", return_value=None), \
             patch("os.path.isfile", return_value=False):
            self.assertIsNone(find_blender())

    def test_build_command_exact_argv(self):
        blend = "/path/to/project.blend"
        script = "/path/to/script.py"
        args = ["--out", "/path/to/out", "--shot", "s01"]

        cmd = build_command(blend, script, args, blender_bin="/bin/blender")
        expected = [
            "/bin/blender",
            "-b",
            blend,
            "-P",
            script,
            "--",
            "--out",
            "/path/to/out",
            "--shot",
            "s01",
        ]
        self.assertEqual(cmd, expected)
        # Ensure it is a list of strings and no shell is used
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(x, str) for x in cmd))

    def test_run_previs_missing_binary(self):
        with patch("aistudio.engines.blender.find_blender", return_value=None):
            with self.assertRaises(FileNotFoundError):
                run_previs("/path/scene.blend", "/proj/out", ["s01"], project_dir="/proj")

    def test_run_previs_path_containment_refuses_outside(self):
        mock_runner = MagicMock()
        with patch("aistudio.engines.blender.find_blender", return_value="/bin/blender"):
            # out_dir completely outside project_dir
            with self.assertRaises(ValueError) as ctx:
                run_previs(
                    blend="/workspace/proj/scene.blend",
                    out_dir="/tmp/outside_renders",
                    shots=["s01"],
                    project_dir="/workspace/proj",
                    runner=mock_runner,
                )
            self.assertIn("outside", str(ctx.exception).lower())
            mock_runner.assert_not_called()

            # traversal attempt
            with self.assertRaises(ValueError):
                run_previs(
                    blend="/workspace/proj/scene.blend",
                    out_dir="/workspace/proj/../secret",
                    shots=["s01"],
                    project_dir="/workspace/proj",
                    runner=mock_runner,
                )
            mock_runner.assert_not_called()

    def test_run_previs_path_containment_allows_inside(self):
        project_dir = "/workspace/proj"
        out_dir = "/workspace/proj/renders/previs"
        mock_runner = MagicMock()
        mock_runner.return_value = MagicMock(
            returncode=0,
            stdout='AISTUDIO_JSON: {"shot": "s01", "frame": "/workspace/proj/renders/previs/s01.png"}\n',
            stderr="",
        )

        with patch("aistudio.engines.blender.find_blender", return_value="/bin/blender"):
            res = run_previs(
                blend="/workspace/proj/scene.blend",
                out_dir=out_dir,
                shots=["s01"],
                project_dir=project_dir,
                runner=mock_runner,
            )
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["shot"], "s01")
            mock_runner.assert_called_once()

    def test_run_previs_argument_list_exact(self):
        mock_runner = MagicMock()
        mock_runner.return_value = MagicMock(
            returncode=0,
            stdout='AISTUDIO_JSON: {"shot": "s01"}\nAISTUDIO_JSON: {"shot": "s02"}\n',
            stderr="",
        )

        with patch("aistudio.engines.blender.find_blender", return_value="/usr/local/bin/blender"):
            res = run_previs(
                blend="/workspace/proj/model.blend",
                out_dir="/workspace/proj/out",
                shots=["s01", "s02"],
                project_dir="/workspace/proj",
                runner=mock_runner,
                timeout=300,
            )
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["shot"], "s01")
            self.assertEqual(res[1]["shot"], "s02")

            # Check invocation on mock_runner
            mock_runner.assert_called_once()
            call_args, call_kwargs = mock_runner.call_args

            cmd = call_args[0]
            self.assertEqual(cmd[0], "/usr/local/bin/blender")
            self.assertEqual(cmd[1], "-b")
            self.assertEqual(cmd[2], "/workspace/proj/model.blend")
            self.assertEqual(cmd[3], "-P")
            self.assertTrue(cmd[4].endswith("blender_previs_script.py"))
            self.assertEqual(cmd[5], "--")
            self.assertIn("--out", cmd)
            self.assertIn("/workspace/proj/out", cmd)
            self.assertIn("s01", cmd)
            self.assertIn("s02", cmd)

            self.assertEqual(call_kwargs.get("timeout"), 300)
            self.assertTrue(call_kwargs.get("capture_output"))
            self.assertTrue(call_kwargs.get("text"))

    def test_run_previs_shots_as_dicts(self):
        mock_runner = MagicMock()
        mock_runner.return_value = MagicMock(
            returncode=0,
            stdout='AISTUDIO_JSON: {"shot": "s01", "frame": "s01.png"}\n',
            stderr="",
        )

        with patch("aistudio.engines.blender.find_blender", return_value="/bin/blender"):
            res = run_previs(
                blend="/workspace/proj/scene.blend",
                out_dir="/workspace/proj/out",
                shots=[{"id": "s01"}],
                project_dir="/workspace/proj",
                runner=mock_runner,
            )
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["shot"], "s01")

            cmd = mock_runner.call_args[0][0]
            self.assertIn("--shot", cmd)
            self.assertIn("s01", cmd)

    def test_run_previs_runner_failure(self):
        mock_runner = MagicMock()
        mock_runner.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Scene not found",
        )

        with patch("aistudio.engines.blender.find_blender", return_value="/bin/blender"):
            with self.assertRaises(RuntimeError) as ctx:
                run_previs(
                    blend="/workspace/proj/scene.blend",
                    out_dir="/workspace/proj/out",
                    shots=["s01"],
                    project_dir="/workspace/proj",
                    runner=mock_runner,
                )
            self.assertIn("Error: Scene not found", str(ctx.exception))


if __name__ == "__main__":
    import unittest
    unittest.main()
