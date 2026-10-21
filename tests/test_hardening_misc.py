"""Regression tests for Item 4 hardening fixes:
1. Pending tool-job sync into version files
2. Attempts cap per clip per tool
3. catalog.missing does not skip adapter check when ptype is empty
4. Cap/cleanup abandoned rcp* recipe plans and awaiting-approval batch files
5. select_version under project_lock
6. Orphan sidecars cleaned on discard and restored
7. UTC timestamp consistency
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import _hermetic  # noqa: F401
from aistudio import catalog as catalog_mod, costlog, discard as discard_mod, project_lock
from aistudio.domain import spec as spec_mod
from aistudio.domain.batches import BatchDomain
from aistudio.domain.costs import CostDomain
from aistudio.domain.pipeline import PipelineDomain
from aistudio.providers import config as cfg
from aistudio.service import ServiceError, Workspace
from tests.test_story_convert import MD


class _MockRunner:
    def __init__(self, res):
        self.res = res

    def fetch_video(self, job, req):
        return self.res


class _MockWS:
    def __init__(self, p, res):
        self.p = p
        self._runner = _MockRunner(res)

    def pdir(self, name):
        return self.p

    def runner(self):
        return self._runner


class TestHardeningMisc(unittest.TestCase):
    def setUp(self):
        _hermetic.all_test(self)

    # 1. Pending tool-job sync into version files
    def test_pending_tool_job_sync_into_version_file_and_meta(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "clips").mkdir(parents=True)
            source_clip = p / "clips" / "s01_final_a1.mp4"
            source_clip.write_bytes(b"ORIGINAL-CLIP-DATA")

            # Simulate pending upscale_ai tool job in costlog
            costlog.append_log(p, {
                "shot": "s01_final_a1", "stage": "upscale_ai", "model": "upscale-model",
                "attempt": "1", "job_id": "job-tool-123", "seconds": "4", "resolution": "1080p",
                "cost": "0.12", "result": "pending", "provider": "fake", "cost_source": "estimated"
            })

            res = {"status": "done", "bytes": b"UPSCALED-BYTES", "cost": 0.12, "cost_source": "reported"}
            ws = _MockWS(p, res)
            synced = CostDomain(ws).sync("demo")
            self.assertIn("s01_final_a1", synced["resolved"])

            # Verify that clips/s01_final_a1.v1.mp4 and .meta.json were written (NOT clips/s01_final_a1_final_a1.mp4)
            v1_clip = p / "clips" / "s01_final_a1.v1.mp4"
            self.assertTrue(v1_clip.is_file())
            self.assertEqual(v1_clip.read_bytes(), b"UPSCALED-BYTES")

            meta_file = p / "clips" / "s01_final_a1.v1.mp4.meta.json"
            self.assertTrue(meta_file.is_file())
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "upscale_ai")
            self.assertEqual(meta["target"], "s01_final_a1")
            self.assertEqual(meta["cost"], 0.12)
            self.assertTrue(meta["source_sha"])
            self.assertIn("+00:00", meta["created"])

    # 2. Attempts cap per clip per tool
    def test_attempts_cap_per_clip_per_tool(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.create_project("demo")
            ws.put_text("demo", "Story.md", MD)
            ws.convert_story("demo")
            p = ws.pdir("demo")
            (p / "clips").mkdir(exist_ok=True)
            (p / "clips" / "s01_final_a1.mp4").write_bytes(b"CLIP1")
            (p / "clips" / "s02_final_a1.mp4").write_bytes(b"CLIP2")

            ws.estimate("demo", 0.5)
            ws.approve_budget("demo")
            ws.set_max_attempts("demo", 2)

            # Record 2 attempts for upscale_ai on s01_final_a1
            costlog.append_log(p, {"shot": "s01_final_a1", "stage": "upscale_ai", "attempt": "1", "cost": "0.1", "result": "completed"})
            costlog.append_log(p, {"shot": "s01_final_a1", "stage": "upscale_ai", "attempt": "2", "cost": "0.1", "result": "completed"})

            # Attempt 3 on s01_final_a1 with upscale_ai should be rejected by gate check
            prop = ws.clip_tool("demo", "upscale_ai", "s01_final_a1", seconds=4)
            ws.approve_human("demo", prop["id"])
            with self.assertRaisesRegex(ServiceError, "attempts already"):
                ws.execute("demo", prop["id"])

            # But reframe_ai on s01_final_a1 is allowed (different tool)
            prop_reframe = ws.clip_tool("demo", "reframe_ai", "s01_final_a1", aspect_ratio="1:1", seconds=4)
            ws.approve_human("demo", prop_reframe["id"])
            res_reframe = ws.execute("demo", prop_reframe["id"])
            self.assertTrue(res_reframe["file"].startswith("clips/s01_final_a1.v1"))

            # And upscale_ai on s02_final_a1 is allowed (different clip)
            prop_s02 = ws.clip_tool("demo", "upscale_ai", "s02_final_a1", seconds=4)
            ws.approve_human("demo", prop_s02["id"])
            res_s02 = ws.execute("demo", prop_s02["id"])
            self.assertTrue(res_s02["file"].startswith("clips/s02_final_a1.v1"))

    # 3. catalog.missing must not skip adapter check when ptype is empty
    def test_catalog_missing_fails_closed_when_ptype_is_empty(self):
        # A profile claiming end_frame support
        profile = {
            "tasks": ["text_to_video", "image_to_video"],
            "frames": {"start": True, "end": True, "keyframes": 0},
            "references": {"max": 2, "roles": []},
        }

        # When ptype is empty, missing must NOT skip the adapter check for end_frame
        reason = catalog_mod.missing(profile, "", {"task": "image_to_video", "end_frame": True})
        self.assertIsNotNone(reason)
        self.assertIn("adapter cannot send an end frame", reason)

        # When ptype is empty, missing must NOT skip the adapter check for AI tool tasks
        reason_task = catalog_mod.missing(profile, "", {"task": "upscale"})
        self.assertIsNotNone(reason_task)
        self.assertIn("no upscale support", reason_task)

        profile_with_upscale = {**profile, "tasks": ["upscale"]}
        reason_task2 = catalog_mod.missing(profile_with_upscale, "", {"task": "upscale"})
        self.assertIsNotNone(reason_task2)
        self.assertIn("adapter cannot run upscale", reason_task2)

        # If provider_type is in profile, it resolves it
        profile_with_provider = {**profile, "provider_type": "google"}
        self.assertIsNone(catalog_mod.missing(profile_with_provider, "", {"task": "image_to_video", "end_frame": True}))

    # 4. Cap/cleanup abandoned rcp* recipe plans and awaiting-approval batch files
    def test_batches_cap_and_cleanup_abandoned_recipe_plans(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.create_project("demo")
            p = ws.pdir("demo")
            b_domain = BatchDomain(ws)

            # Create 12 awaiting-approval batches
            batch_ids = []
            for i in range(12):
                plan = {
                    "items": [{"kind": "clip", "target": f"rcp{i:04d}_s1", "model": "fake-model", "price": 0.1, "recipe": {"run": f"{i:04d}"}}],
                    "budget": {"estimate": 1.0, "stop_loss": 2.0, "spent": 0.0}
                }
                # Also simulate unexecuted shots in shots.json
                shots_doc = ws._read(p, "shots.json", {"shots": []})
                shots_doc["shots"].append({"id": f"rcp{i:04d}_s1", "recipe": f"{i:04d}", "model": "", "seconds": 4, "prompt": "test prompt"})
                ws.put_shots("demo", shots_doc)

                b = b_domain.create("demo", plan=plan)
                batch_ids.append(b["id"])

            # Cap is 10 awaiting batches: oldest 2 should be cleaned up
            existing_batches = [f.stem for f in (p / "batches").glob("*.json")]
            self.assertLessEqual(len(existing_batches), 10)
            self.assertNotIn(batch_ids[0], existing_batches)
            self.assertNotIn(batch_ids[1], existing_batches)

            # And their rcp* shots should be cleaned from shots.json
            remaining_shots = {s["id"] for s in ws._read(p, "shots.json")["shots"]}
            self.assertNotIn("rcp0000_s1", remaining_shots)
            self.assertNotIn("rcp0001_s1", remaining_shots)
            self.assertIn("rcp0011_s1", remaining_shots)

    # 5. select_version under project_lock
    def test_select_version_acquires_project_lock(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.create_project("demo")
            p = ws.pdir("demo")
            (p / "stills").mkdir(exist_ok=True)
            (p / "stills" / "shot1.v1.png").write_bytes(b"V1")
            (p / "stills" / "shot1.v2.png").write_bytes(b"V2")
            ws.put_images("demo", {"images": [{"id": "shot1", "kind": "frame", "prompt": "a portrait", "refs": [], "out": "stills/shot1.v1.png"}]})

            locked = []
            orig_lock = project_lock.lock

            def intercepted_lock(pdir):
                locked.append(pdir)
                return orig_lock(pdir)

            with patch("aistudio.domain.pipeline.project_lock.lock", side_effect=intercepted_lock):
                res = ws.select_version("demo", "image", "shot1", 2)
                self.assertEqual(res["selected_version"], 2)
                self.assertTrue(len(locked) > 0)
                self.assertEqual(locked[0], p)

    # 6. Orphan sidecars cleaned on discard and restored
    def test_orphan_sidecars_cleaned_on_discard_and_restored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            clips_dir = p / "clips"
            clips_dir.mkdir(parents=True)

            clip_file = clips_dir / "shot1.mp4"
            clip_file.write_bytes(b"VIDEO")
            meta_file = clips_dir / "shot1.mp4.meta.json"
            meta_file.write_text(json.dumps({"test": "meta"}), encoding="utf-8")

            # Also create an orphaned sidecar (media file does not exist)
            orphan_meta = clips_dir / "abandoned_shot.mp4.meta.json"
            orphan_meta.write_text(json.dumps({"test": "orphan"}), encoding="utf-8")

            # Discard clip
            rec = discard_mod.discard_file(p, "clips/shot1.mp4", "test discard")
            self.assertFalse(clip_file.exists())
            # Both the clip's sidecar and the orphan sidecar should have been moved into _discarded
            self.assertFalse(meta_file.exists())
            self.assertFalse(orphan_meta.exists())

            discarded_meta = clips_dir / "_discarded" / "shot1.mp4.meta.json"
            self.assertTrue(discarded_meta.is_file())
            discarded_orphan = clips_dir / "_discarded" / "abandoned_shot.mp4.meta.json"
            self.assertTrue(discarded_orphan.is_file())

            # Now restore clip
            restored = discard_mod.restore_file(p, rec["file"])
            self.assertTrue(restored.is_file())
            # Sidecar should be restored
            self.assertTrue(meta_file.is_file())

    # 7. UTC timestamp consistency
    def test_utc_timestamp_consistency(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            clips_dir = p / "clips"
            clips_dir.mkdir(parents=True)
            clip_file = clips_dir / "shot1.mp4"
            clip_file.write_bytes(b"VIDEO")

            rec = discard_mod.discard_file(p, "clips/shot1.mp4", "reason")
            # Rec timestamp should include UTC offset (+00:00 or Z)
            self.assertTrue(rec["when"].endswith("+00:00") or rec["when"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
