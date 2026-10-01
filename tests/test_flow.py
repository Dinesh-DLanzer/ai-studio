import tests._hermetic as HERM  # noqa: F401
import json, tempfile, unittest
from pathlib import Path
from aistudio import chat as C
from aistudio.service import ServiceError, Workspace
from aistudio.storyboard import convert as S

PNG_ORANGE = None


def logo_bytes():
    from PIL import Image, ImageDraw
    import io
    im = Image.new("RGBA", (120, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([10, 10, 110, 110], fill=(240, 140, 20, 255))
    d.rectangle([50, 50, 70, 70], fill=(10, 90, 100, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


ANSWERS = ["Chai Corner, a street tea stall", "Get more walk-ins", "Meena pours tea. Customers smile. She waves.", "12", "English",
           "Meena, 40s, cotton saree", "A small street tea stall", "500"]


class Base(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.p = self.ws.pdir("demo")

    def interview(self, last="skip"):
        self.ws.chat_send("demo", "hello")
        for a in ANSWERS:
            self.ws.chat_send("demo", a)
        return self.ws.chat_send("demo", last)

    def add_logo(self):
        (self.p / "stills").mkdir(exist_ok=True)
        (self.p / "stills" / "logo.png").write_bytes(logo_bytes())
        self.ws.import_stills("demo", [{"file": "logo.png", "id": "logo", "kind": "other"}])


class TestStoryParts(unittest.TestCase):
    def test_sections_become_assets_with_refs_and_style(self):
        md = C.build_story_md({"brand": "X", "story": "One. Two.", "characters": "Meena, 40s, saree", "setting": "tea stall", "length_seconds": "8",
                               "brand_assets": "Logo file: logo. Brand colours: #f08c14, #0a5a64.", "cta": "Visit"})
        st = S.parse_story(md)
        self.assertEqual([c["id"] for c in st["characters"]], ["meena"])
        self.assertEqual([b["id"] for b in st["backgrounds"]], ["main_place"])
        self.assertIn("#f08c14", st["style"])
        img = S.to_images_doc(st, known_ids=["logo"])
        self.assertEqual([(i["id"], i["kind"]) for i in img["images"]], [("meena", "character"), ("main_place", "background"), ("s01", "frame"), ("s02", "frame")])
        self.assertEqual(img["images"][2]["refs"], ["meena", "main_place"])
        self.assertEqual(img["images"][3]["refs"], ["meena", "main_place", "logo"])      # the logo is used in the last (call to action) shot
        self.assertEqual(img["style"], st["style"])

    def test_nobody_and_no_place_means_no_character_or_background(self):
        md = C.build_story_md({"brand": "X", "story": "Colours swirl.", "characters": "none", "setting": "none", "length_seconds": "4"})
        st = S.parse_story(md)
        self.assertEqual((st["characters"], st["backgrounds"]), ([], []))
        self.assertEqual([i["kind"] for i in S.to_images_doc(st)["images"]], ["frame"])


class TestInterviewFlow(Base):
    def test_story_gets_style_characters_backgrounds_and_the_logo(self):
        self.add_logo()
        self.ws.chat_send("demo", "hello")
        for a in ANSWERS:
            h = self.ws.chat_send("demo", a)
        self.assertIn("logo", h["reply"].lower())
        h = self.ws.chat_send("demo", "yes, use my brand colours", attachments=["logo"])
        self.assertTrue(h["applied"])
        user = [m for m in h["messages"] if m["role"] == "user"][-1]
        self.assertEqual(user["attachments"][0]["id"], "logo")                          # the bubble can show the picture
        self.assertEqual(user["attachments"][0]["colors"][0], "#f08c14")                # colours were read from the logo
        story = (self.p / "Story.md").read_text()
        self.assertIn("## Shared style", story)
        self.assertIn("#f08c14", story)
        imgs = json.loads((self.p / "images.json").read_text())
        kinds = sorted(i["kind"] for i in imgs["images"])
        self.assertEqual(kinds, ["background", "character", "frame", "frame", "frame", "other"])
        self.assertIn("#f08c14", imgs["style"])                                          # the shared style is part of every image prompt
        self.assertTrue(any(i["id"] == "logo" and i["kind"] == "other" for i in imgs["images"]))   # applying the story kept the upload

    def test_bad_attachments_are_refused(self):
        with self.assertRaises(ServiceError):
            self.ws.chat_send("demo", "hi", attachments=["nope"])
        with self.assertRaises(ServiceError):
            self.ws.chat_send("demo", "hi", attachments=["a", "b", "c", "d", "e"])


class TestProductionOrder(Base):
    def nxt(self):
        return self.ws.production_progress("demo")["next"]

    def test_checklist_follows_the_fixed_order(self):
        self.assertEqual(self.nxt()["kind"], "chat")                                     # brief first
        self.interview()
        self.assertEqual(self.nxt()["kind"], "budget")                                   # storyboard applied, budget not approved
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        n = self.nxt()
        self.assertEqual((n["kind"], n["target"]), ("image", "meena"))                   # characters first
        for want in ("meena", "main_place", "s01", "s02", "s03"):
            n = self.nxt()
            self.assertEqual((n["kind"], n["target"]), ("image", want))
            (self.p / "stills" / f"{want}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        n = self.nxt()
        self.assertEqual((n["kind"], n["target"]), ("clip", "s01"))                      # only now the clips
        groups = {g["key"]: (g["done"], g["total"]) for g in self.ws.production_progress("demo")["groups"]}
        self.assertEqual((groups["character"], groups["background"], groups["frame"], groups["clip"]), ((1, 1), (1, 1), (3, 3), (0, 3)))

    def test_server_refuses_a_frame_before_its_character_and_a_clip_before_its_frame(self):
        self.interview()
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        with self.assertRaises(ServiceError) as c:
            self.ws.propose("demo", "image", "s01")                                       # needs meena + main_place first
        self.assertIn("reference not found", str(c.exception))
        with self.assertRaises(ServiceError) as c:
            self.ws.propose("demo", "clip", "s01")
        self.assertIn("first frame missing", str(c.exception))

    def test_generate_all_plan_lists_every_item_with_its_exact_price(self):
        self.interview()
        with self.assertRaises(ServiceError):
            self.ws.generate_all_plan("demo")                                     # budget not approved: nothing to run yet
        self.assertEqual(self.ws.production_progress("demo")["queue"], [])
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        q = self.ws.production_progress("demo")["queue"]
        self.assertEqual([(x["kind"], x["target"]) for x in q], [("image", "meena"), ("image", "main_place"), ("image", "s01"), ("image", "s02"), ("image", "s03"),
                                                                 ("clip", "s01"), ("clip", "s02"), ("clip", "s03")])      # assets first, then clips
        plan = self.ws.generate_all_plan("demo")
        self.assertEqual(len(plan["items"]), 8)
        self.assertAlmostEqual(plan["total"], sum(i["price"] for i in plan["items"]), places=6)
        self.assertTrue(all(i["price"] > 0 for i in plan["items"]))
        self.assertEqual(plan["budget"]["spent"], 0)
        self.assertEqual(self.ws.overview("demo")["costs"]["total"], 0)                        # quoting spent nothing and created no proposal
        self.assertEqual(self.ws._read(self.p, "proposals.json", []), [])

    def test_the_queue_shrinks_as_things_are_made(self):
        self.interview()
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        (self.p / "stills" / "meena.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.ws.production_progress("demo")["queue"][0]["target"], "main_place")

    def test_chat_state_has_the_real_budget_and_assets(self):
        self.interview()
        st = self.ws._chat_state(self.p)
        self.assertFalse(st["budget"]["approved"])
        self.assertEqual([a["id"] for a in st["assets"]][:2], ["meena", "main_place"])
        self.assertTrue(all(not a["made"] for a in st["assets"]))
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        st = self.ws._chat_state(self.p)
        self.assertTrue(st["budget"]["approved"])
        self.assertIn("meena", st["next_step_for_the_user"])


class TestRealChatSeesTheTruth(Base):
    """The real chat model gets the project's real state every turn and the logo + colours are remembered, whatever the model replies."""
    def setUp(self):
        super().setUp()
        import os
        os.environ.pop("AISTUDIO_ALL_TEST", None)
        from tests.test_chat import FakeTransport, reply
        self.t = FakeTransport([reply({"reply": "Nice logo. Want the video to use its colours?", "brief_updates": {}, "todos_add": [], "storyboard_md": None})])
        self.ws = Workspace(self.ws.root, transport=self.t)
        self.add_logo()

    def test_state_and_attachment_reach_the_model_and_the_brief(self):
        self.ws.chat_send("demo", "here is my logo", attachments=["logo"])
        msgs = self.t.calls[0]["messages"]
        system, user = msgs[0]["content"], msgs[-1]["content"]
        self.assertIn('"budget": {"estimate": null, "approved": false}', system)       # the model is told the budget is NOT approved
        self.assertIn('"uploads": [{"id": "logo", "colors": ["#f08c14"', system)
        self.assertIn("main colours #f08c14", user)
        self.assertIn("Logo file: logo", self.ws.brief_get("demo")["fields"][11]["value"])        # brand_assets
        self.assertIn("#f08c14", self.ws.brief_get("demo")["fields"][11]["value"])

    def test_approved_budget_is_visible_to_the_model(self):
        self.interview_to_story()
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        self.t.responses.append(__import__("tests.test_chat", fromlist=["reply"]).reply({"reply": "ok", "brief_updates": {}, "todos_add": [], "storyboard_md": None}))
        self.ws.chat_send("demo", "budget is approved, proceed")
        self.assertIn('"approved": true', self.t.calls[-1]["messages"][0]["content"])
        self.assertIn("character image: ", self.t.calls[-1]["messages"][0]["content"])      # and what the next step really is

    def interview_to_story(self):
        (self.p / "Story.md").write_text(C.build_story_md({"brand": "X", "story": "One. Two.", "characters": "Meena, 40s", "setting": "stall", "length_seconds": "8"}), encoding="utf-8")
        self.ws.convert_story("demo")
        self.ws.brief_put("demo", {"brand": "X", "goal": "g", "story": "One. Two.", "length_seconds": "8", "language": "English", "characters": "Meena", "setting": "stall", "budget_cap": "5"})


def raw_reply(text):
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "x:free"}


TOOL_CALL = ("<|tool_call_start|>[write_storyboard(storyboard_md='# Shot 01 \u2014 0:00\u20130:04\\n### Purpose: HOOK\\nVisual\\nGandhi walks', "
             "brief_updates={'brand': 'God promo', 'budget_cap': '$1'}, todos_add=['Make the character image'])]<|tool_call_end|>")


class TestUnreadableModelAnswers(Base):
    def setUp(self):
        super().setUp()
        import os
        os.environ.pop("AISTUDIO_ALL_TEST", None)

    def ws_with(self, *answers):
        from tests.test_chat import FakeTransport
        self.t = FakeTransport(list(answers))
        return Workspace(self.ws.root, transport=self.t)

    def test_pseudo_tool_call_is_recovered_not_shown_raw(self):
        t = C.parse_turn(TOOL_CALL)
        self.assertEqual((t["reply"], t["brief_updates"], t["todos_add"], t["malformed"]), ("I drafted the storyboard.", {"brand": "God promo", "budget_cap": "$1"}, ["Make the character image"], False))
        self.assertNotIn("tool_call", t["reply"])
        self.assertEqual(C.parse_turn("{'reply': 'Hello', 'brief_updates': {'brand': 'Y'}}")["brief_updates"], {"brand": "Y"})   # python-style dict
        self.assertFalse(C.parse_turn("Just friendly words.")["malformed"])
        self.assertTrue(C.parse_turn("<|tool_call_start|>garbage((")["malformed"])

    def test_a_bad_format_is_asked_again_once(self):
        from tests.test_chat import reply
        ws = self.ws_with(raw_reply(TOOL_CALL), reply({"reply": "What is the goal of the video?", "brief_updates": {"brand": "God promo"}, "todos_add": [], "storyboard_md": None}))
        h = ws.chat_send("demo", "Gandhi walking on a beach")
        self.assertEqual(h["reply"], "What is the goal of the video?")
        self.assertEqual(len(self.t.calls), 2)
        self.assertIn("could not be read", self.t.calls[1]["messages"][-1]["content"])           # the rules were repeated
        self.assertEqual(ws.brief_get("demo")["fields"][0]["value"], "God promo")
        self.assertFalse(any("tool_call" in m["text"] for m in h["messages"]))

    def test_two_bad_answers_give_a_friendly_message_and_no_raw_junk(self):
        ws = self.ws_with(raw_reply("<|tool_call_start|>[broken((("), raw_reply("<|tool_call_start|>[still_broken((("))
        h = ws.chat_send("demo", "hello")
        self.assertIn("could not read", h["reply"])
        self.assertFalse(any("tool_call" in m["text"] for m in h["messages"]))

    def test_old_unreadable_messages_already_saved_are_hidden(self):
        (self.p / "chat.json").write_text(json.dumps([{"role": "assistant", "text": TOOL_CALL, "ts": "2026-01-01T00:00:00"}, {"role": "assistant", "text": "A normal answer.", "ts": "2026-01-01T00:00:01"}]))
        msgs = self.ws.chat_history("demo")["messages"]
        self.assertNotIn("tool_call", msgs[0]["text"])
        self.assertEqual(msgs[1]["text"], "A normal answer.")


class TestFavoritesAndCounts(Base):
    def test_favorite_toggle_and_card_counts(self):
        self.add_logo()
        row = self.ws.list_projects()[0]
        self.assertEqual((row["favorite"], row["assets"], row["shots"]), (False, 1, 0))
        self.assertEqual(self.ws.set_favorite("demo", True), {"name": "demo", "favorite": True})
        self.assertTrue(self.ws.list_projects()[0]["favorite"])
        self.assertTrue((self.p / "favorite.json").exists())
        self.ws.set_favorite("demo", False)
        self.assertFalse(self.ws.list_projects()[0]["favorite"])
        self.ws.set_favorite("demo", False)                                   # unmarking twice is harmless
        with self.assertRaises(ServiceError):
            self.ws.set_favorite("nope", True)


class TestUploadsSurviveConvert(Base):
    def test_reconverting_keeps_uploads_and_style(self):
        self.add_logo()
        (self.p / "Story.md").write_text(C.build_story_md({"brand": "X", "story": "One.", "characters": "none", "setting": "none", "length_seconds": "4",
                                                           "brand_assets": "Brand colours: #112233."}), encoding="utf-8")
        self.ws.convert_story("demo")
        imgs = json.loads((self.p / "images.json").read_text())
        self.assertIn("logo", [i["id"] for i in imgs["images"]])
        self.assertIn("#112233", imgs["style"])


if __name__ == "__main__":
    unittest.main()
