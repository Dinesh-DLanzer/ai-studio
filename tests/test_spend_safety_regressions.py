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
                            self.ws._ai_call("demo", role, [])
                        row = costlog.read_log(self.p)[-1]
                        self.assertEqual((row["stage"], row["model"], row["provider"], row["actor"]), (role, model, "g", "local"))
                        self.assertEqual(row["cost_source"], "unknown")
        self.assertEqual(len(costlog.read_log(self.p)), 8)

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
