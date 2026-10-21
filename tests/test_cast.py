import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import unittest
from unittest.mock import patch

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


class MetadataTests(CastBase):
    def meta(self, rel):
        return json.loads((self.p / (rel + ".meta.json")).read_text())

    def test_image_and_clip_outputs_get_meta_after_the_cost_row(self):
        for t in ("meena", "main_place"):
            self.run_image(t)
        res = self.run_image("s01")
        m = self.meta(res["file"])
        self.assertEqual((m["kind"], m["target"], m["seed"], m["actor"]), ("image", "s01", "not sent", "local"))
        self.assertEqual({r["id"] for r in m["refs"]}, {"meena", "main_place"})
        self.assertTrue(all(len(r["sha"]) == 64 for r in m["refs"]))
        self.assertEqual(m["cost"], res["cost"])
        self.assertEqual(len(m["spec_hash"]), 64)
        self.assertTrue(m["prompt"] and m["model"] and m["provider"] and m["created"])
        prop = self.ws.propose("demo", "clip", "s01")
        self.ws.approve_human("demo", prop["id"])
        clip = self.ws.execute("demo", prop["id"])
        cm = self.meta(clip["file"])
        self.assertEqual((cm["kind"], cm["params"]["seconds"], cm["spec_hash"]), ("clip", 4, self.ws.proposal_status("demo", prop["id"])["hash"]))
        self.assertEqual(cm["refs"][0]["id"], "s01")
        self.assertNotIn("s01.png.meta.json", self.ws.overview("demo")["files"]["stills"])      # sidecars stay out of the file lists

    def test_meta_failure_never_loses_the_paid_result(self):
        from unittest.mock import patch
        from aistudio import project
        real = project.save_json
        def boom(pdir, fn, data):
            if fn.endswith(".meta.json"):
                raise OSError("disk")
            return real(pdir, fn, data)
        with patch.object(project, "save_json", side_effect=boom):
            res = self.run_image("meena")
        self.assertTrue((self.p / res["file"]).is_file())
        self.assertEqual(costlog.read_log(self.p)[-1]["result"], "completed")

    def test_remix_is_a_pending_proposal_only(self):
        res = self.run_image("meena")
        rows = costlog.read_log(self.p)
        out = self.ws.remix("demo", res["file"] + ".meta.json")
        prop = out["proposal"]
        self.assertEqual((prop["status"], prop["kind"], prop["shot"]), ("pending", "image", "meena"))
        self.assertNotIn("code", prop)
        self.assertEqual(out["changed"], {"prompt": False, "model": False, "refs": False})
        self.assertEqual(costlog.read_log(self.p), rows)
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])                    # not approved: no spend
        for bad in ("../x.meta.json", "stills/meena.png", "stills/missing.meta.json"):
            with self.assertRaises(ServiceError):
                self.ws.remix("demo", bad)


