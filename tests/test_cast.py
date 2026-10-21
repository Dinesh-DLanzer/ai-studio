import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import unittest

from aistudio import costlog, tool_registry
from aistudio.service import ServiceError
from server import api_docs
from tests.test_flow import Base, logo_bytes

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False


class CastBase(Base):
    def setUp(self):
        super().setUp()
        self.interview()
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = 100
        (self.p / "budget.json").write_text(json.dumps(b))

    def images(self):
        return self.ws._read(self.p, "images.json")

    def run_image(self, target):
        prop = self.ws.propose("demo", "image", target)
        self.ws.approve_human("demo", prop["id"])
        return self.ws.execute("demo", prop["id"])


class ConsentTests(CastBase):
    def mark_real(self):
        doc = self.images()
        next(i for i in doc["images"] if i["id"] == "meena").update(real_person=True, subject="Asha Rao")
        self.ws.put_images("demo", doc)

    def test_generation_refused_without_consent_then_allowed_with_it(self):
        self.mark_real()
        with self.assertRaises(ServiceError) as e:
            self.ws.propose("demo", "image", "meena")
        self.assertIn("consent", str(e.exception))
        with self.assertRaises(ServiceError):                    # a frame that references the real person is refused too
            self.ws.propose("demo", "image", "s01")
        self.assertEqual(costlog.read_log(self.p), [])
        self.ws.consent_record("demo", "asha rao", "I agree to AI likeness use.")
        self.assertIn("file", self.run_image("meena"))

    def test_consent_is_rechecked_at_execute(self):
        prop = self.ws.propose("demo", "image", "meena")
        self.ws.approve_human("demo", prop["id"])
        self.mark_real()
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])
        self.assertEqual(costlog.read_log(self.p), [])

    def test_voice_consent_does_not_cover_a_real_person(self):
        self.mark_real()
        self.ws.consent_record("demo", "Asha Rao", "voice only", kind="voice")
        with self.assertRaises(ServiceError):
            self.ws.propose("demo", "image", "meena")

    def test_upload_marked_real_person_is_refused_without_consent(self):
        with self.assertRaises(ServiceError):
            self.ws.upload_image("demo", aid="asha", data=logo_bytes(), kind="character", real_person=True, subject="Asha Rao")
        self.assertFalse((self.p / "stills" / "asha.png").exists())
        self.ws.consent_record("demo", "Asha Rao", "ok")
        res = self.ws.upload_image("demo", aid="asha", data=logo_bytes(), kind="character", real_person=True, subject="Asha Rao")
        self.assertTrue(res["ok"])

    def test_record_validates(self):
        for args in (("", "x"), ("a", ""), ("a", "x", "bogus")):
            with self.assertRaises(ServiceError):
                self.ws.consent_record("demo", *args)

    def test_no_tool_can_write_consent_and_routes_are_human_only(self):
        self.assertFalse([n for n in tool_registry.TOOLS if "consent" in n])
        self.assertFalse([n for n in tool_registry.crew_tools() if "consent" in n])
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/consent"))
        self.assertTrue(api_docs.agent_allowed("GET", "/api/projects/{name}/consent"))


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx")
class ConsentApiTests(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.c = TestClient(create_app(tempfile.mkdtemp(), token="tok", static_dir="/nonexistent"))
        self.S = {"x-aistudio-token": "tok"}
        key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": key}
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)

    def test_api_key_cannot_write_consent_but_session_can(self):
        body = {"subject": "Asha", "statement": "I agree"}
        self.assertEqual(self.c.post("/api/projects/demo/consent", json=body, headers=self.A).status_code, 403)
        self.assertEqual(self.c.get("/api/projects/demo/consent", headers=self.S).json(), {"consent": []})
        self.assertEqual(self.c.post("/api/projects/demo/consent", json=body, headers=self.S).status_code, 200)
        self.assertEqual(self.c.get("/api/projects/demo/consent", headers=self.A).json()["consent"][0]["subject"], "Asha")


if __name__ == "__main__":
    unittest.main()
