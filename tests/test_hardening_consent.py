import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import tests._hermetic as HERM
from aistudio import consent, costlog, project as project_mod, tools
from aistudio.domain.common import ServiceError, _sha
from aistudio.recipes import RecipeError
from aistudio.service import Workspace
from tests.test_story_convert import MD


class TestHardeningConsent(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root)
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        (self.p / "stills").mkdir(parents=True, exist_ok=True)
        (self.p / "clips").mkdir(parents=True, exist_ok=True)
        self.ws.estimate("demo", 0.5)
        self.ws.approve_budget("demo")

    def test_put_images_cannot_clear_or_set_real_person_or_consent(self):
        # 1. Human marks hero as real person
        hero_file = self.p / "stills" / "hero.png"
        hero_file.write_bytes(b"HERO-PNG-DATA")
        sha = hashlib.sha256(b"HERO-PNG-DATA").hexdigest()
        
        doc = {
            "style": "",
            "images": [
                {"id": "hero", "kind": "character", "out": "stills/hero.png", "prompt": "a hero", "real_person": True, "subject": "Maya", "refs": []}
            ]
        }
        project_mod.save_json(self.p, "images.json", doc)
        consent.mark_real_person(self.p, "hero", sha, "Maya")

        # An agent calls update_images (ws.put_images) attempting to clear real_person
        agent_doc = {
            "style": "",
            "images": [
                {"id": "hero", "kind": "character", "out": "stills/hero.png", "prompt": "a modified hero", "refs": []},
                {"id": "car", "kind": "other", "out": "stills/car.png", "prompt": "a car", "real_person": True, "subject": "CarPerson", "refs": []}
            ]
        }
        self.ws.put_images("demo", agent_doc, is_agent=True)

        updated = self.ws._read(self.p, "images.json")
        hero = next(i for i in updated["images"] if i["id"] == "hero")
        car = next(i for i in updated["images"] if i["id"] == "car")

        # hero must STILL have real_person: True and subject: Maya
        self.assertTrue(hero.get("real_person"))
        self.assertEqual(hero.get("subject"), "Maya")
        # car must NOT have real_person set by the agent
        self.assertFalse(car.get("real_person"))
        self.assertNotIn("subject", car)

    def test_extend_sha_bound_consent_to_videos_and_driving_clips(self):
        driver = self.p / "clips" / "driver.mp4"
        driver.write_bytes(b"DRIVER-VIDEO-BYTES")
        sha = hashlib.sha256(b"DRIVER-VIDEO-BYTES").hexdigest()

        # Mark the driving clip
        self.ws.consent_mark("demo", "clips/driver.mp4")
        self.assertIn(sha, consent.real_person_shas(self.p))

        # Using driver as reference in motion_transfer requires sha-bound consent
        src = self.p / "clips" / "s01_final_a1.mp4"
        src.write_bytes(b"SRC-VIDEO-BYTES")
        opts = {"source": "clips/s01_final_a1.mp4", "reference": "clips/driver.mp4", "subject": "Dancer", "seconds": 3}

        # Name-only consent is not enough for sha-marked file
        consent.record(self.p, "Dancer", "I consent")
        with self.assertRaises(ServiceError) as cm:
            self.ws.propose("demo", "motion_transfer", "s01_final_a1", options=opts)
        self.assertIn("consent", str(cm.exception).lower())

        # Sha-bound consent satisfies it
        consent.record(self.p, "Dancer", "I consent", sha=sha)
        prop = self.ws.propose("demo", "motion_transfer", "s01_final_a1", options=opts)
        self.assertTrue(prop["id"])

    def test_derived_versions_inherit_mark_through_meta_source_sha(self):
        src = self.p / "stills" / "portrait.png"
        src.write_bytes(b"PORTRAIT-ORIGINAL")
        sha = hashlib.sha256(b"PORTRAIT-ORIGINAL").hexdigest()
        consent.mark_real_person(self.p, "portrait", sha, "Subject")

        # Create a derived local crop
        dst = self.p / "stills" / "portrait_crop.png"
        tools.run_local("reframe_local", src, dst, {"aspect": "1:1", "mode": "crop"}, self.p,
                        runner=lambda argv, **kw: Path(argv[-1]).write_bytes(b"CROPPED-BYTES"))
        derived = self.p / "stills" / "portrait_crop.v1.png"
        self.assertTrue(derived.is_file())
        derived_sha = hashlib.sha256(b"CROPPED-BYTES").hexdigest()

        # Derived file must inherit the real_person mark
        self.assertIn(derived_sha, consent.real_person_shas(self.p))

        # Without consent for the original or derived sha, require_shas fails
        with self.assertRaises(ServiceError):
            consent.require_shas(self.p, [derived_sha])

        # Recording consent for the original source sha also covers the derived version
        consent.record(self.p, "Subject", "I consent", sha=sha)
        # Now require_shas must pass
        consent.require_shas(self.p, [derived_sha])

    def test_consent_checked_for_references_of_ordinary_clip_generation(self):
        ref_file = self.p / "stills" / "actor.png"
        ref_file.write_bytes(b"ACTOR-BYTES")
        sha = hashlib.sha256(b"ACTOR-BYTES").hexdigest()
        consent.mark_real_person(self.p, "actor", sha, "Actor")

        shots_doc = {
            "aspect_ratio": "16:9",
            "shots": [
                {"id": "s01", "prompt": "a scene with actor", "seconds": 3, "refs": [{"id": "actor"}]}
            ]
        }
        images_doc = {
            "style": "",
            "images": [
                {"id": "actor", "kind": "character", "out": "stills/actor.png", "prompt": "actor photo", "refs": []}
            ]
        }
        project_mod.save_json(self.p, "shots.json", shots_doc)
        project_mod.save_json(self.p, "images.json", images_doc)

        # Propose ordinary clip with shot s01: must fail because referenced still actor.png is marked
        with self.assertRaises(ServiceError) as cm:
            self.ws.propose("demo", "clip", "s01")
        self.assertIn("consent", str(cm.exception).lower())

        # Once sha-bound consent is recorded, it succeeds
        consent.record(self.p, "Actor", "I consent", sha=sha)
        prop = self.ws.propose("demo", "clip", "s01")
        self.assertTrue(prop["id"])

    def test_voice_consent_enforced_for_voice_clone(self):
        opts = {"text": "Hello world", "voice_id": "v-custom", "cloned": True, "voice_subject": "Singer"}
        # Propose without consent -> fails
        with self.assertRaises(ServiceError):
            self.ws.propose("demo", "tts", "s01", options=opts)

        # Real person consent (wrong kind) -> still fails
        consent.record(self.p, "Singer", "I consent", kind="real_person")
        with self.assertRaises(ServiceError):
            self.ws.propose("demo", "tts", "s01", options=opts)

        # Voice consent -> succeeds
        consent.record(self.p, "Singer", "I consent to voice clone", kind="voice")
        prop = self.ws.propose("demo", "tts", "s01", options=opts)
        self.assertTrue(prop["id"])

    def test_recipes_look_up_consent_by_input_file_sha(self):
        from aistudio import recipes
        photo = self.p / "stills" / "target.png"
        photo.write_bytes(b"TARGET-PHOTO-DATA")
        sha = hashlib.sha256(b"TARGET-PHOTO-DATA").hexdigest()
        consent.mark_real_person(self.p, "target", sha, "Model")

        # Planning recipe with this photo without consent fails
        rec_id = "photo-to-cinematic-clip"
        inputs = {"photo": "stills/target.png", "camera": "slow-push-in"}
        with self.assertRaises((ServiceError, RecipeError)) as cm:
            recipes.plan(self.ws, "demo", rec_id, inputs)
        self.assertIn("consent", str(cm.exception).lower())

        # With sha-bound consent it succeeds
        consent.record(self.p, "Model", "I consent to likeness", sha=sha)
        res = recipes.plan(self.ws, "demo", rec_id, inputs)
        self.assertTrue(res["id"])


if __name__ == "__main__":
    unittest.main()
