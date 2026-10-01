import tests._hermetic as HERM  # noqa: F401
import json, os, tempfile, unittest
from aistudio import chat as C
from aistudio.providers import openrouter as O
from aistudio.service import Workspace, ServiceError


class FakeTransport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, path, body=None, raw=False):
        self.calls.append(body)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}], "usage": {"cost": 0}}


class TestChatLogic(unittest.TestCase):
    def test_progress_and_missing(self):
        self.assertEqual(C.progress({})["required_done"], 0)
        b = {k: "x" for k, _, _, r in C.BRIEF_FIELDS if r}
        self.assertTrue(C.progress(b)["complete"])
        b.pop("goal")
        self.assertEqual(C.missing(b), ["goal"])

    def test_clean_updates(self):
        u = C.clean_updates({"brand": " Chai ", "evil": "x", "goal": "", "story": 5, "cta": ["x"], "setting": "a" * 5000})
        self.assertEqual(set(u), {"brand", "story", "setting"})
        self.assertEqual((u["brand"], u["story"], len(u["setting"])), ("Chai", "5", C.MAX_VALUE))

    def test_parse_turn(self):
        t = C.parse_turn('Sure!\n```json\n{"reply": "Hi", "brief_updates": {"brand": "X", "zzz": "no"}, "todos_add": ["a", "b", "c", "d", "e", "f", "g"], "storyboard_md": null}\n```')
        self.assertEqual((t["reply"], t["brief_updates"], len(t["todos_add"]), t["storyboard_md"]), ("Hi", {"brand": "X"}, 6, None))
        for bad in ("", "no json at all", "{broken", '{"nope": 1}'):
            r = C.parse_turn(bad)
            self.assertIsInstance(r["reply"], str)
            self.assertEqual((r["brief_updates"], r["todos_add"]), ({}, []))
        self.assertEqual(C.parse_turn("plain answer")["reply"], "plain answer")

    def test_free_only_guard(self):
        self.assertEqual(C.check_chat_models(["a/b:free", "openrouter/free"]), ["a/b:free", "openrouter/free"])
        with self.assertRaises(ValueError):
            C.check_chat_models(["a/b:free", "openai/gpt-5"])
        self.assertEqual(C.check_chat_models(["openai/gpt-5"], allow_paid=True), ["openai/gpt-5"])      # only the Settings switch allows paid models
        os.environ["AISTUDIO_ALLOW_PAID_CHAT"] = "1"
        os.environ["AISTUDIO_CHAT_MODELS"] = "x/y:free"
        try:
            with self.assertRaises(ValueError):
                C.check_chat_models(["openai/gpt-5"])                      # environment variables no longer change anything
            self.assertEqual(C.chat_models(), list(C.FREE_MODELS))
        finally:
            del os.environ["AISTUDIO_ALLOW_PAID_CHAT"], os.environ["AISTUDIO_CHAT_MODELS"]

    def test_build_messages(self):
        state = {"brief_so_far": {"brand": "Chai"}, "budget": {"approved": True}}
        m = C.build_messages([{"role": "user", "text": "hi"}, {"role": "assistant", "text": "yo"}] * 20, "now", state)
        self.assertEqual((m[0]["role"], m[-1]), ("system", {"role": "user", "content": "now"}))
        self.assertIn('"brand": "Chai"', m[0]["content"])
        self.assertIn('"approved": true', m[0]["content"])                      # the real budget state is in front of the model
        self.assertIn("You are TARA", m[0]["content"])
        self.assertIn("NEVER say that you generated", m[0]["content"])           # and it may not claim actions it cannot take
        self.assertIn("NEVER ask for budget approval again", m[0]["content"])
        self.assertLessEqual(len(m), 18)
        f = [{"id": "logo", "file": "logo.png", "colors": ["#f08c14", "#0a5a64"]}]
        m = C.build_messages([], "here is my logo", state, files=f)
        self.assertIn("logo (saved in Uploads; main colours #f08c14, #0a5a64)", m[-1]["content"])

    def test_story_builder_is_valid(self):
        b = {"brand": "Chai Corner", "story": "Meena opens her stall. She pours tea. Customers smile.", "characters": "Meena, 40s, saree",
             "setting": "street stall", "length_seconds": "12", "language": "English", "cta": "Visit today"}
        md = C.build_story_md(b)
        self.assertTrue(C.valid_storyboard(md))
        self.assertFalse(C.valid_storyboard("# nothing"))


