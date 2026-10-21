import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from aistudio import apikeys
from server.app import create_app


class ExportRouteTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.client = TestClient(create_app(self.root, token="human", static_dir="/missing"))
        self.client.post("/api/projects", headers={"x-aistudio-token": "human"}, json={"name": "demo"})
        self.project = Path(self.root) / "projects" / "demo"
        (self.project / "clips").mkdir(exist_ok=True)
        (self.project / "clips" / "one.mp4").write_bytes(b"not real video; exporters do not probe duration")
        self.client.put("/api/projects/demo/edit", headers={"x-aistudio-token": "human"}, json={
            "tracks": {"video": [{"id": "one", "src": "clips/one.mp4", "in": 0, "out": 1}],
                       "subtitles": {"cues": [{"id": "cap", "start": 0, "end": 1, "text": "hello"}]}}})

    def test_downloads_interchange_formats_and_otioz_is_relative(self):
        for fmt, expected in (("otio", b"Timeline.1"), ("xmeml", b"xmeml"), ("fcpxml", b"fcpxml"),
                              ("edl", b"FCM:"), ("srt", b"hello"), ("vtt", b"WEBVTT"), ("bundle", b"PK")):
            response = self.client.get(f"/api/projects/demo/edit/export/{fmt}", headers={"x-aistudio-token": "human"})
            self.assertEqual(response.status_code, 200, fmt)
            self.assertIn(expected, response.content, fmt)
        z = self.client.get("/api/projects/demo/edit/export/otioz", headers={"x-aistudio-token": "human"})
        self.assertEqual(z.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"content.otio", "media/clips/one.mp4"})
            otio = json.loads(archive.read("content.otio"))
            ref = otio["tracks"]["children"][0]["children"][0]["media_reference"]["target_url"]
            self.assertEqual(ref, "media/clips/one.mp4")

    def test_external_edit_is_human_only_and_import_is_preview(self):
        before = (self.project / "edit.json").read_bytes()
        response = self.client.post("/api/projects/demo/edit/import-otio", headers={"x-aistudio-token": "human"},
                                    json={"otio": '{"OTIO_SCHEMA":"Timeline.1","tracks":{"children":[]}}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.project / "edit.json").read_bytes(), before)
        _, key = apikeys.create(self.root, "worker")
        for method, path in (("get", "/api/projects/demo/external-edit"),
                              ("post", "/api/projects/demo/external-edit"),
                              ("post", "/api/projects/demo/external-edit/stop")):
            self.assertEqual(getattr(self.client, method)(path, headers={"x-aistudio-token": key}).status_code, 403)

    def test_external_edit_rejects_traversal_and_app_path(self):
        headers = {"x-aistudio-token": "human"}
        bad_file = self.client.post("/api/projects/demo/external-edit", headers=headers, json={"file": "../secret.png"})
        self.assertEqual(bad_file.status_code, 400)
        bad_app = self.client.put("/api/external-apps", headers=headers, json={"apps": ["../../evil"]})
        self.assertEqual(bad_app.status_code, 400)

    def test_import_preview_uses_project_clips_and_lists_unknowns(self):
        p = self.project
        self.client.put("/api/projects/demo/edit", headers={"x-aistudio-token": "human"}, json={
            "tracks": {"video": [{"id": "one", "src": "clips/one.mp4", "in": 0, "out": 1}]}})
        before = (p / "edit.json").read_bytes()
        timeline = {"OTIO_SCHEMA": "Timeline.1", "tracks": {"children": [{"OTIO_SCHEMA": "Track.1", "kind": "Video", "children": [
            {"OTIO_SCHEMA": "Clip.2", "name": "outside", "media_reference": {"target_url": "file:///tmp/outside.mp4"},
             "source_range": {"start_time": {"value": 0, "rate": 24}, "duration": {"value": 24, "rate": 24}}}]}]}}
        r = self.client.post("/api/projects/demo/edit/import-otio", headers={"x-aistudio-token": "human"}, json={"otio": json.dumps(timeline)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ignored"], ["outside"])
        self.assertEqual((p / "edit.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
