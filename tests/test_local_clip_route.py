"""The local clip-tool route creates a new, project-contained free version."""
import tests._hermetic as HERM  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from server.app import create_app


class LocalClipRouteTest(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = Path(tempfile.mkdtemp())
        self.token = "local-clip-test"
        app = create_app(root=self.root, token=self.token)
        self.client = TestClient(app)
        app.state.ws.create_project("demo", test_pipeline=True)
        self.project = app.state.ws.pdir("demo")
        (self.project / "clips").mkdir(exist_ok=True)
        (self.project / "clips" / "s01_final_a1.mp4").write_bytes(b"fake clip")

    def test_local_transform_is_a_new_version_and_agent_safe(self):
        from unittest.mock import patch
        with patch("aistudio.tools.run_local", return_value=self.project.resolve() / "clips" / "s01_final_a1.v1.mp4") as run:
            out = self.client.post("/api/projects/demo/clips/s01_final_a1.mp4/local-tool", headers={"x-aistudio-token": self.token}, json={"tool": "speed", "params": {"factor": 2}})
        self.assertEqual(out.status_code, 200)
        self.assertEqual(out.json()["file"], "clips/s01_final_a1.v1.mp4")
        run.assert_called_once()

    def test_local_clip_route_is_documented(self):
        from server import api_docs
        self.assertTrue(api_docs.agent_allowed("POST", "/api/projects/{name}/clips/{shot_id}/local-tool"))
