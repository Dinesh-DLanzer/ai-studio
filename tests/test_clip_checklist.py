import json, unittest
from aistudio.vision import clip_checklist as V


class TestChecklist(unittest.TestCase):
    def test_checklist(self):
        self.assertEqual(len(V.CHECKLIST), 7)
        self.assertTrue(V.CHECKLIST[0].startswith("Only the intended characters"))
        self.assertTrue(V.CHECKLIST[4].startswith("No broken, ghosted"))

    def test_prompt(self):
        p = V.build_prompt({"id": "s12", "characters": ["Suresh"]}, 6)
        for needle in ("s12", "6", "Suresh", "1.", "7.", '"verdict"', "JSON"):
            self.assertIn(needle, p)
        for c in V.CHECKLIST:
            self.assertIn(c, p)
        self.assertIn("unknown", V.build_prompt({"id": "s1"}, 3))

    def good(self, **kw):
        d = {"verdict": "pass", "findings": [], "summary": "ok"}
        d.update(kw)
        return d

    def test_parse_plain_and_fenced(self):
        d = self.good()
        self.assertEqual(V.parse_review(json.dumps(d)), d)
        self.assertEqual(V.parse_review("Here you go:\n```json\n" + json.dumps(d) + "\n```\nthanks"), d)

    def test_parse_findings(self):
        d = self.good(verdict="fail", findings=[{"frame": 5, "issue": "extra man", "severity": "high"}], summary="bad")
        self.assertEqual(V.parse_review("prefix " + json.dumps(d) + " suffix"), d)

    def test_high_forces_fail(self):
        d = self.good(findings=[{"frame": 1, "issue": "x", "severity": "high"}])
        self.assertEqual(V.parse_review(json.dumps(d))["verdict"], "fail")

    def test_garbage(self):
        bad = {"verdict": "warn", "findings": [], "summary": "could not parse vision review"}
        for t in ("", "no json here", "{broken", json.dumps({"verdict": "maybe", "findings": [], "summary": "s"}),
                  json.dumps(self.good(findings=[{"frame": "a", "issue": "x", "severity": "low"}])),
                  json.dumps(self.good(findings=[{"frame": 1, "issue": "", "severity": "low"}])),
                  json.dumps(self.good(findings=[{"frame": 1, "issue": "x", "severity": "bad"}]))):
            self.assertEqual(V.parse_review(t), bad, t)


if __name__ == "__main__":
    unittest.main()
