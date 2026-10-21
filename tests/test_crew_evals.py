import json
import tempfile
import unittest
from pathlib import Path

from aistudio.crew import evals
from aistudio.domain.common import ServiceError
from aistudio.service import Workspace


def act(tool, **args):
    return json.dumps({"tool": tool, "args": args, "why": "test"})


DONE = json.dumps({"done": True, "summary": "done"})


class Script:
    def __init__(self, replies, cost=0.0):
        self.replies, self.cost, self.seen = list(replies), cost, []

    def __call__(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        text = self.replies.pop(0) if self.replies else DONE
        return {"text": text, "cost": self.cost, "usage": {"input": 10, "output": 5}, "model": "fake/script"}


class CrewEvalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(self.tmp.name)

    def test_load_all_starter_cases(self):
        cases = evals.load_cases()
        self.assertGreaterEqual(len(cases), 5)
        case_ids = {c["id"] for c in cases}
        self.assertIn("tamil-tea-reel", case_ids)
        self.assertIn("english-coffee-reel", case_ids)
        self.assertIn("product-launch-ad", case_ids)
        self.assertIn("fintech-explainer", case_ids)
        self.assertIn("tamil-handicrafts-ad", case_ids)

    def test_evaluate_project_all_pass(self):
        case = evals.get_case("tamil-tea-reel")
        self.ws.create_project("demo-pass")
        p = self.ws.pdir("demo-pass")
        # Populate valid shots
        shots_doc = {
            "aspect_ratio": "9:16",
            "language": "Tamil",
            "shots": [
                {"id": "s01", "seconds": 4, "model": "fake/video", "voice_line": "காலை விடியலில் நீலகிரி தேநீர் மணம் வீசுகிறது."},
                {"id": "s02", "seconds": 5, "model": "veo-3.1-lite", "voice_line": "பாரம்பரிய பித்தளை டவராவில் சுடச்சுட தேநீர்."},
                {"id": "s03", "seconds": 6, "model": "veo-3.1", "voice_line": "இன்றே சுவைத்து மகிழுங்கள்!"},
            ],
        }
        (p / "shots.json").write_text(json.dumps(shots_doc), encoding="utf-8")
        run_rec = {
            "steps": [{"n": 1, "tool": "read_doc", "status": "ok"}],
            "proposals": [{"id": "p1", "price": 0.15}],
            "llm_usd": 0.02,
        }
        res = evals.evaluate_project(self.ws, "demo-pass", case, run_rec)
        self.assertTrue(res["passed"])
        self.assertEqual(res["score"], 1.0)
        self.assertTrue(res["checks"]["shot_count"]["ok"])
        self.assertTrue(res["checks"]["format"]["ok"])
        self.assertTrue(res["checks"]["language_script"]["ok"])
        self.assertTrue(res["checks"]["model_validity"]["ok"])
        self.assertTrue(res["checks"]["schema_validity"]["ok"])
        self.assertTrue(res["checks"]["proposals_only"]["ok"])
        self.assertTrue(res["checks"]["budget_cap"]["ok"])

    def test_harness_catches_bad_run_missing_shots(self):
        case = evals.get_case("tamil-tea-reel")
        self.ws.create_project("demo-missing")
        p = self.ws.pdir("demo-missing")
        # Only 1 shot when min_shots is 3
        shots_doc = {
            "aspect_ratio": "9:16",
            "shots": [
                {"id": "s01", "seconds": 4, "model": "fake/video", "voice_line": "காலை விடியல்"},
            ],
        }
        (p / "shots.json").write_text(json.dumps(shots_doc), encoding="utf-8")
        run_rec = {"steps": [], "proposals": []}
        res = evals.evaluate_project(self.ws, "demo-missing", case, run_rec)
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["shot_count"]["ok"])
        self.assertIn("Expected 3..6 shots, found 1", res["checks"]["shot_count"]["detail"])

    def test_harness_catches_bad_run_forbidden_tool_attempt(self):
        case = evals.get_case("english-coffee-reel")
        self.ws.create_project("demo-forbidden")
        p = self.ws.pdir("demo-forbidden")
        shots_doc = {
            "aspect_ratio": "9:16",
            "shots": [
                {"id": "s01", "seconds": 4, "model": "fake/video", "voice_line": "Wake up to cold brew."},
                {"id": "s02", "seconds": 4, "model": "fake/video", "voice_line": "Rich nitro pour over ice."},
                {"id": "s03", "seconds": 4, "model": "fake/video", "voice_line": "Fuel your creativity all day."},
            ],
        }
        (p / "shots.json").write_text(json.dumps(shots_doc), encoding="utf-8")
        # Run record shows agent attempted approve_budget
        run_rec = {
            "steps": [
                {"n": 1, "tool": "approve_budget", "status": "refused"},
                {"n": 2, "tool": "done", "status": "done"},
            ],
            "proposals": [],
        }
        res = evals.evaluate_project(self.ws, "demo-forbidden", case, run_rec)
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["proposals_only"]["ok"])
        self.assertIn("Forbidden tool attempted: approve_budget", res["checks"]["proposals_only"]["detail"])

    def test_harness_catches_bad_run_script_mismatch(self):
        case = evals.get_case("tamil-tea-reel")
        self.ws.create_project("demo-script")
        p = self.ws.pdir("demo-script")
        # Tamil case, but voice lines are English (Latin script)
        shots_doc = {
            "aspect_ratio": "9:16",
            "shots": [
                {"id": "s01", "seconds": 4, "model": "fake/video", "voice_line": "Fresh morning tea in the mountains."},
                {"id": "s02", "seconds": 4, "model": "fake/video", "voice_line": "Brewed with authentic spices."},
                {"id": "s03", "seconds": 4, "model": "fake/video", "voice_line": "Taste the tradition today."},
            ],
        }
        (p / "shots.json").write_text(json.dumps(shots_doc), encoding="utf-8")
        res = evals.evaluate_project(self.ws, "demo-script", case, {"steps": [], "proposals": []})
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["language_script"]["ok"])
        self.assertIn("Tamil script ratio too low", res["checks"]["language_script"]["detail"])

    def test_paid_chat_model_refuses_without_allow_paid(self):
        case = evals.get_case("english-coffee-reel")
        with self.assertRaises(ServiceError) as ctx:
            evals.run_eval_case(self.ws, case, model="gpt-4o", allow_paid=False)
        self.assertIn("paid model", str(ctx.exception))
        self.assertIn("Pass --allow-paid", str(ctx.exception))
        self.assertIn("Max LLM spend", str(ctx.exception))

    def test_run_eval_full_flow_saves_report(self):
        case = evals.get_case("english-coffee-reel")
        # Scripted LLM simulating writer & director steps
        llm = Script([
            DONE,  # producer
            DONE,  # writer
            DONE,  # director
        ])
        report = evals.run_eval(self.ws, cases=[case], allow_paid=True, llm=llm)
        self.assertEqual(report["summary"]["total_cases"], 1)
        self.assertTrue(Path(report["report_path"]).is_file())
        saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["model"], "default")

        # Table formatting
        table = evals.format_table(report)
        self.assertIn("Crew Evaluation Report", table)
        self.assertIn("english-coffee-reel", table)

    def test_catalog_model_validity(self):
        cat = self.ws.catalog()
        self.assertTrue(evals.is_valid_catalog_model(cat, "veo-3.1"))
        self.assertTrue(evals.is_valid_catalog_model(cat, "veo-3.1-lite"))
        self.assertTrue(evals.is_valid_catalog_model(cat, "fake/video"))
        self.assertFalse(evals.is_valid_catalog_model(cat, "unknown-video-999"))
        self.assertFalse(evals.is_valid_catalog_model(cat, None))

    def test_estimate_max_llm_spend(self):
        cases = evals.load_cases()
        spend = evals.estimate_max_llm_spend(self.ws, cases)
        self.assertGreater(spend, 0.0)

    def test_budget_cap_exceeded(self):
        case = evals.get_case("english-coffee-reel")
        self.ws.create_project("demo-cap")
        p = self.ws.pdir("demo-cap")
        shots_doc = {
            "aspect_ratio": "9:16",
            "shots": [
                {"id": "s01", "seconds": 4, "model": "fake/video", "voice_line": "Wake up."},
                {"id": "s02", "seconds": 4, "model": "fake/video", "voice_line": "Cold brew."},
                {"id": "s03", "seconds": 4, "model": "fake/video", "voice_line": "Ready."},
            ],
        }
        (p / "shots.json").write_text(json.dumps(shots_doc), encoding="utf-8")
        # Proposals total $1.50 which exceeds 0.50 cap
        run_rec = {
            "steps": [],
            "proposals": [{"id": "p1", "price": 0.80}, {"id": "p2", "price": 0.70}],
        }
        res = evals.evaluate_project(self.ws, "demo-cap", case, run_rec)
        self.assertFalse(res["passed"])
        self.assertFalse(res["checks"]["budget_cap"]["ok"])
        self.assertIn("exceeds cap", res["checks"]["budget_cap"]["detail"])


if __name__ == "__main__":
    unittest.main()
