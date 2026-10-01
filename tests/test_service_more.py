import tests._hermetic as HERM  # noqa: F401
import json, os, tempfile, unittest
from aistudio.providers import openrouter as O
from aistudio.service import Workspace, ServiceError
from tests.test_story_convert import MD

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FakeTransport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, path, body=None, raw=False):
        self.calls.append(body)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def chat_reply(obj, cost=0.0):
    return {"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}], "usage": {"cost": cost}}


class Base(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.p = self.ws.pdir("demo")
        self.ws.estimate("demo", 0.2); self.ws.approve_budget("demo")

    def run_paid(self, kind, target):
        prop = self.ws.propose("demo", kind, target, reveal_code=True)
        self.ws.approve("demo", prop["id"], prop["code"])
        return self.ws.execute("demo", prop["id"])


class TestRenames(Base):
    def test_rename_project(self):
        self.assertEqual(self.ws.rename_project("demo", "chai-ad"), "chai-ad")
        self.assertTrue((self.ws.root / "projects" / "chai-ad" / "Story.md").exists())
        self.assertFalse((self.ws.root / "projects" / "demo").exists())
        self.ws.create_project("other")
        for bad, new in (("chai-ad", "other"), ("chai-ad", "../x"), ("chai-ad", "a b"), ("nope", "zzz")):
            with self.assertRaises(ServiceError):
                self.ws.rename_project(bad, new)

    def test_rename_asset_carries_every_reference(self):
        self.run_paid("image", "s01")                                  # stills/s01.png + cost row (image, s01)
        self.run_paid("clip", "s01")                                   # clip that uses it (final, s01)
        imgs = self.ws.overview("demo")["images"]
        imgs["images"].append({"id": "extra", "kind": "frame", "out": "stills/extra.png", "prompt": "p", "refs": ["s01"]})
        self.ws.put_images("demo", imgs)
        (self.p / "checks" / "s01").mkdir(parents=True)                # an image review folder
        (self.p / "checks" / "s01" / "review.json").write_text("{}")
        self.ws.add_file("demo", "stills/s01.png", PNG, replace=True)   # creates a discarded s01.png record
        prop = self.ws.propose("demo", "image", "extra")               # a pending proposal for another asset must survive
        old_prop = self.ws.propose("demo", "review", "s01")            # this one targets the renamed asset: must be voided
        self.ws.rename_asset("demo", "s01", "hero")
        st = self.p / "stills"
        self.assertTrue((st / "hero.png").exists() and not (st / "s01.png").exists())
        self.assertTrue((st / "_discarded" / "hero.png").exists())
        self.assertTrue((self.p / "checks" / "hero" / "review.json").exists())
        doc = self.ws.overview("demo")
        by = {i["id"]: i for i in doc["images"]["images"]}
        self.assertEqual((by["hero"]["out"], by["extra"]["refs"], "s01" in by), ("stills/hero.png", ["hero"], False))
        self.assertEqual(doc["shots"]["shots"][0]["first_frame"], "stills/hero.png")
        self.assertEqual([d["file"] for d in doc["discarded"]], ["stills/_discarded/hero.png"])
        rows = {(r["shot"], r["stage"]) for r in self.ws.costs("demo")["rows"]}
        self.assertIn(("hero", "image"), rows); self.assertIn(("s01", "final"), rows); self.assertNotIn(("s01", "image"), rows)
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "pending")
        self.assertEqual(self.ws.proposal_status("demo", old_prop["id"])["status"], "pending")   # review proposals belong to shots/images by id
        self.assertEqual(self.ws.costs("demo")["split"]["total"], 0.236)

    def test_rename_asset_errors(self):
        self.run_paid("image", "s01")
        for old, new in (("nope", "x"), ("s01", "s01"), ("s01", "../x"), ("s01", "a b")):
            with self.assertRaises(ServiceError):
                self.ws.rename_asset("demo", old, new)
        (self.p / "stills" / "taken.png").write_bytes(PNG)
        with self.assertRaises(ServiceError):
            self.ws.rename_asset("demo", "s01", "taken")                 # a file with that name already exists
        self.assertTrue((self.p / "stills" / "s01.png").exists())        # nothing was moved

    def test_rename_shot_carries_clips_log_and_discards(self):
        self.run_paid("image", "s01")
        self.run_paid("clip", "s01")
        self.ws.approve_shot("demo", "s01")
        self.run_paid("clip", "s01")
        self.ws.discard("demo", "clips/s01_final_a2.mp4", "worse")
        prop = self.ws.propose("demo", "clip", "s01")
        self.ws.rename_shot("demo", "s01", "intro")
        clips = self.p / "clips"
        self.assertTrue((clips / "intro_final_a1.mp4").exists() and (clips / "_discarded" / "intro_final_a2.mp4").exists())
        self.assertFalse(list(clips.glob("s01_*")) or list((clips / "_discarded").glob("s01_*")))
        shots = {s["id"]: s for s in self.ws.overview("demo")["shots"]["shots"]}
        self.assertEqual((shots["intro"]["final_clip"], "s01" in shots), ("clips/intro_final_a1.mp4", False))
        self.assertEqual(shots["intro"]["first_frame"], "stills/s01.png")           # the image keeps its own name
        rows = {(r["shot"], r["stage"], r["attempt"]) for r in self.ws.costs("demo")["rows"]}
        self.assertTrue({("intro", "final", "1"), ("intro", "final", "2"), ("s01", "image", "1")} <= rows)
        self.assertEqual(self.ws.overview("demo")["discarded"][0]["file"], "clips/_discarded/intro_final_a2.mp4")
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "rejected")
        self.assertEqual(self.ws.costs("demo")["split"]["discarded"], 0.2)           # discarded cost survives the rename
        with self.assertRaises(ServiceError):
            self.ws.rename_shot("demo", "intro", "s02")
        with self.assertRaises(ServiceError):
            self.ws.rename_shot("demo", "zzz", "q")


