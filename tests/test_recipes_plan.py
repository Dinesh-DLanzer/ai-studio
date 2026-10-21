import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistudio import costlog, recipes, tools as tools_mod
from aistudio.domain.common import ServiceError
from aistudio.service import Workspace

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082")


class Base(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Workspace(tmp.name)
        self.ws.create_project("demo", test_pipeline=True)
        self.p = self.ws.pdir("demo")
        (self.p / "stills").mkdir(exist_ok=True)
        (self.p / "stills" / "product.png").write_bytes(PNG)

    def approve_everything_human(self, batch):
        """What the human does: estimate + approve the budget, then approve the batch at its hash."""
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = 100
        (self.p / "budget.json").write_text(json.dumps(b))
        return self.ws.batches.approve("demo", batch["id"], batch["batch_hash"])


class PlanTests(Base):
    def test_every_runnable_starter_plans_to_a_batch_whose_total_is_the_sum_of_its_items(self):
        inputs = {"product-placement": {"product": "stills/product.png", "setting": "studio"},
                  "product-showcase-360": {"product": "stills/product.png", "setting": "studio"},
                  "product-ad-9x16": {"product": "stills/product.png", "setting": "kitchen", "headline": "Fresh"},
                  "photo-to-cinematic-clip": {"photo": "stills/product.png", "camera": "360-orbit", "motion": "slow"},
                  "explainer-from-script": {"scene1": "Hello there.", "scene2": "Second.", "style": "flat illustration"}}
        self.ws.create_project("wide", test_pipeline=True)      # a 16:9 recipe cannot share a project with 9:16 shots
        for rid, given in inputs.items():
            batch = recipes.plan(self.ws, "wide" if rid == "explainer-from-script" else "demo", rid, given)
            self.assertEqual(batch["status"], "awaiting_approval", rid)
            self.assertEqual(batch["total"], round(sum(i["price"] for i in batch["items"]), 6), rid)
            self.assertGreater(batch["total"], 0, rid)
            self.assertTrue(all(i["request_hash"] and i["model"] for i in batch["items"]), rid)
        self.assertEqual(costlog.read_log(self.p), [])      # planning is free: no cost-log row
        self.assertEqual(list((self.p / "clips").glob("*")) if (self.p / "clips").exists() else [], [])

    def test_unavailable_recipes_are_flagged_with_the_reason_and_refused(self):
        rows = {r["id"]: r for r in recipes.list_recipes(self.ws, "demo")}
        for rid in ("talking-head-ad", "outfit-swap", "headshot", "face-swap"):
            self.assertFalse(rows[rid]["available"], rid)
            self.assertTrue(rows[rid]["reasons"], rid)
            with self.assertRaises(ServiceError) as c:
                recipes.plan(self.ws, "demo", rid, {})
            self.assertIn("cannot run here", str(c.exception))
        self.assertTrue(rows["product-ad-9x16"]["available"])
        self.assertEqual([s["step"] for s in rows["product-ad-9x16"]["skipped"]], ["music"])      # no music model exists: skipped, not guessed
        self.assertNotIn("talking-head-ad", [r["id"] for r in recipes.list_recipes(self.ws, "demo", only_available=True)])

    def test_missing_model_makes_a_recipe_unavailable(self):
        with patch.object(recipes, "task_available", side_effect=lambda ws, p, t: (False, "no model") if t == "image_to_video" else (True, "")):
            a = recipes.availability(self.ws, recipes.get("product-showcase-360"))
        self.assertFalse(a["available"])
        self.assertIn("image_to_video", a["reasons"][0])

    def test_optional_step_and_when_are_left_out_with_a_note(self):
        batch = recipes.plan(self.ws, "demo", "explainer-from-script", {"scene1": "One.", "style": "clean 3D"})
        steps = [i["recipe"]["step"] for i in batch["items"]]
        self.assertEqual(steps, ["still1", "clip1", "edit"])
        self.assertEqual({n["step"] for n in batch["recipe"]["skipped"]}, {"still2", "clip2", "still3", "clip3", "voice"})

    def test_bad_inputs_are_refused(self):
        good = {"product": "stills/product.png", "setting": "studio"}
        for bad in ({**good, "product": "../etc/passwd"}, {**good, "product": "/etc/passwd"}, {**good, "product": "stills/none.png"},
                    {**good, "product": "stills"}, {**good, "setting": "moon"}, {**good, "extra": "x"}, {"setting": "studio"}):
            with self.assertRaises(ServiceError, msg=str(bad)):
                recipes.plan(self.ws, "demo", "product-placement", bad)
        with self.assertRaises(ServiceError):
            recipes.plan(self.ws, "demo", "product-ad-9x16", {**good, "headline": "x" * 41})
        with self.assertRaises(ServiceError):
            recipes.plan(self.ws, "demo", "product-ad-9x16", {**good, "headline": "bad\x00char"})
        self.assertEqual(list((self.p / "batches").glob("*.json")) if (self.p / "batches").exists() else [], [])

    def test_placeholder_injection_is_inert(self):
        for text in ("{setting}", "{nope}", "${product}", "{hero}", "../../x", "{{x}}"):
            b = recipes.plan(self.ws, "demo", "product-ad-9x16", {"product": "stills/product.png", "setting": "studio", "headline": text})
            self.assertIn(text, " ".join(t["text"] for e in b["items"] if e["kind"] == "assemble" for t in e["recipe"]["text"]))
        self.assertEqual(recipes._fill("a {x} b", {"x": "{y}", "y": "BOOM"}), "a {y} b")      # a value is never re-expanded

    def test_failed_plan_leaves_the_project_documents_untouched(self):
        before = ((self.p / "shots.json").read_bytes(), (self.p / "images.json").read_bytes())
        with patch.object(recipes, "_price", side_effect=ServiceError("no price")):
            with self.assertRaises(ServiceError):
                recipes.plan(self.ws, "demo", "product-showcase-360", {"product": "stills/product.png", "setting": "studio"})
        self.assertEqual(before, ((self.p / "shots.json").read_bytes(), (self.p / "images.json").read_bytes()))


class RunTests(Base):
    def planned(self, rid="product-ad-9x16", **given):
        given = {"product": "stills/product.png", "setting": "studio", "headline": "Fresh", **given}
        return recipes.plan(self.ws, "demo", rid, given)

    def test_nothing_runs_before_approval(self):
        b = self.planned()
        with self.assertRaises(ServiceError):
            self.ws.batches.run("demo", b["id"])
        self.assertEqual(costlog.read_log(self.p), [])
        self.assertFalse((self.p / "edit.json").exists())

    def test_approved_recipe_runs_end_to_end_and_charges_exactly_the_total(self):
        b = self.approve_everything_human(self.planned())
        done = self.ws.batches.run("demo", b["id"])
        self.assertEqual(done["status"], "done", [(i["recipe"]["step"], i["status"], i.get("error")) for i in done["items"]])
        rows = costlog.read_log(self.p)
        self.assertEqual(len(rows), 2)      # hero edit + orbit clip; assemble is free
        self.assertAlmostEqual(sum(float(r["cost"]) for r in rows), done["total"], places=6)
        edit = json.loads((self.p / "edit.json").read_text())
        self.assertEqual(len(edit["tracks"]["video"]), 1)
        self.assertEqual(edit["tracks"]["text"][0]["text"], "Fresh")
        self.assertTrue(all((self.p / i["file"]).is_file() for i in done["items"]))

    def test_changed_input_after_approval_stops_the_run(self):
        b = self.approve_everything_human(self.planned())
        (self.p / "stills" / "product.png").write_bytes(PNG + b"\x00")
        res = self.ws.batches.run("demo", b["id"])
        self.assertEqual(res["status"], "needs_reapproval")
        self.assertIn("request changed", res["items"][0]["changes"])
        self.assertEqual(costlog.read_log(self.p), [])

    def test_changed_spec_after_approval_stops_the_clip_and_keeps_finished_items(self):
        b = self.approve_everything_human(self.planned())
        doc = json.loads((self.p / "shots.json").read_text())
        next(s for s in doc["shots"] if s["id"].endswith("_orbit"))["prompt"] = "something else entirely"
        (self.p / "shots.json").write_text(json.dumps(doc))
        res = self.ws.batches.run("demo", b["id"])
        self.assertEqual(res["status"], "needs_reapproval")
        self.assertEqual([i["status"] for i in res["items"]], ["done", "needs_reapproval", "pending"])
        self.assertEqual(len(costlog.read_log(self.p)), 1)

    def test_tampered_batch_is_refused(self):
        b = self.planned()
        f = self.p / "batches" / f"{b['id']}.json"
        doc = json.loads(f.read_text())
        doc["items"][0]["recipe"]["prompt"] = "x"
        doc["items"][0]["request_hash"] = "0" * 64
        f.write_text(json.dumps(doc))
        with self.assertRaises(ServiceError):
            self.ws.batches.get("demo", b["id"])

    def test_budget_gate_still_applies(self):
        b = self.planned()
        self.ws.batches.approve("demo", b["id"], b["batch_hash"])      # batch approved, project budget is not
        res = self.ws.batches.run("demo", b["id"])
        self.assertEqual(res["status"], "error")
        self.assertIn("budget", res["items"][0]["error"])
        self.assertEqual(costlog.read_log(self.p), [])

    def test_free_reframe_pack_runs_without_spend(self):
        def fake_run(tool, src, dst, params, project_dir, runner=None):
            out = Path(project_dir) / "stills" / f"{Path(dst).stem}.v1.png"
            out.write_bytes(PNG)
            return out
        with patch.object(tools_mod, "available", return_value=["reframe_local"]), patch.object(tools_mod, "run_local", side_effect=fake_run):
            b = recipes.plan(self.ws, "demo", "upscale-and-reframe-pack", {"photo": "stills/product.png"})
            self.assertEqual((b["total"], [i["recipe"]["step"] for i in b["items"]]), (0, ["tall", "square", "wide"]))
            b = self.ws.batches.approve("demo", b["id"], b["batch_hash"])
            done = self.ws.batches.run("demo", b["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(costlog.read_log(self.p), [])


class ConsentTests(Base):
    def flag(self, real=True):
        doc = json.loads((self.p / "images.json").read_text())
        doc["images"].append({"id": "product", "kind": "other", "out": "stills/product.png", "refs": [], "prompt": "x", "real_person": real, "subject": "Asha"})
        (self.p / "images.json").write_text(json.dumps(doc))

    def test_flagged_photo_is_refused_at_plan_without_consent(self):
        self.flag()
        with self.assertRaises(ServiceError) as c:
            recipes.plan(self.ws, "demo", "photo-to-cinematic-clip", {"photo": "stills/product.png", "camera": "360-orbit"})
        self.assertIn("consent", str(c.exception))

    def test_flagged_photo_with_consent_plans_and_revoking_stops_the_run(self):
        self.flag()
        self.ws.consent_record("demo", "Asha", "I agree")
        b = recipes.plan(self.ws, "demo", "photo-to-cinematic-clip", {"photo": "stills/product.png", "camera": "360-orbit"})
        b = self.approve_everything_human(b)
        (self.p / "consent.json").write_text("[]")      # consent withdrawn after approval
        res = self.ws.batches.run("demo", b["id"])
        self.assertEqual(res["status"], "error")
        self.assertIn("consent", res["items"][0]["error"])
        self.assertEqual(costlog.read_log(self.p), [])

    def test_required_policy_needs_a_flagged_asset(self):
        rec = recipes.get("photo-to-cinematic-clip")
        with patch.object(recipes, "get", return_value={**rec, "consent": "required"}):
            with self.assertRaises(ServiceError) as c:
                recipes.plan(self.ws, "demo", "photo-to-cinematic-clip", {"photo": "stills/product.png", "camera": "360-orbit"})
            self.assertIn("real person", str(c.exception))
            self.flag()
            self.ws.consent_record("demo", "Asha", "I agree")
            self.assertEqual(recipes.plan(self.ws, "demo", "photo-to-cinematic-clip", {"photo": "stills/product.png", "camera": "360-orbit"})["status"], "awaiting_approval")

    def test_person_recipes_are_consent_required(self):
        for rid in ("talking-head-ad", "outfit-swap", "headshot", "face-swap"):
            self.assertEqual(recipes.get(rid)["consent"], "required", rid)


if __name__ == "__main__":
    unittest.main()
