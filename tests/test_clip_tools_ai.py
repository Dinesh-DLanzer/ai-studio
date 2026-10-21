"""Plan 17 stage 2: paid AI clip tools (upscale_ai, reframe_ai, restyle, replace, motion_transfer, character_swap). Fake providers only."""
import tests._hermetic as HERM  # noqa: F401
import json
import tempfile
import unittest
from unittest.mock import patch

from aistudio import consent, costlog, tool_registry
from aistudio.domain.common import _sha
from aistudio.providers.adapters.fake import FakeAdapter
from aistudio.service import ServiceError, Workspace
from tests.test_story_convert import MD

SRC = "clips/s01_final_a1.mp4"
CASES = {
    "upscale_ai": {"scale": 2},
    "reframe_ai": {"aspect_ratio": "1:1"},
    "restyle": {"prompt": "watercolour"},
    "replace": {"prompt": "a red car", "target": "object"},
    "motion_transfer": {"reference": "clips/driver.mp4", "subject": "Asha Rao"},
    "character_swap": {"reference": "stills/newchar.png", "subject": "Asha Rao"},
}


class Base(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        (self.p / "clips").mkdir(exist_ok=True)
        (self.p / SRC).write_bytes(b"FAKEMP4-source")
        (self.p / "clips" / "driver.mp4").write_bytes(b"FAKEMP4-driver")
        (self.p / "stills" / "newchar.png").write_bytes(b"PNG-new")
        HERM.register_test_media(self.p, SRC, "clips/driver.mp4", "stills/newchar.png")
        self.ws.estimate("demo", 0.5)
        self.ws.approve_budget("demo")

    def consent(self, subject="Asha Rao"):
        consent.record(self.p, subject, "I agree", "real_person")

    def propose(self, kind, **over):
        o = {**CASES[kind], **over}
        return self.ws.clip_tool("demo", kind, "s01_final_a1", seconds=4, **o)

    def run_tool(self, kind, **over):
        prop = self.propose(kind, **over)
        self.ws.approve_human("demo", prop["id"])
        return prop, self.ws.execute("demo", prop["id"])


class TestEndToEnd(Base):
    def test_every_kind_proposes_then_executes_into_a_new_version_at_the_quoted_price(self):
        self.consent()
        for n, kind in enumerate(CASES, 1):
            before = costlog.read_log(self.p)
            prop = self.propose(kind)
            self.assertEqual(costlog.read_log(self.p), before)                 # proposing spends nothing
            self.ws.approve_human("demo", prop["id"])
            res = self.ws.execute("demo", prop["id"])
            self.assertEqual(res["file"], f"clips/s01_final_a1.v{n}.mp4")      # a NEW version beside the source, never an overwrite
            self.assertEqual((self.p / SRC).read_bytes(), b"FAKEMP4-source")
            row = costlog.read_log(self.p)[-1]
            self.assertEqual((row["stage"], row["result"], row["provider"], row["cost_source"]), (kind, "completed", "fake", "reported"))
            self.assertEqual(round(float(row["cost"]), 6), prop["price"])      # actual == quote
            self.assertEqual(round(res["cost"], 6), prop["price"])
            meta = json.loads((self.p / (res["file"] + ".meta.json")).read_text())
            self.assertEqual((meta["kind"], meta["actor"], meta["params"]["task"]), (kind, "local", {"upscale_ai": "upscale", "reframe_ai": "reframe", "motion_transfer": "motion_transfer"}.get(kind, "video_to_video")))

    def test_price_is_the_per_second_card_times_the_source_seconds(self):
        self.assertEqual(self.propose("upscale_ai")["price"], 0.12)            # fake card: 0.03 per silent second x 4

    def test_unapproved_and_changed_source_are_refused(self):
        prop = self.propose("upscale_ai")
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])                                # pending, never approved
        self.ws.approve_human("demo", prop["id"])
        (self.p / SRC).write_bytes(b"FAKEMP4-changed")
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])                                # source sha changed: the approval is void
        self.assertEqual(costlog.read_log(self.p), [])

    def test_a_grant_is_single_use(self):
        prop, _ = self.run_tool("upscale_ai")
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])

    def test_bad_parameters_are_refused(self):
        for kind, bad in (("upscale_ai", {"scale": 3}), ("reframe_ai", {"aspect_ratio": "2:1"}), ("restyle", {"prompt": " "}), ("replace", {"target": "sky"})):
            with self.assertRaises(ServiceError, msg=kind):
                self.propose(kind, **bad)
        with self.assertRaises(ServiceError):
            self.ws.clip_tool("demo", "upscale_ai", "nope", seconds=4)
        with self.assertRaises(ServiceError):
            self.ws.clip_tool("demo", "upscale_ai", "s01_final_a1")             # fake clip has no length and no ffprobe answer: never guess a price

    def test_reference_is_bound_by_bytes(self):
        self.consent()
        prop = self.propose("motion_transfer")
        self.ws.approve_human("demo", prop["id"])
        (self.p / "clips" / "driver.mp4").write_bytes(b"FAKEMP4-other")
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])