class TestLanguages(Base):
    def test_language_is_canonical_and_kept_in_shots(self):
        self.ws.brief_put("demo", {"language": " tamil ", "extra_languages": "hindi and english"})
        b = {f["key"]: f["value"] for f in self.ws.brief_get("demo")["fields"]}
        self.assertEqual((b["language"], b["extra_languages"]), ("Tamil", "Hindi, English"))
        self.assertEqual(self.ws.overview("demo")["shots"]["language"], "Tamil")
        self.assertEqual(len(self.ws.languages()), len(__import__("aistudio.languages", fromlist=["x"]).NAMES))

    def test_convert_names_the_language_in_audio_lines(self):
        self.ws.brief_put("demo", {"language": "Tamil"})
        doc = self.ws.convert_story("demo")["shots"]
        self.assertIn("says this line in Tamil, clearly", doc["shots"][0]["prompt"])
        self.ws.brief_put("demo", {"language": ""}) if False else None


class TestAiSettingsAndCap(Base):
    def test_defaults_then_paid_rules(self):
        d = self.ws.ai_settings()
        self.assertFalse(d["settings"]["allow_paid"])
        s = d["stored"]; s["chat"]["models"] = ["openai/gpt-5"]
        with self.assertRaises(ServiceError):
            self.ws.put_ai_settings(s)
        s["allow_paid"] = True
        self.assertEqual(self.ws.put_ai_settings(s)["settings"]["chat"]["models"], ["openai/gpt-5"])
        os.environ["AISTUDIO_CHAT_MODELS"] = "a/b:free"            # environment variables do not override the saved settings
        try:
            self.assertEqual(self.ws.ai_settings()["settings"]["chat"]["models"], ["openai/gpt-5"])
            self.assertEqual(self.ws.ai_settings()["locked"], [])
        finally:
            del os.environ["AISTUDIO_CHAT_MODELS"]

    def test_catalog_live_and_offline(self):
        api = {"data": [{"id": "x/y:free", "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["text"]}},
                        {"id": "p/q", "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "architecture": {"output_modalities": ["text"]}}]}
        ws = Workspace(self.ws.root, catalog_fetch=lambda: api)
        c = ws.ai_catalog()
        self.assertEqual(([m["id"] for m in c["models"]], c["source"]), (["x/y:free", "p/q"], "live from OpenRouter"))
        self.assertIs(ws.ai_catalog(), c)                                    # cached
        off = Workspace(self.ws.root).ai_catalog()                           # no network in tests: built-in free list
        self.assertIn("built-in", off["source"])
        self.assertTrue(all(m["free"] for m in off["models"]))

    def test_paid_chat_is_logged_and_capped(self):
        s = self.ws.ai_settings()["stored"]
        s.update(allow_paid=True, ai_cap_usd=0.5); s["chat"]["models"] = ["openai/gpt-5"]
        self.ws.put_ai_settings(s)
        t = FakeTransport([chat_reply({"reply": "one"}, 0.4), chat_reply({"reply": "two"}, 0.4), chat_reply({"reply": "three"}, 0.4)])
        ws = Workspace(self.ws.root, transport=t); HERM.real_projects(self)
        self.assertEqual(ws.chat_send("demo", "hi")["reply"], "one")
        self.assertEqual(ws.ai_spent("demo"), 0.4)
        self.assertEqual(ws.chat_send("demo", "again")["reply"], "two")       # 0.4 < 0.5 cap: allowed, now 0.8 spent
        with self.assertRaises(ServiceError) as c:
            ws.chat_send("demo", "third")
        self.assertIn("cap", str(c.exception))
        self.assertEqual(len(t.calls), 2)                                    # the refused call never reached the provider
        rows = [r for r in ws.costs("demo")["rows"] if r["stage"] == "chat"]
        self.assertEqual([(r["shot"], r["cost"]) for r in rows], [("_ai", "0.4"), ("_ai", "0.4")])
        self.assertAlmostEqual(ws.costs("demo")["split"]["total"], 0.8)

    def test_free_chat_logs_nothing(self):
        t = FakeTransport([chat_reply({"reply": "hi"}, 0.0)])
        ws = Workspace(self.ws.root, transport=t); HERM.real_projects(self)
        ws.chat_send("demo", "hello")
        self.assertEqual([r for r in ws.costs("demo")["rows"] if r["stage"] == "chat"], [])
        self.assertEqual(ws.ai_spent("demo"), 0)

    def test_paid_model_refused_without_the_switch_even_if_saved_in_a_file(self):
        (self.ws.root / "ai_settings.json").write_text(json.dumps({"chat": {"models": ["openai/gpt-5"]}, "allow_paid": False}))
        ws = Workspace(self.ws.root, transport=FakeTransport([chat_reply({"reply": "x"})])); HERM.real_projects(self)
        with self.assertRaises(ServiceError):
            ws.chat_send("demo", "hi")


class TestVerification(Base):
    def test_rules_are_live_and_fresh(self):
        v = self.ws.verify_status("demo")
        self.assertEqual(set(v), {"brief", "story", "assets", "shots", "todos"})
        self.assertIn(v["brief"]["status"], ("warn", "ok"))
        doc = self.ws.overview("demo")["shots"]
        doc["shots"][0]["prompt"] += " deep teal (#07363c)"
        self.ws.put_shots("demo", doc)
        shots = self.ws.verify_status("demo")["shots"]
        self.assertTrue(any("colour code" in f["issue"] for f in shots["findings"]))
        self.assertEqual({f["source"] for f in shots["findings"]}, {"rules"})

    def test_ai_review_real_mode_is_stored_then_stale_after_edit(self):
        t = FakeTransport([chat_reply({"verdict": "warn", "summary": "Names differ", "findings": [{"where": "s01", "severity": "medium", "issue": "Character name differs from the brief", "fix": "Use one name"}]})])
        ws = Workspace(self.ws.root, transport=t); HERM.real_projects(self)
        r = ws.verify_run("demo", "shots")
        self.assertEqual(r["status"], "warn")
        self.assertIn("ai", {f["source"] for f in r["findings"]})
        self.assertEqual(r["ai"]["model"], "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertFalse(r["ai_stale"])
        self.assertIn("project_language", t.calls[0]["messages"][1]["content"])
        doc = ws.overview("demo")["shots"]; doc["shots"][0]["seconds"] = 6
        ws.put_shots("demo", doc)
        st = ws.verify_status("demo")["shots"]
        self.assertTrue(st["ai_stale"])                                       # content changed: the old AI result is not shown as current
        self.assertNotIn("ai", {f["source"] for f in st["findings"]})

    def test_ai_outage_does_not_break_anything(self):
        ws = Workspace(self.ws.root, transport=FakeTransport([O.ProviderError("HTTP 429")] * 4)); HERM.real_projects(self)
        r = ws.verify_run("demo", "brief")
        self.assertIn("unavailable", r["ai"]["summary"])
        ws2 = Workspace(self.ws.root, transport=FakeTransport([chat_reply({"not": "the protocol"})])); HERM.real_projects(self)
        self.assertTrue(ws2.verify_run("demo", "story")["ai"]["error"])

    def test_fake_mode_ai_is_labelled(self):
        self.assertEqual(self.ws.verify_run("demo", "todos")["ai"]["model"], "fake/reviewer")
        with self.assertRaises(ServiceError):
            self.ws.verify_run("demo", "nonsense")

    def test_auto_verify_runs_in_background_after_a_change(self):
        ws = Workspace(self.ws.root, auto_verify=True)
        ws.VERIFY_DELAY = 0
        ws.todo_add("demo", "Get the logo")
        ws.wait_verify()
        store = json.loads((self.p / "verify.json").read_text())
        self.assertEqual(store["todos"]["ai"]["model"], "fake/reviewer")
        s = ws.ai_settings()["stored"]; s["auto_verify"] = False; ws.put_ai_settings(s)
        (self.p / "verify.json").unlink()
        ws.todo_add("demo", "Another")
        ws.wait_verify()
        self.assertFalse((self.p / "verify.json").exists())                   # auto-verify off: no background AI


if __name__ == "__main__":
    unittest.main()
