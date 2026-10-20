import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from aistudio.external_edit import ExternalEdit, allowed_apps, open_file, register_version


class ExternalEditTests(unittest.TestCase):
    def test_allowed_apps_includes_os_default_and_configured_names(self):
        self.assertEqual(allowed_apps(["Blender", "GIMP"]), {None, "Blender", "GIMP"})

    def test_open_file_argv_by_platform(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "image.png"
            p.write_bytes(b"x")
            run = Mock(return_value=Mock(returncode=0))
            open_file(p, platform="darwin", runner=run)
            self.assertEqual(run.call_args.args[0], ["open", str(p)])
            open_file(p, app="GIMP", allowed=["GIMP"], platform="darwin", runner=run)
            self.assertEqual(run.call_args.args[0], ["open", "-a", "GIMP", str(p)])
            open_file(p, platform="linux", runner=run)
            self.assertEqual(run.call_args.args[0], ["xdg-open", str(p)])
            startfile = Mock()
            open_file(p, platform="win32", startfile=startfile)
            startfile.assert_called_once_with(str(p))

    def test_open_file_refuses_unallowed_app_and_outside_path(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            p = Path(td) / "a.png"
            p.touch()
            run = Mock()
            with self.assertRaises(ValueError):
                open_file(p, app="Evil", allowed=["GIMP"], platform="darwin", runner=run)
            with self.assertRaises(ValueError):
                open_file(Path(other) / "a.png", project_dir=td, platform="linux", runner=run)
            run.assert_not_called()

    def test_stable_change_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "source.png"
            Image.new("RGB", (2, 2), "red").save(src)
            now = [0.0]
            edit = ExternalEdit(root, apps=["GIMP"], clock=lambda: now[0], poll_interval=1,
                                opener=lambda *a, **k: None)
            record = edit.start("source.png", "GIMP")
            work = Path(record["path"])
            work.write_bytes(src.read_bytes() + b"\0")
            self.assertIsNone(edit.poll())
            now[0] += 1
            self.assertIsNone(edit.poll())
            now[0] += 1
            event = edit.poll()
            self.assertIsNotNone(event)
            self.assertEqual(event["path"], work)
            self.assertTrue(edit.validate(work))
            bad = root / "bad.png"
            bad.write_text("not an image")
            self.assertFalse(edit.validate(bad))
            edit.stop()

    def test_register_version_never_touches_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "image.png"
            original.write_bytes(b"original")
            src = root / "edited.png"
            src.write_bytes(b"edited")
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            dest, metadata = register_version(root, "image.png", src, app="GIMP")
            self.assertEqual(Path(dest).name, "image.v1.png")
            self.assertEqual(Path(dest).read_bytes(), b"edited")
            self.assertEqual(metadata, {"tool": "external", "app": "GIMP", "source_sha": hashlib.sha256(b"edited").hexdigest()})
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
            dest2, _ = register_version(root, "image.png", src, app="GIMP")
            self.assertEqual(Path(dest2).name, "image.v2.png")


if __name__ == "__main__":
    unittest.main()