class TestFailClosed(Base):
    def test_no_adapter_method_means_no_tool(self):
        with patch.object(FakeAdapter, "task_methods", frozenset()):
            with self.assertRaises(ServiceError) as e:
                self.propose("upscale_ai")
        self.assertIn("adapter cannot run upscale", str(e.exception))

    def test_a_model_that_does_not_list_the_task_is_never_used_for_another_task(self):
        # the task list of the (built-in) fake model is the catalog's; remove one task and only that tool disappears
        from aistudio import catalog
        real = catalog.Catalog.profile

        def profile(self_, *a, **k):
            out = real(self_, *a, **k)
            out["tasks"] = [t for t in out["tasks"] if t != "upscale"]
            return out
        with patch.object(catalog.Catalog, "profile", profile):
            with self.assertRaises(ServiceError) as e:
                self.propose("upscale_ai")
            self.assertIn("no upscale support", str(e.exception))
            self.assertTrue(self.propose("restyle")["id"])

    def test_runner_without_a_catalog_refuses(self):
        from aistudio.roles import ChainError
        r = self.ws.runner()
        r.catalog = None
        with self.assertRaises(ChainError):
            r.video_task("upscale", "x.mp4", "", {}, project_dir=self.p)

    def test_runner_refuses_without_a_grant(self):
        from aistudio.roles import GrantRequired
        self.ws.runner().fake_mode = lambda: False
        with self.assertRaises(GrantRequired):
            self.ws.runner().video_task("upscale", "x.mp4", "", {}, project_dir=self.p)


class TestConsent(Base):
    def test_motion_transfer_and_character_swap_always_need_a_subject_with_consent(self):
        for kind in ("motion_transfer", "character_swap"):
            with self.assertRaises(ServiceError):
                self.propose(kind, subject=None)
            with self.assertRaises(ServiceError) as e:
                self.propose(kind)                                              # named, but no consent recorded
            self.assertIn("consent", str(e.exception))
        self.consent()
        self.assertTrue(self.propose("motion_transfer")["id"])

    def test_flagged_source_needs_consent_at_propose_and_execute(self):
        doc = self.ws._read(self.p, "images.json")
        doc["images"][0].update(id="s01_final_a1", real_person=True, subject="Asha Rao")
        self.ws.put_images("demo", doc)
        HERM.register_test_media(self.p, SRC, "clips/driver.mp4", "stills/newchar.png")
        with self.assertRaises(ServiceError):
            self.propose("upscale_ai")
        self.consent()
        prop = self.propose("upscale_ai")
        self.ws.approve_human("demo", prop["id"])
        consent_file = self.p / "consent.json"
        consent_file.write_text("[]")                                           # consent withdrawn between approval and execution
        with self.assertRaises(ServiceError):
            self.ws.execute("demo", prop["id"])

    def test_sha_bound_consent_survives_clearing_the_flag(self):
        doc = self.ws._read(self.p, "images.json")
        doc["images"][0].update(id="s01_final_a1", real_person=True, subject="Asha Rao")
        self.ws.put_images("demo", doc)
        HERM.register_test_media(self.p, SRC, "clips/driver.mp4", "stills/newchar.png")
        sha = _sha(self.p / SRC)
        consent.mark_real_person(self.p, "s01_final_a1", sha)
        doc["images"][0].pop("real_person")                                      # an agent clears the flag
        self.ws.put_images("demo", doc)
        HERM.register_test_media(self.p, SRC, "clips/driver.mp4", "stills/newchar.png")
        self.consent()                                                           # a name-only consent is not enough for marked bytes
        with self.assertRaises(ServiceError) as e:
            self.propose("restyle")
        self.assertIn("bound", str(e.exception))
        consent.record(self.p, "Asha Rao", "I agree", sha=sha)
        self.assertTrue(self.propose("restyle")["id"])

    def test_marking_is_human_session_only(self):
        from server import api_docs
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/consent/mark"))
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/consent"))
        self.assertTrue(api_docs.agent_allowed("POST", "/api/projects/{name}/clips/{shot_id}/tool"))
        self.assertNotIn("consent", " ".join(tool_registry.TOOLS))

    def test_service_binds_consent_to_the_asset_file(self):
        (self.p / "stills" / "s01.png").write_bytes(b"PNG-face")
        self.ws.consent_mark("demo", "s01")
        self.ws.consent_record("demo", "Asha Rao", "I agree", asset_id="s01")
        self.assertEqual(len(consent.real_person_shas(self.p)), 1)
        sha = _sha(self.p / "stills" / "s01.png")
        self.assertEqual(sum(1 for x in consent.read(self.p) if x.get("sha") == sha), 2)


