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


class PickRefsTests(unittest.TestCase):
    DOC = {"images": [
        {"id": "ana", "kind": "character", "out": "stills/ana.png", "views": [
            {"id": "ana_front", "view": "front", "file": "stills/ana_front.png"},
            {"id": "ana_full", "view": "full-body", "file": "stills/ana_full.png"},
            {"id": "ana_prof", "view": "profile", "file": "stills/ana_prof.png"}]},
        {"id": "bo", "kind": "character", "out": "stills/bo.png"},
        {"id": "cafe", "kind": "background", "out": "stills/cafe.png"},
        {"id": "ink", "kind": "other", "role": "style", "out": "stills/ink.png"},
        {"id": "mug", "kind": "other", "role": "product", "out": "stills/mug.png"}]}

    def pick(self, framing, mx, refs=("mug", "ink", "cafe", "bo", "ana")):
        from aistudio.domain.characters import pick_refs
        shot = {"refs": list(refs), "direction": {"framing": framing} if framing else {}}
        kept, dropped = pick_refs(shot, {"references": {"max": mx}}, self.DOC)
        return [r["id"] for r in kept], [r["id"] for r in dropped]

    def test_close_up_uses_face_view_and_wide_uses_full_body(self):
        self.assertEqual(self.pick("close-up", 9)[0][:2], ["bo", "ana_front"])
        self.assertEqual(self.pick("wide", 9)[0][:2], ["bo", "ana_full"])
        self.assertEqual(self.pick(None, 9, ("bo",))[0], ["bo"])          # master image when a character has no views (plan 15 behaviour)

    def test_order_and_cut_to_limit(self):
        kept, dropped = self.pick("wide", 9)
        self.assertEqual(kept, ["bo", "ana_full", "cafe", "ink", "mug", "ana_front"])      # extra identity view is ranked last
        kept, dropped = self.pick("wide", 3)
        self.assertEqual((kept, dropped), (["bo", "ana_full", "cafe"], ["ink", "mug", "ana_front"]))
        self.assertEqual(self.pick("wide", 0), ([], ["bo", "ana_full", "cafe", "ink", "mug", "ana_front"]))


class IdentitySheetTests(CastBase):
    def setUp(self):
        super().setUp()
        self.run_image("meena")
        self.before = costlog.read_log(self.p)

    def test_sheet_is_an_unapproved_batch_whose_total_is_the_sum_of_items(self):
        batch = self.ws.identity_sheet("demo", "meena")
        self.assertEqual(batch["status"], "awaiting_approval")
        self.assertEqual([i["target"] for i in batch["items"]], ["meena_front", "meena_three_quarter", "meena_profile", "meena_full_body", "meena_expression"])
        self.assertEqual(batch["total"], round(sum(i["price"] for i in batch["items"]), 6))
        self.assertGreater(batch["total"], 0)
        self.assertEqual(costlog.read_log(self.p), self.before)                         # nothing spent
        self.assertEqual([x["status"] for x in json.loads((self.p / "proposals.json").read_text())], ["used"])    # no new proposal either
        doc = self.images()
        views = next(i for i in doc["images"] if i["id"] == "meena")["views"]
        self.assertEqual([v["view"] for v in views], ["front", "three-quarter", "profile", "full-body", "expression"])
        self.assertEqual(next(i for i in doc["images"] if i["id"] == "meena_front")["refs"], ["meena"])      # conditioned on the master
        with self.assertRaises(ServiceError):
            self.ws.batches.run("demo", batch["id"])                                    # unapproved batches cannot run

    def test_approved_sheet_runs_one_grant_and_cost_row_per_view(self):
        batch = self.ws.identity_sheet("demo", "meena", views=["front", "profile"])
        self.ws.estimate("demo", 0.2)           # new assets change the estimate: the budget gate makes a human re-approve it (not weakened)
        self.ws.approve_budget("demo")
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = 100
        (self.p / "budget.json").write_text(json.dumps(b))
        self.ws.batches.approve("demo", batch["id"], batch["batch_hash"])
        done = self.ws.batches.run("demo", batch["id"])
        self.assertEqual(done["status"], "done")
        new = costlog.read_log(self.p)[len(self.before):]
        self.assertEqual(len(new), 2)
        self.assertAlmostEqual(sum(float(r["cost"]) for r in new), batch["total"], places=6)
        self.assertTrue((self.p / "stills" / "meena_front.png").is_file())
        with self.assertRaises(ServiceError):                                           # views now exist: only the missing ones are offered
            self.ws.identity_sheet("demo", "meena", views=["front", "profile"])
        again = self.ws.identity_sheet("demo", "meena")
        self.assertEqual(len(again["items"]), 3)

    def test_needs_master_and_known_character(self):
        with self.assertRaises(ServiceError):
            self.ws.identity_sheet("demo", "nobody")
        with self.assertRaises(ServiceError):
            self.ws.identity_sheet("demo", "meena", views=["back"])

    def test_tool_is_paid_class_and_cannot_be_run_by_the_crew(self):
        self.assertEqual(tool_registry.cost_class("build_identity_sheet"), "paid")
        self.assertTrue(api_docs.agent_allowed("POST", "/api/projects/{name}/characters/{aid}/identity-sheet"))
        batch = tool_registry.TOOLS["build_identity_sheet"][2](self.ws, {"name": "demo", "character": "meena"})
        self.assertEqual((batch["status"], batch["actor"]), ("awaiting_approval", "mcp"))
        from aistudio.crew import runtime
        self.assertTrue(all(tool_registry.cost_class(n) in ("free", "paid") for n in tool_registry.crew_tools()))
        self.assertNotIn("approve_batch", tool_registry.crew_tools())
        self.assertNotIn("run_batch", tool_registry.crew_tools())
        self.assertTrue(hasattr(runtime, "_open_proposal"))


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
