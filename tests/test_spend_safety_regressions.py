"""Fake-only regressions for the final approval-enforcement review."""
import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from aistudio import costlog, project_lock
from aistudio.service import ServiceError, Workspace
from tests.test_story_convert import MD


class TestSpendSafetyRegressions(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(self.tmp.name)
        self.ws.create_project("demo", test_pipeline=True)
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        self.ws.estimate("demo")
        self.ws.approve_budget("demo")

    def approved(self, kind="image", target="s01"):
        prop = self.ws.propose("demo", kind, target)
        self.ws.approve_human("demo", prop["id"])
        return prop

    def test_paid_text_calls_are_logged_with_missing_or_zero_usage(self):
        from tests.test_roles import setup, ch, Script
        for role in ("chat", "verify"):
            for model in ("gem", "unknown-model"):
                for usage in ({}, {"input": 0, "output": 0}):
                    with self.subTest(role=role, model=model, usage=usage):
                        runner, _ = setup(chains={role: ch(("g", model))})
                        output = {"text": "ok", "model": model, "cost": None, "usage": usage}
                        with patch.object(self.ws, "runner", return_value=runner), \
                             patch.object(self.ws._verify, "ai_settings", return_value={"settings": {"allow_paid": True, "ai_cap_usd": 10}}), \
                             patch.object(Script, "chat", return_value=output):
                            if model == "unknown-model":
                                with self.assertRaises(ServiceError):
                                    self.ws._ai_call("demo", role, [])
                                continue
                            self.ws._ai_call("demo", role, [])
                        row = costlog.read_log(self.p)[-1]
                        self.assertEqual((row["stage"], row["model"], row["provider"], row["actor"]), (role, model, "g", "local"))
                        self.assertEqual(row["cost_source"], "unknown")
        self.assertEqual(len(costlog.read_log(self.p)), 4)

    def test_concurrent_text_calls_respect_planned_cost_cap(self):
        class Runner:
            calls = 0
            def resolve(self, role, p):
                return [{"problem": None, "card": {"kind": "text", "output_per_1m": 1000.0}}]
            def chat(self, *args, **kwargs):
                self.calls += 1
                return {"text": "ok", "cost": 9.0, "cost_source": "reported", "model": "paid", "provider": "fake"}
        runner = Runner()
        outcomes = []
        def call():
            try:
                outcomes.append(self.ws._ai_call("demo", "verify", []))
            except ServiceError as error:
                outcomes.append(error)
        with patch.object(self.ws, "runner", return_value=runner), \
             patch.object(self.ws._verify, "ai_settings", return_value={"settings": {"allow_paid": True, "ai_cap_usd": 10.0}}):
            threads = [threading.Thread(target=call) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(sum(isinstance(x, ServiceError) for x in outcomes), 1)

    def test_background_verification_only_runs_free_model(self):
        class Runner:
            def __init__(self, card): self.card = card
            def resolve(self, role, p): return [{"problem": None, "card": self.card}]
        for card, should_run in (({"kind": "text", "free": True}, True),
                                 ({"kind": "text", "output_per_1m": 1.0}, False), (None, False)):
            with self.subTest(card=card):
                with patch.object(self.ws, "is_test", return_value=False), \
                     patch.object(self.ws, "runner", return_value=Runner(card)), \
                     patch.object(self.ws._verify, "ai_settings", return_value={"settings": {"auto_verify": True}}), \
                     patch.object(self.ws._verify, "_verify_inputs", return_value=({}, [], "", {}, "hash")), \
                     patch.object(self.ws._verify, "verify_run") as verify_run, \
                     patch("aistudio.domain.verify.time.sleep"):
                    self.ws._verify._verify_bg("demo", "brief")
                    self.assertEqual(verify_run.called, should_run)

    def test_provider_cost_survives_output_save_failure(self):
        prop = self.approved()
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.ws.execute("demo", prop["id"], override=True)
        rows = costlog.read_log(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["result"], rows[0]["actor"], rows[0]["override"]), ("output_failed", "local", "yes"))
        self.assertAlmostEqual(float(rows[0]["cost"]), 0.036)
        self.assertEqual(project_lock.reserved(self.p), 0)

    def test_corrupt_reservations_fail_closed_and_remain_for_recovery(self):
        prop = self.approved()
        reservation_path = self.p / "spend_reservations.json"
        reservation_path.write_text("{broken")
        with patch.object(self.ws.runner(), "image", side_effect=AssertionError("provider called")):
            with self.assertRaises(RuntimeError):
                self.ws.execute("demo", prop["id"])
        self.assertEqual(reservation_path.read_text(), "{broken")

    def test_failed_log_write_keeps_reservation(self):
        prop = self.approved()
        with patch.object(costlog, "append_log", side_effect=OSError("log unavailable")):
            with self.assertRaises(OSError):
                self.ws.execute("demo", prop["id"])
        self.assertAlmostEqual(project_lock.reserved(self.p), prop["price"])

    def test_image_executes_approved_payload_without_rereading_spec(self):
        prop = self.approved()
        original = self.ws.pipeline_domain._execute_kind
        def execute(*args, **kwargs):
            with patch.object(self.ws, "_image_spec", side_effect=AssertionError("mutable spec reread")):
                return original(*args, **kwargs)
        with patch.object(self.ws.pipeline_domain, "_execute_kind", side_effect=execute):
            self.ws.execute("demo", prop["id"])
        self.assertEqual(len(costlog.read_log(self.p)), 1)

    def test_inflight_attempt_counts_toward_attempt_limit(self):
        (self.p / "stills" / "s01.png").write_bytes(b"fake input")
        b = json.loads((self.p / "budget.json").read_text())
        b.update(max_attempts=1, stop_loss=10)
        (self.p / "budget.json").write_text(json.dumps(b))
        first, second = self.approved("clip"), self.approved("clip")
        entered, release = threading.Event(), threading.Event()
        original = self.ws.runner().video
        errors = []
        def slow(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            return original(*args, **kwargs)
        def work():
            try:
                self.ws.execute("demo", first["id"])
            except Exception as error:
                errors.append(error)
        with patch.object(self.ws.runner(), "video", side_effect=slow):
            thread = threading.Thread(target=work)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(ServiceError, "attempts already"):
                    self.ws.execute("demo", second["id"])
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(len(costlog.read_log(self.p)), 1)


class LockOrderAndPendingAudioTests(unittest.TestCase):
    def test_ai_call_never_holds_the_project_lock_across_the_provider_call(self):
        import inspect
        from aistudio.domain import verify
        src = inspect.getsource(verify.VerifyDomain._ai_call)
        i = src.index("runner.chat(")
        self.assertEqual(src[:i].count("with project_lock.lock(p):"), 1)          # the check + reserve block ...
        before_call = src[:i]
        self.assertIn("project_lock.reserve(", before_call)
        # ... has ended (dedented) before the provider call: the call line is indented only inside the inner try
        call_line = [l for l in src.splitlines() if "runner.chat(" in l][0]
        lock_line = [l for l in src.splitlines() if "with project_lock.lock(p):" in l][0]
        self.assertLessEqual(len(lock_line) - len(lock_line.lstrip()), len(call_line) - len(call_line.lstrip()) - 4)

    def test_pending_audio_job_keeps_the_quote_as_its_logged_cost(self):
        import inspect
        from aistudio.domain import pipeline
        src = inspect.getsource(pipeline.PipelineDomain._execute_audio)
        self.assertIn('"result": "pending", "cost_source": "estimated", "cost": price', src)
