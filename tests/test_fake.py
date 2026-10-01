import struct, unittest, zlib
from aistudio.providers import fake as F


def png_ok(b):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    pos, seen = 8, []
    while pos < len(b):
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        typ, data, crc = b[pos + 4:pos + 8], b[pos + 8:pos + 8 + n], struct.unpack(">I", b[pos + 8 + n:pos + 12 + n])[0]
        if zlib.crc32(typ + data) & 0xffffffff != crc:
            return False
        seen.append(typ)
        if typ == b"IDAT":
            zlib.decompress(data)
        pos += 12 + n
    return seen[0] == b"IHDR" and seen[-1] == b"IEND"


class TestFake(unittest.TestCase):
    def test_image(self):
        r = F.FakeImageProvider().generate("hello", ["a.png"])
        self.assertTrue(png_ok(r["bytes"]))
        self.assertEqual((r["cost"], r["model"]), (0.036, "fake/image"))
        self.assertEqual(r["bytes"], F.FakeImageProvider().generate("hello", ["a.png"])["bytes"])
        with self.assertRaises(ValueError):
            F.FakeImageProvider().generate("x", ["1", "2", "3", "4", "5"])

    def test_video(self):
        v = F.FakeVideoProvider()
        r = v.generate("p", 4, audio=True)
        self.assertTrue(r["bytes"].startswith(b"FAKEMP4"))
        self.assertEqual((r["cost"], r["seconds"], r["model"]), (0.2, 4, "fake/video"))
        self.assertEqual(v.generate("p", 6)["cost"], 0.18)
        self.assertEqual(v.generate("p", 8, audio=True)["cost"], 0.4)
        with self.assertRaises(ValueError):
            v.generate("p", 5)
        self.assertEqual(v.generate("please FAIL_ME", 4), {"error": "rejected by fake provider", "cost": 0.0})

    def test_vision(self):
        r = F.FakeVisionProvider().review(["f0.png"])
        self.assertEqual((r["verdict"], r["findings"], r["cost"]), ("pass", [], 0.001))
        r = F.FakeVisionProvider().review(["f0.png"], {"inject": "extra_person"})
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["findings"], [{"frame": 0, "issue": "extra person", "severity": "high"}])

    def test_llm(self):
        r = F.FakeLLM().complete("x" * 100)
        self.assertEqual(r["text"], "FAKE: " + "x" * 40)
        self.assertEqual(r["cost"], 0.0)


if __name__ == "__main__":
    unittest.main()
