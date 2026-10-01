import unittest
from aistudio import gates as G

B = {"approved": True, "stop_loss": 6.0}


class TestGates(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(G.check_run(B, 1.0, 0.2, 0))

    def test_not_approved(self):
        for b in ({"approved": False, "stop_loss": 9}, {}, None):
            with self.assertRaises(G.GateError):
                G.check_run(b, 0, 0.2, 0)

    def test_stop_loss(self):
        self.assertIsNone(G.check_run(B, 5.8, 0.2, 0))
        with self.assertRaises(G.GateError):
            G.check_run(B, 5.9, 0.2, 0)
        self.assertIsNone(G.check_run(B, 5.9, 0.2, 0, override=True))

    def test_attempts(self):
        with self.assertRaises(G.GateError):
            G.check_run(B, 0, 0.2, 3)
        self.assertIsNone(G.check_run(B, 0, 0.2, 2))
        self.assertIsNone(G.check_run(B, 0, 0.2, 3, override=True))

    def test_daily(self):
        with self.assertRaises(G.GateError):
            G.check_run(B, 0, 0.5, 0, today_spent=0.8, daily_limit=1.0)
        self.assertIsNone(G.check_run(B, 0, 0.2, 0, today_spent=0.8, daily_limit=1.0))

    def test_negative(self):
        with self.assertRaises(G.GateError):
            G.check_run(B, 0, -1, 0)

    def test_stop_loss_for(self):
        self.assertEqual(G.stop_loss_for(5.67), 7.37)


if __name__ == "__main__":
    unittest.main()