class TestOpenRouterLLM(unittest.TestCase):
    def test_fallback_chain(self):
        t = FakeTransport([O.ProviderError("HTTP 429 rate limited"), O.ProviderError("HTTP 500"), reply({"reply": "ok"})])
        r = O.OpenRouterLLM(["a:free", "b:free", "c:free"], transport=t).complete([{"role": "user", "content": "x"}])
        self.assertEqual((r["model"], r["cost"]), ("c:free", 0.0))
        self.assertEqual([c["model"] for c in t.calls], ["a:free", "b:free", "c:free"])

    def test_all_fail_and_paid_refused(self):
        with self.assertRaises(O.ProviderError) as c:
            O.OpenRouterLLM(["a:free"], transport=FakeTransport([O.ProviderError("HTTP 429")])).complete([])
        self.assertIn("all free chat models failed", str(c.exception))
        with self.assertRaises(ValueError):
            O.OpenRouterLLM(["openai/gpt-5"], transport=FakeTransport([]))
        with self.assertRaises(O.ProviderError):
            O.OpenRouterLLM(["a:free"], transport=FakeTransport([{"choices": [{"message": {"content": "  "}}]}])).complete([])


class TestServiceChat(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")

    def test_scripted_interview_to_storyboard(self):
        h = self.ws.chat_send("demo", "hello")
        self.assertIn("brand", h["reply"].lower())
        self.assertIn("I'm Tara", h["reply"])                  # the producer introduces itself by name
        answers = ["Chai Corner, a street tea stall", "Get more walk-ins", "Meena pours tea. Customers smile. She waves.", "12", "English",
                   "Meena, 40s, cotton saree", "A small street tea stall", "500"]
        for a in answers:
            h = self.ws.chat_send("demo", a)
        self.assertTrue(h["brief"]["complete"])
        self.assertIn("logo", h["reply"].lower())              # before drafting it asks about the logo and brand colours
        self.assertFalse(h["applied"])
        h = self.ws.chat_send("demo", "skip")
        self.assertTrue(h["applied"])                          # brief -> story -> todo, by itself in a fresh project
        self.assertFalse(h["pending_story"])
        self.assertEqual(self.ws.brief_get("demo")["fields"][0]["value"], "Chai Corner, a street tea stall")
        p = self.ws.pdir("demo")
        self.assertIn("Chai Corner", (p / "brief.md").read_text())
        self.assertIn("Shot 01", (p / "Story.md").read_text())
        self.assertEqual(len(json.loads((p / "shots.json").read_text())["shots"]), 3)
        todo = (p / "TODO.md").read_text()
        self.assertIn("speaker check every voice line", todo)
        self.assertIn("(3 shots)", todo)
        with self.assertRaises(ServiceError):
            self.ws.apply_pending_story("demo")                  # nothing pending any more

    def test_existing_shots_keep_the_draft_for_the_user(self):
        p = self.ws.pdir("demo")
        (p / "shots.json").write_text(json.dumps({"aspect_ratio": "9:16", "audio": False, "shots": [{"id": "s01", "model": "m", "seconds": 4, "prompt": "p"}]}))
        for a in ["hello", "Chai Corner", "Get more walk-ins", "Meena pours tea. Customers smile. She waves.", "12", "English", "Meena, 40s", "A tea stall", "500", "skip"]:
            h = self.ws.chat_send("demo", a)
        self.assertFalse(h["applied"])
        self.assertTrue(h["pending_story"])

    def test_apply_refuses_when_clips_approved(self):
        self.ws.convert_story  # noqa
        p = self.ws.pdir("demo")
        (p / "pending_story.md").write_text(C.build_story_md({"brand": "X", "story": "One.", "characters": "A", "setting": "s", "length_seconds": "4"}), encoding="utf-8")
        (p / "shots.json").write_text(json.dumps({"shots": [{"id": "s01", "model": "m", "seconds": 4, "prompt": "p", "final_ok": True}]}))
        with self.assertRaises(ServiceError):
            self.ws.apply_pending_story("demo")

    def test_todos(self):
        t = self.ws.todos("demo")
        self.assertEqual([x["id"] for x in t["auto"]], ["brief", "story", "budget", "images", "clips"])
        self.assertFalse(any(x["done"] for x in t["auto"]))
        self.assertEqual(len(t["manual"]), 3)
        t = self.ws.todo_add("demo", "Get the shop logo")
        new = t["manual"][-1]
        self.assertFalse(new["done"])
        self.assertTrue(self.ws.todo_toggle("demo", new["id"])["manual"][-1]["done"])
        self.assertEqual(len(self.ws.todo_remove("demo", new["id"])["manual"]), 3)
        with self.assertRaises(ServiceError):
            self.ws.todo_toggle("demo", "nope")
        with self.assertRaises(ServiceError):
            self.ws.todo_add("demo", "  ")

    def test_real_mode_uses_free_models_and_applies_turn(self):
        t = FakeTransport([reply({"reply": "Nice! Who is it for?", "brief_updates": {"brand": "Chai Corner", "bogus": "x"}, "todos_add": ["Get the logo file"], "storyboard_md": None})])
        ws = Workspace(self.ws.root, transport=t)
        HERM.real_projects(self)
        h = ws.chat_send("demo", "I run Chai Corner")
        self.assertEqual(h["reply"], "Nice! Who is it for?")
        self.assertEqual(ws.brief_get("demo")["fields"][0]["value"], "Chai Corner")
        self.assertIn("Get the logo file", [x["title"] for x in ws.todos("demo")["manual"]])
        self.assertTrue(all(c["model"].endswith(":free") or c["model"] == "openrouter/free" for c in t.calls))
        self.assertIn("PRODUCER", t.calls[0]["messages"][0]["content"])

    def test_test_pipeline_project_has_real_chat_and_fake_everything_else(self):
        t = FakeTransport([reply({"reply": "Here is how it works.", "brief_updates": {}, "todos_add": [], "storyboard_md": None})])
        ws = Workspace(self.ws.root, transport=t)
        ws.create_project("practice", test_pipeline=True)
        h = ws.chat_send("practice", "How does this work?")
        self.assertEqual(h["reply"], "Here is how it works.")
        self.assertTrue(h["test_pipeline"])
        self.assertIn("TEST PIPELINE", t.calls[0]["messages"][0]["content"])
        self.assertEqual(ws.overview("practice")["mode"], "test")
        p = ws.pdir("practice")
        self.assertNotEqual(ws.runner().resolve("chat", p)[0]["ptype"], "fake")
        self.assertEqual(ws.runner().resolve("image", p)[0]["ptype"], "fake")
        self.assertEqual(ws.runner().resolve("video", p)[0]["ptype"], "fake")
        self.assertFalse(ws.overview("demo")["test_pipeline"])

    def test_real_mode_bad_storyboard_is_not_saved_and_outage_is_friendly(self):
        bad = reply({"reply": "Here", "storyboard_md": "# not a storyboard"})
        t = FakeTransport([bad, bad])                      # the model is asked a second time; it is wrong again
        ws = Workspace(self.ws.root, transport=t)
        HERM.real_projects(self)
        h = ws.chat_send("demo", "go")
        self.assertEqual(len(t.calls), 2)
        self.assertFalse(h["pending_story"])
        self.assertIn("not in the right format", h["reply"])
        ws2 = Workspace(self.ws.root, transport=FakeTransport([O.ProviderError("HTTP 429")] * 4))
        with self.assertRaises(ServiceError) as c:
            ws2.chat_send("demo", "hi")
        self.assertIn("unavailable", str(c.exception))

    def test_input_limits(self):
        for bad in ("", "   ", "x" * 3001):
            with self.assertRaises(ServiceError):
                self.ws.chat_send("demo", bad)


if __name__ == "__main__":
    unittest.main()
