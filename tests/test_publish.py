import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests._hermetic as HERM  # noqa: F401
from aistudio import publish


class Workspace:
    def __init__(self, root):
        self.root = Path(root)

    def pdir(self, project):
        return self.root / "projects" / project

    def _read(self, pdir, fn, default=None):
        path = Path(pdir) / fn
        return json.loads(path.read_text()) if path.exists() else default


class PublishTests(unittest.TestCase):
    def test_validation_normalizes_tags_and_strips_controls(self):
        doc = publish.validate({"platform": "youtube", "title": "<b>Hi</b>\x00\nthere", "description": "x<script>alert(1)</script>\x7f", "hashtags": [" #Hello World ", "helloWorld"]})
        self.assertEqual(doc["title"], "Hithere")
        self.assertEqual(doc["description"], "xalert(1)")
        self.assertEqual(doc["hashtags"], ["#HelloWorld"])
        with self.assertRaisesRegex(ValueError, "conservative"):
            publish.validate({"platform": "x", "title": "t" * 71})
        with self.assertRaisesRegex(ValueError, "invalid hashtag"):
            publish.validate({"platform": "youtube", "title": "ok", "hashtags": ["#x<script>"]})

    def test_save_archives_prior_publish_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            p = ws.pdir("demo")
            p.mkdir(parents=True)
            publish.save(ws, "demo", {"platform": "youtube", "title": "one"})
            publish.save(ws, "demo", {"platform": "youtube", "title": "two"})
            history = list((p / ".history" / "publish.json").glob("*.json"))
            self.assertEqual(len(history), 1)
            self.assertEqual(json.loads(history[0].read_text())["title"], "one")

    def test_draft_uses_chat_and_does_not_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            p = ws.pdir("demo")
            p.mkdir(parents=True)
            ws._ai_call = lambda project, role, messages: json.dumps({"platform": "youtube", "title": "Draft", "description": "Desc", "hashtags": ["#film"]})
            result = publish.draft_metadata(ws, "demo", "youtube")
            self.assertEqual(result["title"], "Draft")
            self.assertFalse((p / "publish.json").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_export_for_renders_preset_package_and_preflight_blocks_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            p = ws.pdir("demo")
            (p / "clips").mkdir(parents=True)
            generated = subprocess.run([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=360x640:r=24:d=1.2", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p / "clips" / "source.mp4")], capture_output=True)
            self.assertEqual(generated.returncode, 0, generated.stderr.decode(errors="replace"))
            (p / "edit.json").write_text(json.dumps({"aspect": "9:16", "fps": 24, "tracks": {"video": [{"id": "v1", "src": "clips/source.mp4", "in": 0, "out": 1.2}], "text": [], "audio": [], "elements": [], "subtitles": {"cues": [{"id": "c1", "start": 0, "end": 1, "text": "Hi"}]}}}))
            publish.save(ws, "demo", {"platform": "youtube", "title": "A title", "description": "A desc", "hashtags": ["#tag"]})
            result = publish.export_for(ws, "demo", "youtube-shorts")
            self.assertEqual(result["status"], "exported", result)
            out = p / "exports" / "youtube-shorts"
            self.assertTrue((out / "demo.mp4").is_file())
            self.assertTrue((out / "platform" / "title.txt").is_file())
            with patch("aistudio.publish.delivery.preflight", return_value=[{"level": "error", "code": "forced", "message": "blocked"}]):
                blocked = publish.export_for(ws, "demo", "youtube-shorts")
            self.assertEqual(blocked["status"], "draft")
            self.assertTrue(any(i["code"] == "forced" for i in blocked["findings"]))

    def test_no_network_upload_code(self):
        source = Path(publish.__file__).read_text(encoding="utf-8").lower()
        for token in ("urllib", "requests", "http.client"):
            self.assertNotIn(token, source)

    def test_publish_routes_reject_api_keys(self):
        try:
            from fastapi.testclient import TestClient
            from server.app import create_app
            from aistudio import apikeys
        except Exception as exc:
            self.skipTest(f"FastAPI test client unavailable: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            _, key = apikeys.create(tmp, "test-agent")
            client = TestClient(create_app(tmp, token="human", static_dir="/nonexistent"))
            for method, url, body in (("get", "/api/projects/demo/publish", None),
                                      ("put", "/api/projects/demo/publish", {"platform": "youtube", "title": "x"}),
                                      ("post", "/api/projects/demo/publish/draft", {"platform": "youtube"}),
                                      ("post", "/api/projects/demo/publish/export", {"preset": "youtube"}),
                                      ("post", "/api/projects/demo/publish/thumbnail", {"source": "clips/x.mp4"})):
                response = getattr(client, method)(url, headers={"x-aistudio-token": key}, json=body) if body is not None else getattr(client, method)(url, headers={"x-aistudio-token": key})
                self.assertEqual(response.status_code, 403, url)


if __name__ == "__main__":
    unittest.main()
