import ast
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

ADDON_DIR = Path(__file__).resolve().parent.parent / "integrations" / "blender" / "aistudio_bridge"
MANIFEST_PATH = ADDON_DIR / "blender_manifest.toml"

# Allow importing the client module directly without requiring bpy
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from client import AIStudioClient, AIStudioError  # noqa: E402


class TestBlenderAddonPackage(unittest.TestCase):
    def test_manifest_exists_and_parses(self):
        self.assertTrue(MANIFEST_PATH.is_file(), f"Manifest not found at {MANIFEST_PATH}")
        content = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = tomllib.loads(content)

        self.assertEqual(manifest.get("id"), "aistudio_bridge")
        self.assertEqual(manifest.get("version"), "0.1.0")
        self.assertEqual(manifest.get("blender_version_min"), "4.2.0")

        # License can be string or list containing SPDX:GPL-3.0-or-later
        lic = manifest.get("license")
        if isinstance(lic, list):
            self.assertTrue(
                any("GPL-3.0-or-later" in str(item) for item in lic),
                f"Expected GPL-3.0-or-later in license list, got {lic}",
            )
        else:
            self.assertIn("GPL-3.0-or-later", str(lic))

        # Permissions check
        permissions = manifest.get("permissions", {})
        self.assertIn("network", permissions)
        self.assertIn("files", permissions)
        self.assertEqual(permissions["network"], "talk to the local AI Studio server")
        self.assertEqual(permissions["files"], "save rendered frames temporarily")

    def test_init_and_python_files_compile(self):
        init_file = ADDON_DIR / "__init__.py"
        self.assertTrue(init_file.is_file(), "__init__.py not found")

        py_files = list(ADDON_DIR.glob("**/*.py"))
        self.assertTrue(len(py_files) >= 1)

        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            try:
                compiled = compile(source, str(py_file), "exec")
                self.assertIsNotNone(compiled)
            except SyntaxError as e:
                self.fail(f"Syntax error compiling {py_file}: {e}")

    def test_no_forbidden_network_imports(self):
        py_files = list(ADDON_DIR.glob("**/*.py"))
        forbidden_modules = {"requests", "httpx", "aiohttp", "socket", "http.client", "websocket"}

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertNotIn(
                            top,
                            forbidden_modules,
                            f"Disallowed network module {alias.name} imported in {py_file}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        self.assertNotIn(
                            top,
                            forbidden_modules,
                            f"Disallowed network module {node.module} imported in {py_file}",
                        )

    def test_no_shell_true_or_os_system(self):
        py_files = list(ADDON_DIR.glob("**/*.py"))

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check for os.system calls
                    if isinstance(node.func, ast.Attribute):
                        self.assertNotEqual(
                            node.func.attr,
                            "system",
                            f"os.system or similar call found in {py_file} at line {node.lineno}",
                        )
                    elif isinstance(node.func, ast.Name):
                        self.assertNotEqual(
                            node.func.id,
                            "system",
                            f"system() call found in {py_file} at line {node.lineno}",
                        )

                    # Check for shell=True or truthy shell keyword argument
                    for kw in node.keywords:
                        if kw.arg == "shell":
                            if isinstance(kw.value, ast.Constant):
                                self.assertFalse(
                                    bool(kw.value.value),
                                    f"shell=True found in {py_file} at line {node.lineno}",
                                )
                            else:
                                self.fail(
                                    f"Non-literal shell= argument found in {py_file} at line {node.lineno}"
                                )


