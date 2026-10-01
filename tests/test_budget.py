import unittest
from aistudio import budget as B

RATES = {"models": {"google/veo-3.1-lite": {"720p": {"audio": 0.05, "no_audio": 0.03}},
                    "s": {"480p": 0.103, "720p": 0.231}}}
SHOTS = {"audio": False, "final_resolution": "720p", "shots": [
    {"id": "s01", "model": "google/veo-3.1-lite", "seconds": 4, "audio": True},
    {"id": "s02", "model": "google/veo-3.1-lite", "seconds": 4},
    {"id": "s03", "model": "s", "seconds": 4, "resolution": "480p"}]}
IMGS = {"images": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}


class TestBudget(unittest.TestCase):
    def test_basic(self):
        r = B.estimate(SHOTS, IMGS, RATES, existing_images=["a"], failure=0.0)
        self.assertEqual([s["id"] for s in r["per_shot"]], ["s01", "s02", "s03"])
        self.assertEqual([s["cost"] for s in r["per_shot"]], [0.2, 0.12, 0.412])
        self.assertAlmostEqual(r["clips"], 0.732)
        self.assertAlmostEqual(r["stills"], 0.072)
        self.assertEqual(r["estimate"], 0.8)
        self.assertEqual(r["stop_loss"], 1.05)
        self.assertEqual((r["footage_seconds"], r["failure_rate"]), (12, 0.0))

    def test_failure(self):
        r = B.estimate(SHOTS, {"images": []}, RATES, failure=0.5)
        self.assertEqual(r["estimate"], 1.46)
        self.assertEqual(r["stop_loss"], 1.90)

    def test_errors(self):
        for f in (-0.1, 0.9, 1.0):
            with self.assertRaises(ValueError):
                B.estimate(SHOTS, IMGS, RATES, failure=f)
        with self.assertRaises(KeyError):
            B.estimate({"shots": [{"id": "x", "model": "zzz", "seconds": 4}]}, IMGS, RATES)

    def test_default_resolution(self):
        r = B.estimate({"shots": [{"id": "x", "model": "s", "seconds": 2}]}, {"images": []}, RATES)
        self.assertEqual(r["per_shot"][0]["cost"], 0.462)


if __name__ == "__main__":
    unittest.main()