class VariantTests(CastBase):
    def setUp(self):
        super().setUp()
        for t in ("meena", "main_place", "s01"):
            self.run_image(t)
        self.before = costlog.read_log(self.p)

    def approve_and_run(self, batch):
        self.ws.batches.approve("demo", batch["id"], batch["batch_hash"])
        return self.ws.batches.run("demo", batch["id"])

    def test_variant_batch_total_is_n_times_unit_and_each_item_is_its_own_proposal(self):
        unit = self.ws.spec("demo", "image", "s01")["price"]
        batch = self.ws.propose_variants("demo", "image", "s01", 3)
        self.assertEqual((batch["status"], len(batch["items"])), ("awaiting_approval", 3))
        self.assertEqual(batch["total"], round(3 * unit, 6))
        self.assertEqual(batch["total"], round(sum(i["price"] for i in batch["items"]), 6))
        self.assertEqual(len({i["request_hash"] for i in batch["items"]}), 3)
        self.assertEqual(costlog.read_log(self.p), self.before)                          # creating spends nothing
        with self.assertRaises(ServiceError):
            self.ws.batches.run("demo", batch["id"])                                     # and nothing runs unapproved
        done = self.approve_and_run(batch)
        self.assertEqual(done["status"], "done")
        new = costlog.read_log(self.p)[len(self.before):]
        self.assertEqual(sorted(r["shot"] for r in new), ["s01.v1", "s01.v2", "s01.v3"])
        self.assertAlmostEqual(sum(float(r["cost"]) for r in new), batch["total"], places=6)
        used = [x for x in json.loads((self.p / "proposals.json").read_text()) if x["status"] == "used"]
        self.assertEqual(len(used), len(self.before) + 3)                                # one consumed grant per variant
        for k in (1, 2, 3):
            self.assertTrue((self.p / "stills" / f"s01.v{k}.png").is_file())
        self.assertTrue((self.p / "stills" / "s01.png").is_file())                       # the original is untouched

    def test_stop_loss_applies_to_every_variant(self):
        batch = self.ws.propose_variants("demo", "image", "s01", 3)
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = round(costlog.spent(self.p) + 2 * batch["items"][0]["price"] + 0.001, 6)
        (self.p / "budget.json").write_text(json.dumps(b))
        done = self.approve_and_run(batch)
        self.assertEqual([i["status"] for i in done["items"]], ["done", "done", "error"])
        self.assertEqual(len(costlog.read_log(self.p)) - len(self.before), 2)

    def test_agent_keys_may_propose_variants_but_never_select(self):
        self.assertTrue(api_docs.agent_allowed("POST", "/api/projects/{name}/variants"))
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/variants/select"))

    def test_bad_counts_and_kinds_are_refused(self):
        for args in (("image", "s01", 1), ("image", "s01", 5), ("image", "s01", True), ("review", "s01", 2)):
            with self.assertRaises(ServiceError):
                self.ws.propose_variants("demo", *args)

    def test_select_version_discards_the_rest_with_cost_and_never_deletes(self):
        self.approve_and_run(self.ws.propose_variants("demo", "image", "s01", 3))
        res = self.ws.select_version("demo", "image", "s01", 2)
        self.assertEqual((res["selected_version"], res["discarded"]), (2, [1, 3]))
        self.assertTrue((self.p / "stills" / "s01.v2.png").is_file())
        recs = self.ws.overview("demo")["discarded"]
        self.assertEqual(sorted(r["original"] for r in recs), ["stills/s01.v1.png", "stills/s01.v3.png"])
        for r in recs:
            self.assertTrue((self.p / r["file"]).is_file())                              # moved, not deleted
        unit = self.ws.spec("demo", "image", "s01")["price"]
        self.assertAlmostEqual(costlog.split(self.p)["discarded"], 2 * unit, places=6)  # their cost is tracked as discarded
        img = next(i for i in self.images()["images"] if i["id"] == "s01")
        self.assertEqual((img["selected_version"], img["out"]), (2, "stills/s01.v2.png"))
        shot = next(s for s in self.ws._read(self.p, "shots.json")["shots"] if s["id"] == "s01")
        self.assertEqual(shot["first_frame"], "stills/s01.v2.png")                       # downstream source follows the selection
        self.ws.restore("demo", recs[0]["file"])                                         # restorable
        with self.assertRaises(ServiceError):
            self.ws.select_version("demo", "image", "s01", 4)

    def test_clip_variants_select_updates_timeline_source(self):
        from aistudio import editor
        batch = self.ws.propose_variants("demo", "clip", "s01", 2)
        self.assertEqual(batch["total"], round(2 * batch["items"][0]["price"], 6))
        self.approve_and_run(batch)
        files = sorted(f.name for f in (self.p / "clips").glob("s01.v*.mp4"))
        self.assertEqual(files, ["s01.v1_final_a1.mp4", "s01.v2_final_a1.mp4"])
        self.assertEqual(sorted(r["shot"] for r in costlog.read_log(self.p) if r["stage"] == "final"), ["s01.v1", "s01.v2"])
        res = self.ws.select_version("demo", "clip", "s01", 1)
        shot = next(s for s in self.ws._read(self.p, "shots.json")["shots"] if s["id"] == "s01")
        self.assertEqual((shot["selected_version"], shot["final_clip"]), (1, "clips/s01.v1_final_a1.mp4"))
        self.assertEqual(editor.clip_for_shot(self.p, shot), "clips/s01.v1_final_a1.mp4")
        self.assertEqual(res["discarded"], [2])
        self.assertGreater(costlog.split(self.p)["discarded"], 0)
        self.assertTrue(self.ws.approve_shot("demo", "s01")["final_ok"])