class TestBlenderAddonClient(unittest.TestCase):
    def setUp(self):
        self.client = AIStudioClient(base_url="http://127.0.0.1:8765", token="test-token", timeout=2.0)

    @patch("urllib.request.urlopen")
    def test_pair_and_list_projects(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"projects": [{"name": "proj1"}, {"name": "proj2"}]}).encode("utf-8")
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        projects = self.client.pair()
        self.assertEqual(len(projects), 2)
        self.assertEqual(projects[0]["name"], "proj1")

        # Verify headers and URL
        call_args = mock_urlopen.call_args[0]
        req = call_args[0]
        self.assertEqual(req.get_full_url(), "http://127.0.0.1:8765/api/projects")
        self.assertEqual(req.get_header("X-aistudio-token"), "test-token")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token")

    @patch("urllib.request.urlopen")
    def test_get_shots_direct(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"shots": [{"id": "s01", "seconds": 4}]}).encode("utf-8")
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        shots = self.client.get_shots("proj1")
        self.assertIn("shots", shots)
        self.assertEqual(shots["shots"][0]["id"], "s01")

    @patch("urllib.request.urlopen")
    def test_get_shots_fallback_to_overview(self, mock_urlopen):
        # 1st call to /api/projects/proj1/shots raises HTTPError 404
        fp = io.BytesIO(b'{"detail":"Not Found"}')
        http_err = urllib.error.HTTPError("http://127.0.0.1:8765/api/projects/proj1/shots", 404, "Not Found", {}, fp)

        # 2nd call to /api/projects/proj1 succeeds with overview
        mock_overview = MagicMock()
        mock_overview.read.return_value = json.dumps({
            "name": "proj1",
            "shots": {"aspect_ratio": "9:16", "shots": [{"id": "s02", "seconds": 5}]},
        }).encode("utf-8")
        mock_overview.headers = {"Content-Type": "application/json"}
        mock_overview.__enter__.return_value = mock_overview

        mock_urlopen.side_effect = [http_err, mock_overview]

        shots = self.client.get_shots("proj1")
        self.assertEqual(shots["aspect_ratio"], "9:16")
        self.assertEqual(shots["shots"][0]["id"], "s02")
        fp.close()

    @patch("urllib.request.urlopen")
    def test_put_shots(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        doc = {"aspect_ratio": "16:9", "shots": [{"id": "s01", "prompt": "test"}]}
        res = self.client.put_shots("proj1", doc)
        self.assertTrue(res.get("ok"))

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "PUT")
        self.assertEqual(req.get_full_url(), "http://127.0.0.1:8765/api/projects/proj1/shots")
        self.assertEqual(json.loads(req.data.decode("utf-8")), doc)

    @patch("urllib.request.urlopen")
    def test_upload_frame(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        fake_png = b"\x89PNG\r\n\x1a\nfakeimagebytes"
        res = self.client.upload_frame("proj1", "stills/s01-blender-1.png", fake_png, replace=1)
        self.assertTrue(res.get("ok"))

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn("/api/projects/proj1/upload?rel=stills%2Fs01-blender-1.png&replace=1", req.get_full_url())
        self.assertEqual(req.data, fake_png)
        self.assertEqual(req.get_header("Content-type"), "image/png")

    @patch("urllib.request.urlopen")
    def test_send_camera_move(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"direction":{"movement":"dolly-in"}}'
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        payload = {"samples": [{"frame": 1, "matrix": [[1, 0, 0, 0]]}], "fps": 24.0, "lens_samples": []}
        res = self.client.send_camera_move("proj1", "s01", payload)
        self.assertIn("direction", res)

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_full_url(), "http://127.0.0.1:8765/api/projects/proj1/shots/s01/camera-move")
        self.assertEqual(json.loads(req.data.decode("utf-8")), payload)

    @patch("urllib.request.urlopen")
    def test_download_file(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"video-stream-content"
        mock_resp.headers = {"Content-Type": "video/mp4"}
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        data = self.client.download_file("proj1", "clips/s01_final_a1.mp4")
        self.assertEqual(data, b"video-stream-content")

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.get_full_url(), "http://127.0.0.1:8765/files/proj1/clips/s01_final_a1.mp4")

    @patch("urllib.request.urlopen")
    def test_error_handling(self, mock_urlopen):
        fp = io.BytesIO(b'{"detail":"Unauthorized token"}')
        http_err = urllib.error.HTTPError("http://127.0.0.1:8765/api/projects", 401, "Unauthorized", {}, fp)
        mock_urlopen.side_effect = http_err

        with self.assertRaises(AIStudioError) as ctx:
            self.client.list_projects()
        self.assertIn("401", str(ctx.exception))
        self.assertIn("Unauthorized token", str(ctx.exception))
        fp.close()


if __name__ == "__main__":
    unittest.main()
