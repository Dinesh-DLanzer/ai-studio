import unittest
from aistudio import rates as R

RATES = {"models": {
    "a": {"720p": 0.231, "480p": 0.103},
    "veo": {"720p": {"audio": 0.05, "no_audio": 0.03}},
    "tier": {"720p": [{"up_to": 8, "rate": 0.3}, {"up_to": 16, "rate": 0.25}, {"rate": 0.2}]},
}}


class TestRates(unittest.TestCase):
    def test_number(self):
        self.assertEqual(R.rate_for(RATES, "a", "480p"), 0.103)

    def test_audio(self):
        self.assertEqual(R.rate_for(RATES, "veo", "720p", audio=True), 0.05)
        self.assertEqual(R.rate_for(RATES, "veo", "720p", audio=False), 0.03)
        self.assertEqual(R.rate_for(RATES, "veo", "720p"), 0.03)

    def test_tiers(self):
        got = [R.rate_for(RATES, "tier", "720p", s) for s in (4, 8, 9, 16, 17, 30)]
        self.assertEqual(got, [0.3, 0.3, 0.25, 0.25, 0.2, 0.2])

    def test_errors(self):
        with self.assertRaises(KeyError):
            R.rate_for(RATES, "nope", "720p")
        with self.assertRaises(KeyError):
            R.rate_for(RATES, "a", "4k")
        with self.assertRaises(ValueError):
            R.rate_for(RATES, "tier", "720p")
        with self.assertRaises(ValueError):
            R.rate_for({"models": {"t": {"720p": [{"up_to": 4, "rate": 1}]}}}, "t", "720p", 9)

    def test_clip_cost(self):
        self.assertEqual(R.clip_cost(RATES, "veo", "720p", 4, audio=True), 0.2)
        self.assertEqual(R.clip_cost(RATES, "veo", "720p", 4), 0.12)
        self.assertEqual(R.clip_cost(RATES, "a", "720p", 3), 0.693)


if __name__ == "__main__":
    unittest.main()