class TestEntryPoints(Base):
    def test_registry_marks_it_paid_and_the_crew_cannot_run_it(self):
        self.assertEqual(tool_registry.cost_class("clip_tool"), "paid")
        from aistudio.crew import runtime
        self.assertIn("clip_tool", tool_registry.crew_tools())                  # offered like edit_still, but the runtime only lets paid tools propose image|clip|review
        from tests.test_crew_runtime import DONE, Script, act
        from aistudio.crew import agents
        from pathlib import Path
        agent = agents.load("echo-writer", dirs=(Path(__file__).parent / "fixtures" / "agents",))
        agent["tools"].append("clip_tool")
        rec = runtime.run(self.ws, "demo", agent, "try the paid clip tool", llm=Script([
            json.dumps({"tool": "clip_tool", "args": {"name": "demo", "tool": "upscale_ai", "clip_id": "s01_final_a1", "scale": 2}}), DONE]))
        self.assertEqual(rec["steps"][0]["status"], "refused")
        self.assertIn("not supported for agents", rec["steps"][0]["result"])

    def test_mcp_tool_only_creates_a_proposal(self):
        from aistudio import mcp_server as M
        r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "clip_tool", "arguments": {
            "name": "demo", "tool": "upscale_ai", "clip_id": "s01_final_a1", "seconds": 4}}}, self.ws)["result"]
        body = json.loads(r["content"][0]["text"])
        self.assertFalse(r["isError"])
        self.assertEqual((body["kind"], body["status"]), ("upscale_ai", "pending"))
        self.assertNotIn("code", body)
        self.assertEqual(costlog.read_log(self.p), [])
        run = M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run_proposal", "arguments": {"name": "demo", "id": body["id"]}}}, self.ws)["result"]
        self.assertTrue(json.loads(run["content"][0]["text"])["approval_needed"])      # a human code is required; the agent gets none
        self.assertEqual(costlog.read_log(self.p), [])


if __name__ == "__main__":
    unittest.main()


class TestBilledSecondsCannotBeUnderstated(unittest.TestCase):
    def setUp(self):
        import shutil
        import subprocess
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg missing")
        from pathlib import Path
        self.p = Path(tempfile.mkdtemp())
        (self.p / "clips").mkdir()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=6", "-pix_fmt", "yuv420p",
                        str(self.p / "clips" / "real.mp4")], check=True)
        (self.p / "clips" / "fake.mp4").write_bytes(b"not real media")

    def test_real_length_is_billed_and_a_smaller_caller_value_is_refused(self):
        from aistudio.domain.spec import clip_seconds
        from aistudio.service import ServiceError
        real = {"ptype": "runway"}
        self.assertEqual(clip_seconds(self.p, {"source": "clips/real.mp4"}, real), 6)
        self.assertEqual(clip_seconds(self.p, {"source": "clips/real.mp4", "seconds": 9}, real), 6)      # the provider bills the clip, not the claim
        with self.assertRaisesRegex(ServiceError, "shorter than the clip"):
            clip_seconds(self.p, {"source": "clips/real.mp4", "seconds": 1}, real)

    def test_unreadable_media_is_refused_for_real_providers_but_fake_keeps_the_callers_number(self):
        from aistudio.domain.spec import clip_seconds
        from aistudio.service import ServiceError
        with self.assertRaisesRegex(ServiceError, "cannot read the clip length"):
            clip_seconds(self.p, {"source": "clips/fake.mp4", "seconds": 1}, {"ptype": "runway"})
        self.assertEqual(clip_seconds(self.p, {"source": "clips/fake.mp4", "seconds": 4}, {"ptype": "fake"}), 4)
