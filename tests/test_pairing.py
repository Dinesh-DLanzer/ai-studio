import tests._hermetic  # noqa: F401
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from aistudio.secrets import SecretStore
from aistudio import pairing
try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import api_docs
    HAVE = True
except Exception:
    HAVE = False


class TestPairingModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.secrets = SecretStore(self.tmp)

    def test_start_pairing_creates_challenge_without_code_in_storage(self):
        challenge, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        self.assertTrue(challenge["id"])
        self.assertEqual(challenge["created"], 1000.0)
        self.assertEqual(challenge["expires"], 1600.0)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

        # Check storage: code MUST NOT be stored
        stored = json.loads((Path(self.tmp) / "settings" / "pairing_challenges.json").read_text())
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], challenge["id"])
        self.assertNotIn("code", stored[0])
        self.assertNotIn(code, json.dumps(stored))

    def test_confirm_pairing_success_and_single_use(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        result = pairing.confirm_pairing(self.tmp, self.secrets, code, "premiere", "Studio Mac", now=1005.0)
        token = result["device_token"]
        self.assertTrue(token.startswith(pairing.DEVICE_PREFIX))
        self.assertEqual(result["device"]["host"], "premiere")
        self.assertEqual(result["device"]["device_name"], "Studio Mac")
        self.assertEqual(result["device"]["expires"], 1005.0 + 30 * 86400)

        # Check storage: raw token is NOT stored, only hash
        stored_devs = json.loads((Path(self.tmp) / "settings" / "paired_devices.json").read_text())
        self.assertEqual(len(stored_devs), 1)
        self.assertNotIn(token, json.dumps(stored_devs))
        self.assertEqual(stored_devs[0]["hash"], hashlib.sha256(token.encode("utf-8")).hexdigest())

        # Single-use check: confirming again fails
        with self.assertRaises(pairing.PairingError):
            pairing.confirm_pairing(self.tmp, self.secrets, code, "premiere", "Studio Mac 2", now=1010.0)

    def test_confirm_pairing_invalid_host(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        with self.assertRaises(pairing.PairingError) as ctx:
            pairing.confirm_pairing(self.tmp, self.secrets, code, "finalcut", "Mac", now=1005.0)
        self.assertIn("host", str(ctx.exception).lower())

    def test_confirm_pairing_invalid_device_name(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        with self.assertRaises(pairing.PairingError):
            pairing.confirm_pairing(self.tmp, self.secrets, code, "premiere", "", now=1005.0)

    def test_confirm_pairing_expiry(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        with self.assertRaises(pairing.PairingError) as ctx:
            pairing.confirm_pairing(self.tmp, self.secrets, code, "resolve", "Mac", now=1601.0)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_confirm_pairing_lock_after_five_wrong_tries(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        for i in range(4):
            with self.assertRaises(pairing.PairingError):
                pairing.confirm_pairing(self.tmp, self.secrets, "000000", "blender", "PC", now=1005.0 + i)
        # 5th wrong try locks the challenge
        with self.assertRaises(pairing.PairingError) as ctx:
            pairing.confirm_pairing(self.tmp, self.secrets, "000000", "blender", "PC", now=1010.0)
        self.assertIn("locked", str(ctx.exception).lower())

        # Even correct code fails now because it's locked
        with self.assertRaises(pairing.PairingError) as ctx:
            pairing.confirm_pairing(self.tmp, self.secrets, code, "blender", "PC", now=1015.0)
        self.assertIn("locked", str(ctx.exception).lower())

    def test_verify_and_revoke_device(self):
        _, code = pairing.start_pairing(self.tmp, self.secrets, now=1000.0)
        result = pairing.confirm_pairing(self.tmp, self.secrets, code, "aftereffects", "AE Box", now=1005.0)
        token = result["device_token"]

        rec = pairing.verify_device(self.tmp, token, now=1010.0)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["device_name"], "AE Box")
        self.assertEqual(rec["host"], "aftereffects")

        # Wrong token
        self.assertIsNone(pairing.verify_device(self.tmp, token + "x", now=1010.0))
        self.assertIsNone(pairing.verify_device(self.tmp, "aisd_invalid", now=1010.0))
        self.assertIsNone(pairing.verify_device(self.tmp, "aisk_notadevice", now=1010.0))

        # List devices
        devs = pairing.list_devices(self.tmp)
        self.assertEqual(len(devs), 1)
        self.assertEqual(devs[0]["device_name"], "AE Box")
        self.assertNotIn("hash", devs[0])

        # Revoke
        pairing.revoke_device(self.tmp, rec["id"])
        self.assertIsNone(pairing.verify_device(self.tmp, token, now=1020.0))
        self.assertEqual(len(pairing.list_devices(self.tmp)), 0)


@unittest.skipUnless(HAVE, "fastapi not installed")
class TestPairingApi(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session_token = "s" * 32
        os.environ["AISTUDIO_TOKEN"] = self.session_token
        from aistudio.service import Workspace
        self.ws = Workspace(self.root)
        self.ws.create_project("demo")
        self.app = create_app(self.root)
        self.c = TestClient(self.app)
        self.H = {"x-aistudio-token": self.session_token}

    def tearDown(self):
        os.environ.pop("AISTUDIO_TOKEN", None)

    def test_pair_start_human_session_only(self):
        # Unauthenticated -> 401
        res = self.c.post("/api/pair/start")
        self.assertEqual(res.status_code, 401)

        # Successful start with human session
        res = self.c.post("/api/pair/start", headers=self.H)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("id"))
        self.assertTrue(data.get("expires"))
        # Crucial check: code is NEVER in the response
        self.assertNotIn("code", data)

        # Code is shown in human notifications
        notif_res = self.c.get("/api/approval-notifications", headers=self.H)
        self.assertEqual(notif_res.status_code, 200)
        notifs = notif_res.json().get("notifications", [])
        self.assertTrue(any(n.get("id") == data["id"] and "code" in n for n in notifs))
        code = next(n["code"] for n in notifs if n.get("id") == data["id"])
        self.assertEqual(len(code), 6)

        # Confirm pairing via public endpoint
        conf_res = self.c.post("/api/pair/confirm", json={
            "code": code,
            "host": "premiere",
            "device_name": "Editor Studio 1"
        })
        self.assertEqual(conf_res.status_code, 200)
        conf_data = conf_res.json()
        device_token = conf_data.get("device_token")
        self.assertTrue(device_token and device_token.startswith("aisd_"))

        # Device token cannot call pair/start (human session only)
        dev_h = {"authorization": f"Bearer {device_token}"}
        res_dev = self.c.post("/api/pair/start", headers=dev_h)
        self.assertEqual(res_dev.status_code, 403)

        # GET /api/pair/devices (human session only)
        devs_res = self.c.get("/api/pair/devices", headers=self.H)
        self.assertEqual(devs_res.status_code, 200)
        dev_list = devs_res.json().get("devices", [])
        self.assertEqual(len(dev_list), 1)
        self.assertEqual(dev_list[0]["host"], "premiere")
        self.assertEqual(dev_list[0]["device_name"], "Editor Studio 1")

        # Device token cannot call GET /api/pair/devices
        res_list_dev = self.c.get("/api/pair/devices", headers=dev_h)
        self.assertEqual(res_list_dev.status_code, 403)

        # DELETE /api/pair/devices/{id} (human session only)
        dev_id = dev_list[0]["id"]
        res_del_dev = self.c.delete(f"/api/pair/devices/{dev_id}", headers=dev_h)
        self.assertEqual(res_del_dev.status_code, 403)

        # Human revokes
        res_del = self.c.delete(f"/api/pair/devices/{dev_id}", headers=self.H)
        self.assertEqual(res_del.status_code, 200)

        # Once revoked, device token returns 401
        res_after = self.c.get("/api/projects", headers=dev_h)
        self.assertEqual(res_after.status_code, 401)

    def test_pair_code_single_use_and_lock_api(self):
        # Start pairing
        res = self.c.post("/api/pair/start", headers=self.H)
        cid = res.json()["id"]

        # Get code from notifications
        notifs = self.c.get("/api/approval-notifications", headers=self.H).json()["notifications"]
        code = next(n["code"] for n in notifs if n["id"] == cid)

        # 4 wrong tries
        for _ in range(4):
            r = self.c.post("/api/pair/confirm", json={"code": "000000", "host": "blender", "device_name": "Box"})
            self.assertEqual(r.status_code, 400)

        # 5th wrong try locks the challenge
        r5 = self.c.post("/api/pair/confirm", json={"code": "000000", "host": "blender", "device_name": "Box"})
        self.assertEqual(r5.status_code, 400)
        self.assertIn("locked", r5.json().get("detail", "").lower())

        # Correct code now fails because locked
        r_correct = self.c.post("/api/pair/confirm", json={"code": code, "host": "blender", "device_name": "Box"})
        self.assertEqual(r_correct.status_code, 400)
        self.assertIn("locked", r_correct.json().get("detail", "").lower())

    def test_expired_device_token_returns_401(self):
        res = self.c.post("/api/pair/start", headers=self.H)
        cid = res.json()["id"]
        notifs = self.c.get("/api/approval-notifications", headers=self.H).json()["notifications"]
        code = next(n["code"] for n in notifs if n["id"] == cid)

        conf = self.c.post("/api/pair/confirm", json={"code": code, "host": "resolve", "device_name": "Color Suite"}).json()
        token = conf["device_token"]

        # Artificially expire the token in settings/paired_devices.json
        dev_file = Path(self.root) / "settings" / "paired_devices.json"
        devs = json.loads(dev_file.read_text())
        devs[0]["expires"] = 10.0
        dev_file.write_text(json.dumps(devs))

        # Request with expired token -> 401
        dev_h = {"authorization": f"Bearer {token}"}
        res = self.c.get("/api/projects", headers=dev_h)
        self.assertEqual(res.status_code, 401)

    def test_code_never_in_responses_or_project_files(self):
        # Start pairing
        res = self.c.post("/api/pair/start", headers=self.H)
        data = res.json()
        cid = data["id"]
        notifs = self.c.get("/api/approval-notifications", headers=self.H).json()["notifications"]
        code = next(n["code"] for n in notifs if n["id"] == cid)

        # Check start response body
        self.assertNotIn(code, json.dumps(data))

        # Check confirm response body
        conf_res = self.c.post("/api/pair/confirm", json={"code": code, "host": "premiere", "device_name": "NLE 1"})
        conf_data = conf_res.json()
        self.assertNotIn(code, json.dumps(conf_data))

        # Check devices list response body
        devs_data = self.c.get("/api/pair/devices", headers=self.H).json()
        self.assertNotIn(code, json.dumps(devs_data))

        # Check project files: code must NEVER appear in any file under projects/
        pdir = Path(self.root) / "projects"
        if pdir.exists():
            for root, _, files in os.walk(pdir):
                for f in files:
                    content = (Path(root) / f).read_bytes()
                    self.assertNotIn(code.encode("utf-8"), content, f"Code leaked into project file: {f}")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE, "fastapi not installed")
class TestAuthReviewFixes(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.session_token = "s" * 32
        os.environ["AISTUDIO_TOKEN"] = self.session_token
        from aistudio.service import Workspace
        Workspace(self.root).create_project("demo")
        self.c = TestClient(create_app(self.root))
        self.H = {"x-aistudio-token": self.session_token}

    def tearDown(self):
        os.environ.pop("AISTUDIO_TOKEN", None)

    def _device_token(self):
        cid = self.c.post("/api/pair/start", headers=self.H).json()["id"]
        notifs = self.c.get("/api/approval-notifications", headers=self.H).json()["notifications"]
        code = next(n["code"] for n in notifs if n["id"] == cid)
        res = self.c.post("/api/pair/confirm", json={"code": code, "host": "premiere", "device_name": "t"})
        return res.json()["device_token"]

    def test_a_device_token_in_the_url_is_refused_even_with_an_unrelated_authorization_header(self):
        tok = self._device_token()
        self.assertEqual(self.c.get("/api/projects", headers={"x-aistudio-token": tok}).status_code, 200)
        self.assertEqual(self.c.get("/api/projects", params={"token": tok}).status_code, 401)
        self.assertEqual(self.c.get("/api/projects", params={"token": tok}, headers={"Authorization": "Basic eDp4"}).status_code, 401)

    def test_pairing_confirm_is_single_use_across_threads(self):
        import threading
        secrets_store = SecretStore(self.root)
        root = tempfile.mkdtemp()
        _, code = pairing.start_pairing(root, secrets_store)
        results = []

        def go():
            try:
                results.append(pairing.confirm_pairing(root, secrets_store, code, "blender", "dev"))
            except pairing.PairingError as e:
                results.append(e)
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        issued = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(issued), 1, results)

    def test_the_public_confirm_route_limits_request_volume(self):
        codes = [self.c.post("/api/pair/confirm", json={"code": "000000", "host": "blender", "device_name": "x"}).status_code for _ in range(25)]
        self.assertEqual(codes[-1], 429)

    def test_review_package_route_is_wired(self):
        res = self.c.post("/api/projects/demo/review-package", headers=self.H, json={})
        self.assertNotEqual(res.status_code, 500)      # a missing import used to raise NameError here


@unittest.skipUnless(HAVE, "fastapi not installed")
class TestMediaListingIncludesGeneratedAudio(unittest.TestCase):
    def test_audio_in_subfolders_is_listed(self):
        root = tempfile.mkdtemp()
        from aistudio.service import Workspace
        ws = Workspace(root)
        ws.create_project("demo")
        d = Path(root) / "projects" / "demo" / "audio" / "vo"
        d.mkdir(parents=True)
        (d / "s1.v1.mp3").write_bytes(b"x")
        names = json.dumps(ws.list_media("demo", approved_only=False) if "approved_only" in ws.list_media.__code__.co_varnames else ws.list_media("demo"))
        self.assertIn("audio/vo/s1.v1.mp3", names)
