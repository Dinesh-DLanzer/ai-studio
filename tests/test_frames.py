import unittest
from aistudio import frames as F


class TestFrames(unittest.TestCase):
    def test_ffmpeg_preferred(self):
        c = F.plan_command("a.mp4", "out", 6, 8, which=lambda x: "/bin/" + x, platform="darwin")
        self.assertEqual(c[0], "ffmpeg")
        self.assertIn("fps=6/8", c)

    def test_swift_fallback(self):
        c = F.plan_command("a.mp4", "out", 6, 8, which=lambda x: "/bin/swift" if x == "swift" else None, platform="darwin")
        self.assertEqual((c[0], c[-1]), ("swift", "6"))

    def test_nothing(self):
        with self.assertRaises(F.FrameError):
            F.plan_command("a.mp4", "out", 6, 8, which=lambda x: None, platform="linux")
        with self.assertRaises(ValueError):
            F.plan_command("a.mp4", "out", 0, 8)


if __name__ == "__main__":
    unittest.main()
