"""Tests for the Blender server routes (plan 24): camera-move classification, direction apply,
headless previs.  No Blender and no network: the engine is mocked."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tests._hermetic  # noqa: F401
from aistudio import pairing
from aistudio.service import Workspace
from tests.test_camera_classify import make_look_at_matrix

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import api_docs
    HAVE = True
except Exception:      # fastapi is optional
    HAVE = False

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40
CAMERA_MOVE = "/api/projects/testproj/shots/{shot}/camera-move"
DIRECTION = "/api/projects/testproj/shots/{shot}/direction"


def dolly_in(frames=6, start=-5.0, step=1.0, target=(0.0, 10.0, 0.0)):
    """Camera samples that dolly towards the target (a straight push in)."""
    return [{"frame": i + 1, "matrix": make_look_at_matrix((0.0, start + i * step, 0.0), target)}
            for i in range(frames)]


@unittest.skipUnless(HAVE, "fastapi not installed")
class TestBlenderRoutes(unittest.TestCase):
    def setUp(self):
        tests._hermetic.all_test(self)
        self.root = tempfile.mkdtemp()
        self.session_token = "s" * 32
        os.environ["AISTUDIO_TOKEN"] = self.session_token
        self.ws = Workspace(self.root)
        self.ws.create_project("testproj")
        self.p = self.ws.pdir("testproj")
        (self.p / "shots.json").write_text(json.dumps({
            "aspect_ratio": "9:16",
            "shots": [
                {"id": "s01", "shot": 1, "model": "fake/clip", "seconds": 4, "prompt": "a dolly in on the hero"},
                {"id": "s02", "shot": 2, "model": "fake/clip", "seconds": 3, "prompt": "a wide of the street"},
            ],
        }))
        (self.p / "images.json").write_text(json.dumps({"style": "", "images": []}))

        # a paired device token (the Blender add-on) and an API key (an agent)
        _, code = pairing.start_pairing(self.root, self.ws.secrets)
        self.device_token = pairing.confirm_pairing(self.root, self.ws.secrets, code, "blender", "Blender Add-on")["device_token"]
        from aistudio import apikeys
        _, self.api_key = apikeys.create(self.root, "test-agent")

        self.app = create_app(self.root, auto_verify=False)
        self.c = TestClient(self.app)
        self.human_headers = {"x-aistudio-token": self.session_token}
        self.device_headers = {"authorization": f"Bearer {self.device_token}"}
        self.agent_headers = {"authorization": f"Bearer {self.api_key}"}

    def tearDown(self):
        os.environ.pop("AISTUDIO_TOKEN", None)

    def shots(self):
        return json.loads((self.p / "shots.json").read_text())["shots"]

    def post_json(self, path, payload, headers=None):
        """Post raw JSON: httpx refuses NaN, the server must still refuse it."""
        head = {"content-type": "application/json"}
        head.update(headers or self.human_headers)
        return self.c.post(path, headers=head, content=json.dumps(payload).encode("utf-8"))

    # ---------------------------------------------------------------- camera move
    def test_camera_move_classifies_and_saves_nothing(self):
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers,
                          json={"samples": dolly_in(), "fps": 24.0})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["shot"], "s01")
        self.assertEqual(body["classification"]["movement"], "dolly-in")
        self.assertIn("confidence", body["classification"])
        self.assertIn("evidence", body["classification"])
        self.assertEqual(body["direction"]["movement"], "dolly-in")
        self.assertFalse(body["saved"])
        # nothing was written
        self.assertNotIn("direction", self.shots()[0])
        self.assertEqual(json.loads((self.p / "shots.json").read_text())["shots"][0]["id"], "s01")

    def test_camera_move_accepts_plain_matrices_and_lens_samples(self):
        samples = [m["matrix"] for m in dolly_in()]
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers,
                          json={"samples": samples, "fps": 24.0,
                                "lens_samples": [{"frame": 1, "focal_length": 50.0, "sensor_width": 36.0}]})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["direction"]["movement"], "dolly-in")
        self.assertEqual(body["direction"]["lens_mm"], 50.0)

    def test_camera_move_rejects_too_many_samples(self):
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers,
                          json={"samples": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]] * 501, "fps": 24.0})
        self.assertEqual(res.status_code, 400)
        self.assertIn("too many samples", res.json()["detail"])

    def test_camera_move_rejects_nan_and_inf(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            matrix = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
            matrix[1][2] = bad
            res = self.post_json(CAMERA_MOVE.format(shot="s01"), {"samples": [matrix, matrix], "fps": 24.0})
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("finite", res.json()["detail"])
        # a NaN in the lens samples is refused too
        res = self.post_json(CAMERA_MOVE.format(shot="s01"),
                             {"samples": dolly_in(), "fps": 24.0, "lens_samples": [50.0, float("nan")]})
        self.assertEqual(res.status_code, 400)

    def test_camera_move_rejects_bad_shapes_and_fps(self):
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers, json={"samples": [], "fps": 24.0})
        self.assertEqual(res.status_code, 400)
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers,
                          json={"samples": [[[1, 0, 0], [0, 1, 0], [0, 0, 1]]], "fps": 24.0})
        self.assertEqual(res.status_code, 400)
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.human_headers,
                          json={"samples": dolly_in(), "fps": 0})
        self.assertEqual(res.status_code, 400)
        res = self.c.post(CAMERA_MOVE.format(shot="s99"), headers=self.human_headers,
                          json={"samples": dolly_in(), "fps": 24.0})
        self.assertEqual(res.status_code, 400)

    def test_a_broken_body_is_a_400(self):
        res = self.c.post(CAMERA_MOVE.format(shot="s01"),
                          headers={**self.human_headers, "content-type": "application/json"},
                          content=b"{not json")
        self.assertEqual(res.status_code, 400)
        res = self.c.post(DIRECTION.format(shot="s01"),
                          headers={**self.human_headers, "content-type": "application/json"},
                          content=b"{not json")
        self.assertEqual(res.status_code, 400)

    # ---------------------------------------------------------------- direction
    def test_direction_applies_validates_and_keeps_unknown_keys(self):
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers,
                          json={"direction": {"movement": "dolly-in", "speed": "normal", "blender_note": "from the add-on"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["direction"]["movement"], "dolly-in")
        shot = self.shots()[0]
        self.assertEqual(shot["direction"]["movement"], "dolly-in")
        self.assertEqual(shot["direction"]["speed"], "normal")
        self.assertEqual(shot["direction"]["blender_note"], "from the add-on")     # unknown keys are kept
        # the rest of the shot is untouched
        self.assertEqual(shot["prompt"], "a dolly in on the hero")
        self.assertEqual(shot["seconds"], 4)
        # the previous version is in the history
        versions = list((self.p / ".history" / "shots.json").glob("*.json"))
        self.assertTrue(versions, "the direction change must be recorded in the history")

    def test_direction_refuses_an_invalid_enum(self):
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers,
                          json={"direction": {"movement": "crash-zoom"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("movement", res.json()["detail"])
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers,
                          json={"direction": {"framing": "super-wide"}})
        self.assertEqual(res.status_code, 400)
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers,
                          json={"direction": {"lens_mm": -5}})
        self.assertEqual(res.status_code, 400)
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers,
                          json={"direction": "dolly-in"})
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("direction", self.shots()[0])

    def test_direction_merges_into_the_existing_direction(self):
        self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers, json={"direction": {"movement": "dolly-in"}})
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.human_headers, json={"direction": {"speed": "slow"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.shots()[0]["direction"], {"movement": "dolly-in", "speed": "slow"})

    # ---------------------------------------------------------------- previs
    def _blend(self, rel="scenes/main.blend"):
        f = self.p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"BLENDER")
        return rel

    def test_previs_render_runs_a_free_ledger_job(self):
        blend = self._blend()
        seen = {}

        def fake_run_previs(blend=None, out_dir=None, shots=None, project_dir=None, **kw):
            seen.update({"blend": blend, "out_dir": out_dir, "shots": list(shots or []), "project_dir": project_dir})
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            for sid in shots or []:
                (Path(out_dir) / f"{sid}.png").write_bytes(PNG)
            return [{"shot": sid, "frame": str(Path(out_dir) / f"{sid}.png")} for sid in shots or []]

        with patch("aistudio.engines.blender.run_previs", side_effect=fake_run_previs):
            res = self.c.post("/api/projects/testproj/previs/render", headers=self.human_headers,
                              json={"blend": blend, "shots": ["s01", "s02"]})
            self.assertEqual(res.status_code, 200)
            jid = res.json()["job"]
            self.assertTrue(jid)
            job = self._wait_for_job(jid)

        self.assertEqual(job["state"], "completed", job)
        self.assertEqual(seen["shots"], ["s01", "s02"])
        self.assertEqual(Path(seen["out_dir"]).name, "previs")
        self.assertEqual(Path(seen["out_dir"]).parent, self.p.resolve())
        self.assertEqual(Path(seen["blend"]), (self.p / blend).resolve())
        # the frames are on disk, inside the project
        self.assertTrue((self.p / "previs" / "s01.png").is_file())

        # the ledger knows the job and its kind
        jobs = self.c.get("/api/jobs?project=testproj", headers=self.human_headers).json()["jobs"]
        row = next(j for j in jobs if j["id"] == jid)
        self.assertEqual(row["kind"], "previs")
        self.assertEqual(row["state"], "completed")

    def test_previs_frames_are_listed_but_never_registered(self):
        (self.p / "previs").mkdir(exist_ok=True)
        (self.p / "previs" / "s01.png").write_bytes(PNG)
        res = self.c.get("/api/projects/testproj/previs", headers=self.human_headers)
        self.assertEqual(res.status_code, 200)
        outputs = res.json()["outputs"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["file"], "previs/s01.png")
        self.assertEqual(outputs[0]["shot"], "s01")
        self.assertTrue(outputs[0]["image"])
        self.assertFalse(outputs[0]["registered"])
        # nothing was registered as a still
        self.assertEqual(json.loads((self.p / "images.json").read_text())["images"], [])

    def test_previs_refuses_a_path_outside_the_project(self):
        outside = Path(self.root) / "outside.blend"
        outside.write_bytes(b"BLENDER")
        for blend in ("../outside.blend", str(outside), "/etc/passwd.blend", "scenes/../../outside.blend"):
            res = self.c.post("/api/projects/testproj/previs/render", headers=self.human_headers,
                              json={"blend": blend, "shots": ["s01"]})
            self.assertEqual(res.status_code, 400, blend)
        res = self.c.post("/api/projects/testproj/previs/render", headers=self.human_headers,
                          json={"blend": "scenes/main.blend", "shots": ["s01"]})
        self.assertEqual(res.status_code, 400)      # the file does not exist

    def test_previs_refuses_unknown_shots(self):
        blend = self._blend()
        res = self.c.post("/api/projects/testproj/previs/render", headers=self.human_headers,
                          json={"blend": blend, "shots": ["nope"]})
        self.assertEqual(res.status_code, 400)
        res = self.c.post("/api/projects/testproj/previs/render", headers=self.human_headers,
                          json={"blend": blend, "shots": []})
        self.assertEqual(res.status_code, 400)

    def _wait_for_job(self, jid, timeout=20.0):
        deadline = time.time() + timeout
        job = {}
        while time.time() < deadline:
            job = self.c.get(f"/api/jobs/{jid}", headers=self.human_headers).json()
            if job.get("state") in ("completed", "failed", "cancelled", "needs_sync"):
                return job
            time.sleep(0.05)
        return job

    # ---------------------------------------------------------------- who may call what
    def test_api_keys_are_refused_everywhere(self):
        self._blend()
        calls = [
            ("post", CAMERA_MOVE.format(shot="s01"), {"samples": dolly_in(), "fps": 24.0}),
            ("post", DIRECTION.format(shot="s01"), {"direction": {"movement": "dolly-in"}}),
            ("post", "/api/projects/testproj/previs/render", {"blend": "scenes/main.blend", "shots": ["s01"]}),
            ("get", "/api/projects/testproj/previs", None),
        ]
        for method, path, body in calls:
            res = self.c.request(method.upper(), path, headers=self.agent_headers, json=body)
            self.assertEqual(res.status_code, 403, path)
        self.assertNotIn("direction", self.shots()[0])

    def test_a_device_token_may_preview_but_not_write(self):
        res = self.c.post(CAMERA_MOVE.format(shot="s01"), headers=self.device_headers,
                          json={"samples": dolly_in(), "fps": 24.0})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["classification"]["movement"], "dolly-in")
        # a device may not apply a direction, render previs or read the project files
        res = self.c.post(DIRECTION.format(shot="s01"), headers=self.device_headers,
                          json={"direction": {"movement": "dolly-in"}})
        self.assertEqual(res.status_code, 403)
        res = self.c.post("/api/projects/testproj/previs/render", headers=self.device_headers,
                          json={"blend": "scenes/main.blend", "shots": ["s01"]})
        self.assertEqual(res.status_code, 403)
        res = self.c.get("/api/projects/testproj/previs", headers=self.device_headers)
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("direction", self.shots()[0])

    def test_the_routes_are_documented(self):
        self.assertEqual(api_docs.undocumented(self.app), [])
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/shots/{shot}/camera-move"))
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/shots/{shot}/direction"))
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/previs/render"))
        self.assertFalse(api_docs.agent_allowed("GET", "/api/projects/{name}/previs"))
        self.assertTrue(api_docs.device_allowed("POST", "/api/projects/{name}/shots/{shot}/camera-move"))
        self.assertFalse(api_docs.device_allowed("POST", "/api/projects/{name}/shots/{shot}/direction"))
        self.assertFalse(api_docs.device_allowed("POST", "/api/projects/{name}/previs/render"))


if __name__ == "__main__":
    unittest.main()
