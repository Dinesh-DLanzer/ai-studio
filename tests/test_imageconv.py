import shutil, subprocess, tempfile, unittest, base64
from pathlib import Path
from aistudio import imageconv as I

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
HEADERS = {"png": b"\x89PNG\r\n\x1a\n" + b"0" * 9, "jpg": b"\xff\xd8\xff\xe0" + b"0" * 9, "gif": b"GIF89a" + b"0" * 9,
           "bmp": b"BM" + b"0" * 30, "tiff": b"II*\x00" + b"0" * 9, "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ", "heic": b"\x00\x00\x00\x18ftypheic" + b"0" * 9}


class TestImageConv(unittest.TestCase):
    def test_detect_by_content(self):
        for kind, head in HEADERS.items():
            self.assertEqual(I.detect(head), kind)
        for bad in (b"", b"hello world, not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.4 ....", b"MZ\x90\x00 an exe"):
            self.assertIsNone(I.detect(bad))

    def test_png_and_jpeg_pass_through_untouched(self):
        for kind in ("png", "jpg"):
            self.assertEqual(I.normalise(HEADERS[kind]), (HEADERS[kind], kind))

    def test_refuses_bad_input(self):
        for bad in (b"", b"plain text", b"x" * 100, b"<svg/>"):
            with self.assertRaises(I.ImageError):
                I.normalise(bad)
        with self.assertRaises(I.ImageError):
            I.normalise(b"\x89PNG\r\n\x1a\n" + b"0" * (I.MAX_BYTES + 1))

    def test_no_converter_is_a_clear_error(self):
        with self.assertRaises(I.ImageError) as c:
            I.normalise(HEADERS["gif"], which=lambda x: None)        # no sips; Pillow (if present) cannot read this fake GIF either
        self.assertTrue(str(c.exception))

    @unittest.skipUnless(shutil.which("sips"), "needs macOS sips")
    def test_real_conversion_with_sips(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.png").write_bytes(PNG)
        for fmt in ("gif", "bmp", "tiff"):
            subprocess.run(["sips", "-s", "format", fmt, str(d / "a.png"), "--out", str(d / f"a.{fmt}")], capture_output=True)
            out, ext = I.normalise((d / f"a.{fmt}").read_bytes())
            self.assertEqual((ext, I.detect(out)), ("png", "png"), fmt)


if __name__ == "__main__":
    unittest.main()