class DriftTests(CastBase):
    def setUp(self):
        super().setUp()
        for t in ("meena", "main_place", "s01"):
            self.run_image(t)

    def fake_review(self, score):
        from aistudio.roles import RoleRunner
        text = json.dumps({"scores": {"meena": score, "ghost": 0.1}, "summary": "checked"})
        return patch.object(RoleRunner, "review", autospec=True, return_value={"text": text, "model": "fake/vision", "provider": "fake", "cost": 0.001, "cost_source": "fake"})

    def test_parser_keeps_only_known_characters_and_never_invents_scores(self):
        from aistudio import character_check as cc
        self.assertEqual(cc.parse_drift('x {"scores": {"a": 1.4, "b": "hi", "z": 0.2}}', ["a", "b"])["scores"], {"a": 1.0})
        self.assertEqual(cc.parse_drift("no json", ["a"])["scores"], {})

    def test_check_is_a_proposal_only_and_the_paid_call_needs_approval(self):
        rows = costlog.read_log(self.p)
        prop = self.ws.drift_check("demo", "s01")
        self.assertEqual((prop["kind"], prop["status"], prop["options"]), ("review", "pending", {"review_type": "drift"}))
        self.assertGreater(prop["price"], 0)
        with self.fake_review(0.9) as review:
            with self.assertRaises(ServiceError):
                self.ws.execute("demo", prop["id"])
            self.assertEqual(review.call_count, 0)
        self.assertEqual(costlog.read_log(self.p), rows)
        self.assertFalse((self.p / "checks" / "s01.json").exists())

    def test_approved_check_stores_scores_and_verification_flags_low_ones(self):
        prop = self.ws.drift_check("demo", "s01")
        self.ws.approve_human("demo", prop["id"])
        with self.fake_review(0.35):
            res = self.ws.execute("demo", prop["id"])
        self.assertEqual(res["review"]["scores"], {"meena": 0.35})
        saved = json.loads((self.p / "checks" / "s01.json").read_text())
        self.assertEqual((saved["scores"], saved["threshold"]), ({"meena": 0.35}, 0.6))
        self.assertEqual(costlog.read_log(self.p)[-1]["stage"], "vision")
        with patch("aistudio.roles.RoleRunner.review", side_effect=AssertionError("no paid call from verification")):
            findings = self.ws.verify_status("demo")["shots"]["findings"]
        self.assertIn("identity drift", next(x for x in findings if x["where"] == "s01")["issue"])
        saved["scores"] = {"meena": 0.9}
        (self.p / "checks" / "s01.json").write_text(json.dumps(saved))
        self.assertFalse([x for x in self.ws.verify_status("demo")["shots"]["findings"] if "identity drift" in x["issue"]])

    def test_needs_a_character_reference(self):
        with self.assertRaises(ServiceError):
            self.ws.drift_check("demo", "main_place")
        self.assertTrue(api_docs.agent_allowed("POST", "/api/projects/{name}/drift-check"))


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


class TestReviewNotesFixed(unittest.TestCase):
    def test_edit_of_a_real_person_asset_needs_consent(self):
        from tests.test_spec import make
        ws, p = make(self)
        (p / "stills").mkdir(exist_ok=True)
        (p / "stills" / "maya.png").write_bytes(b"x")
        doc = ws._read(p, "images.json", {"images": []})
        doc.setdefault("images", []).append({"id": "maya", "kind": "character", "out": "stills/maya.png", "prompt": "p", "refs": [], "aspect_ratio": "3:2", "real_person": True})
        ws.put_images("demo", doc)
        with self.assertRaises(Exception) as cm:
            ws._pipeline._payload_and_price("demo", "image_edit", "maya", {"source": "stills/maya.png", "prompt": "swap"})
        self.assertIn("consent", str(cm.exception).lower())
