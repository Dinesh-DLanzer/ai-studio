import unittest
from aistudio import verify as V

SHOT = {"id": "s01", "model": "google/veo-3.1-lite", "seconds": 4, "audio": True, "first_frame": "stills/s01.png",
        "prompt": 'SUBJECT: Ramesh, same face as the first frame. ACTION: waves. AUDIO: says this line: "கடை இருக்கு" (I have a shop). NEGATIVE: no on-screen text, no logos.'}


def sh(**kw):
    s = dict(SHOT); s.update(kw)
    return {"shots": [s]}


def whats(findings):
    return {(x["where"], x["severity"]) for x in findings}


class TestRules(unittest.TestCase):
    def test_clean_shot(self):
        self.assertEqual(V.lint_shots(sh(), {"images": [{"id": "s01"}]}, {"s01"}, "Tamil"), [])

    def test_hex_and_empty_centre(self):
        f = V.lint_shots(sh(prompt=SHOT["prompt"] + " deep teal (#07363c) with an empty centre for the logo"), None, {"s01"}, "Tamil")
        self.assertEqual(sum(1 for x in f if x["severity"] == "medium"), 2)

    def test_first_frame_missing_is_high(self):
        s = sh(); del s["shots"][0]["first_frame"]
        self.assertIn(("s01", "high"), whats(V.lint_shots(s, None, set(), "Tamil")))

    def test_audio_consistency(self):
        self.assertIn(("s01", "medium"), whats(V.lint_shots(sh(prompt="SUBJECT: x. NEGATIVE: no text.", first_frame="stills/s01.png"), None, {"s01"}, "")))
        self.assertIn(("s01", "medium"), whats(V.lint_shots(sh(audio=False), None, {"s01"}, "Tamil")))

    def test_tanglish_is_high_for_tamil(self):
        p = 'SUBJECT: a. AUDIO: says: "kadai irukku instagram irukku" (x). NEGATIVE: no text.'
        self.assertIn(("s01", "high"), whats(V.lint_shots(sh(prompt=p), None, {"s01"}, "Tamil")))
        self.assertNotIn(("s01", "high"), whats(V.lint_shots(sh(prompt=p), None, {"s01"}, "English")))

    def test_long_line_claims_and_seconds(self):
        long = 'SUBJECT: a. AUDIO: says: "' + " ".join(["word"] * 20) + '" (x). NEGATIVE: no text.'
        self.assertIn(("s01", "medium"), whats(V.lint_shots(sh(prompt=long), None, {"s01"}, "English")))
        claim = 'SUBJECT: a. AUDIO: says: "guaranteed sales" (x). NEGATIVE: no text.'
        self.assertIn(("s01", "medium"), whats(V.lint_shots(sh(prompt=claim), None, {"s01"}, "English")))
        self.assertIn(("s01", "high"), whats(V.lint_shots(sh(seconds=5), None, {"s01"}, "Tamil")))

    def test_frame_not_created_and_not_in_list(self):
        f = V.lint_shots(sh(), {"images": [{"id": "other"}]}, set(), "Tamil")
        self.assertEqual({x["severity"] for x in f}, {"low", "medium"})

    def test_assets(self):
        imgs = {"images": [{"id": "hero", "kind": "character", "prompt": "a man", "refs": []},
                           {"id": "shop", "kind": "background", "prompt": "a shop with customers", "refs": []},
                           {"id": "s01", "kind": "frame", "prompt": "x", "refs": ["shop", "ghost"], "aspect_ratio": "16:9"}]}
        f = V.lint_assets(imgs, {"hero.png"}, {"platform": "Instagram Reels"})
        w = whats(f)
        self.assertIn(("hero", "low"), w); self.assertIn(("shop", "low"), w)
        self.assertIn(("s01", "medium"), w); self.assertIn(("s01", "high"), w)
        self.assertEqual(V.lint_assets({"images": [{"id": "s01", "kind": "frame", "prompt": "x", "refs": []}]}, set())[0]["severity"], "medium")

    def test_brief(self):
        f = V.lint_brief({"language": "Hindi", "budget_cap": "0.5", "length_seconds": "60"}, required_missing=["brand"])
        w = whats(f)
        self.assertIn(("brief.language", "medium"), w)
        self.assertIn(("brief.budget_cap", "medium"), w)
        self.assertIn(("brief", "low"), w)
        self.assertEqual(V.lint_brief({"language": "Tamil", "budget_cap": "10", "length_seconds": "12"}), [])
        self.assertIn(("brief.language", "low"), whats(V.lint_brief({"language": "Klingon"})))

    def test_story(self):
        md = "# CHAI: STORY\n\n## Shot 01 — 0:00–0:04\n### Purpose: HOOK\n\n**Voice** (ON-CAMERA)\n> kadai irukku\n\n**AI Video Prompt**\n> SUBJECT: a customer smiles. NEGATIVE: no text.\n"
        w = whats(V.lint_story(md, {"brand": "Chai", "length_seconds": "40"}, "Tamil"))
        self.assertIn(("s01", "high"), w)        # Tanglish
        self.assertIn(("s01", "medium"), w)      # on-camera without image
        self.assertIn(("Story.md", "low"), w)    # 4s vs 40s
        self.assertEqual(V.lint_story("# nothing", {}, "")[0]["where"], "Story.md")

    def test_todos(self):
        t = [{"id": "a", "title": "Get logo", "done": False}, {"id": "b", "title": "get logo", "done": False}]
        self.assertEqual(len(V.lint_todos(t)), 1)


class TestAiProtocol(unittest.TestCase):
    def test_result_and_status(self):
        self.assertEqual(V.result([])["status"], "ok")
        r = V.result([V.f("a", "low", "x"), V.f("b", "high", "y")])
        self.assertEqual((r["status"], r["findings"][0]["severity"]), ("fail", "high"))
        self.assertEqual(V.result([V.f("a", "low", "x")])["status"], "warn")

    def test_parse_ai(self):
        t = 'Sure:\n```json\n{"verdict":"warn","summary":"ok","findings":[{"where":"s01","severity":"medium","issue":"Name mismatch","fix":"rename"},{"issue":""},{"where":"x","severity":"weird","issue":"odd"}]}\n```'
        r = V.parse_ai(t)
        self.assertTrue(r["ok"])
        self.assertEqual([(x["where"], x["severity"]) for x in r["findings"]], [("s01", "medium"), ("x", "low")])
        for bad in ("", "no json", "{broken", '{"verdict":"pass"}'):
            self.assertFalse(V.parse_ai(bad)["ok"])

    def test_messages_and_hash(self):
        m = V.build_ai_messages("shots", {"a": 1}, {"brand": "X", "goal": ""}, "Tamil", [V.f("s01", "low", "z")])
        self.assertEqual(m[0]["role"], "system")
        self.assertIn('"project_language": "Tamil"', m[1]["content"])
        self.assertNotIn('"goal"', m[1]["content"])                          # empty brief fields are not sent
        self.assertEqual(V.content_hash({"a": 1}, "x"), V.content_hash({"a": 1}, "x"))
        self.assertNotEqual(V.content_hash({"a": 1}), V.content_hash({"a": 2}))


if __name__ == "__main__":
    unittest.main()
