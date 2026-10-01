import json, tempfile, unittest
from pathlib import Path
from aistudio import costlog as C


def row(shot, stage="final", attempt="1", cost="0.2"):
    return {"shot": shot, "stage": stage, "attempt": attempt, "cost": cost, "model": "m", "result": "completed"}


class TestCostlog(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp())

    def test_empty(self):
        self.assertEqual(C.read_log(self.p), [])
        self.assertEqual(C.spent(self.p), 0.0)

    def test_append_read_spent(self):
        C.append_log(self.p, row("s01"))
        C.append_log(self.p, row("s02", cost="0.12"))
        C.append_log(self.p, row("s03", cost=""))
        rows = C.read_log(self.p)
        self.assertEqual([r["shot"] for r in rows], ["s01", "s02", "s03"])
        self.assertEqual(list(rows[0].keys()), C.LOG_COLS)
        self.assertEqual(rows[0]["job_id"], "")
        self.assertAlmostEqual(C.spent(self.p), 0.32)
        self.assertEqual((self.p / "cost_log.csv").read_text().splitlines()[0], ",".join(C.LOG_COLS))

    def test_extra_key(self):
        with self.assertRaises(KeyError):
            C.append_log(self.p, dict(row("s01"), bogus=1))

    def test_split(self):
        C.append_log(self.p, row("s01"))
        C.append_log(self.p, row("s01", attempt="2", cost="0.3"))
        C.append_log(self.p, row("d01", stage="image", cost="0.036"))
        C.append_log(self.p, row("d02", stage="image", cost="0.04"))
        (self.p / "discarded.json").write_text(json.dumps([
            {"file": "clips/_discarded/s01_final_a1.mp4", "cost": 0.2, "reason": "x"},
            {"file": "stills/_discarded/d01.png", "cost": 0.036, "reason": "y"}]))
        r = C.split(self.p)
        self.assertAlmostEqual(r["discarded"], 0.236)
        self.assertAlmostEqual(r["used"], 0.34)
        self.assertAlmostEqual(r["total"], 0.576)

    def test_split_no_discard_file(self):
        C.append_log(self.p, row("s01"))
        self.assertEqual(C.split(self.p), {"used": 0.2, "discarded": 0.0, "total": 0.2})


if __name__ == "__main__":
    unittest.main()
