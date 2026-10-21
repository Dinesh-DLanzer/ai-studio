import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aistudio import comments, project, review_package
from aistudio.service import Workspace


def make_tiny_mp4(out_path: Path) -> bool:
    """Generate a tiny 1-second black MP4 with ffmpeg."""
    if not shutil.which("ffmpeg"):
        return False
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path)
    ]
    res = subprocess.run(cmd, capture_output=True)
    return res.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


class TestReviewPackage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = Workspace(self.root)
        self.pname = "review-test"
        self.ws.create_project(self.pname)
        self.pdir = self.ws.pdir(self.pname)

    def test_refuse_when_no_exported_mp4(self):
        # exports/ folder is empty
        with self.assertRaises(ValueError) as cm:
            review_package.export(self.ws, self.pname, out=None)
        self.assertIn("no exported video", str(cm.exception).lower())
        self.assertIn("exports/", str(cm.exception))

    def test_package_export_zip_and_folder(self):
        exports_dir = self.pdir / "exports"
        exports_dir.mkdir(exist_ok=True)
        video_file = exports_dir / f"{self.pname}_20261021.mp4"
        if not make_tiny_mp4(video_file):
            self.skipTest("ffmpeg not available or failed to create test MP4")

        # Create dummy shot and poster frame
        (self.pdir / "stills").mkdir(exist_ok=True)
        (self.pdir / "stills" / "s01.png").write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        shots_doc = {
            "schema_version": 2,
            "shots": [
                {
                    "id": "s01",
                    "seconds": 3,
                    "prompt": "Secret AI prompt that should be hidden",
                    "note": "Establishing shot",
                    "first_frame": "stills/s01.png"
                }
            ]
        }
        project.save_json(self.pdir, "shots.json", shots_doc)

        # Add open and resolved comments
        comments.add_comment(self.pdir, "edit", "Fix audio balance", "Director", time=1.2, cid="c_open1")
        c_res = comments.add_comment(self.pdir, "shot:s01", "Old resolved issue", "Editor", time=2.0, cid="c_res1")
        comments.resolve_comment(self.pdir, c_res["id"])

        # 1. Export as folder with prompts hidden
        folder_out = Path(tempfile.mkdtemp()) / "package_dir"
        res_dir = review_package.export(self.ws, self.pname, out=folder_out, include_prompts=False)
        self.assertEqual(res_dir, folder_out)
        self.assertTrue((folder_out / "index.html").is_file())
        self.assertTrue((folder_out / "video.mp4").is_file())
        self.assertTrue((folder_out / "frames" / "s01.png").is_file())

        html_text = (folder_out / "index.html").read_text(encoding="utf-8")

        # Verify CSP
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self' blob:; img-src 'self' data:;"
        self.assertIn(csp, html_text)

        # Verify no http:// or https://
        self.assertNotIn("http://", html_text)
        self.assertNotIn("https://", html_text)

        # Verify prompt is HIDDEN
        self.assertNotIn("Secret AI prompt", html_text)

        # Verify existing open comment is displayed and resolved is not
        self.assertIn("Fix audio balance", html_text)
        self.assertNotIn("Old resolved issue", html_text)

        # Verify Download feedback mechanism is present in JS
        self.assertIn("feedback.json", html_text)
        self.assertIn("Blob", html_text)

        # 2. Export with include_prompts=True
        folder_out_prompts = Path(tempfile.mkdtemp()) / "package_prompts"
        review_package.export(self.ws, self.pname, out=folder_out_prompts, include_prompts=True)
        html_prompts = (folder_out_prompts / "index.html").read_text(encoding="utf-8")
        self.assertIn("Secret AI prompt", html_prompts)

        # 3. Export as Zip
        zip_out = Path(tempfile.mkdtemp()) / "package.zip"
        res_zip = review_package.export(self.ws, self.pname, out=zip_out)
        self.assertEqual(res_zip, zip_out)
        self.assertTrue(zip_out.is_file() and zip_out.stat().st_size > 0)

    def test_xss_escaping_inert(self):
        exports_dir = self.pdir / "exports"
        exports_dir.mkdir(exist_ok=True)
        video_file = exports_dir / f"{self.pname}_xss.mp4"
        if not make_tiny_mp4(video_file):
            self.skipTest("ffmpeg not available or failed to create test MP4")

        xss_script = "<script>alert('xss')</script>"
        xss_img = '<img src=x onerror="alert(1)">'

        shots_doc = {
            "schema_version": 2,
            "shots": [
                {
                    "id": "s01",
                    "seconds": 2,
                    "prompt": xss_script,
                    "note": xss_img,
                }
            ]
        }
        project.save_json(self.pdir, "shots.json", shots_doc)

        comments.add_comment(self.pdir, "edit", xss_script, f"Author{xss_img}", time=0.0)

        folder_out = Path(tempfile.mkdtemp()) / "xss_test"
        review_package.export(self.ws, self.pname, out=folder_out, include_prompts=True)
        html_text = (folder_out / "index.html").read_text(encoding="utf-8")

        # Assert no raw unescaped script tag from data
        # Only the application's own inline <script> should exist
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html_text, re.DOTALL | re.IGNORECASE)
        for s in scripts:
            self.assertNotIn("alert('xss')", s)
            self.assertNotIn("alert(1)", s)

        self.assertNotIn(xss_script, html_text)
        self.assertNotIn(xss_img, html_text)

        # The escaped versions should exist
        self.assertIn(html.escape(xss_script, quote=True), html_text)

    def test_cli_review_export_and_import(self):
        from aistudio import cli

        exports_dir = self.pdir / "exports"
        exports_dir.mkdir(exist_ok=True)
        video_file = exports_dir / f"{self.pname}_cli.mp4"
        if not make_tiny_mp4(video_file):
            self.skipTest("ffmpeg not available or failed to create test MP4")

        # Set AISTUDIO_HOME to test root
        old_home = os.environ.get("AISTUDIO_HOME")
        os.environ["AISTUDIO_HOME"] = str(self.root)
        try:
            out_zip = self.root / "cli_pkg.zip"
            lines = []
            rc = cli.main(["review", "export", self.pname, "--out", str(out_zip), "--json"], out=lines.append)
            self.assertEqual(rc, 0)
            self.assertTrue(out_zip.is_file())
            self.assertIn(str(out_zip), "".join(lines))

            # Test review import CLI
            fb_file = self.root / "feedback.json"
            fb_file.write_text(json.dumps({
                "comments": [{"target": "edit", "text": "CLI feedback", "author": "Reviewer via CLI"}]
            }), encoding="utf-8")

            import_lines = []
            rc_imp = cli.main(["review", "import", self.pname, str(fb_file), "--json"], out=import_lines.append)
            self.assertEqual(rc_imp, 0)
            res = json.loads("".join(import_lines))
            self.assertEqual(res["imported"], 1)

            c_list = comments.list_comments(self.pdir)
            self.assertTrue(any(c["author"] == "Reviewer via CLI" for c in c_list))
        finally:
            if old_home is not None:
                os.environ["AISTUDIO_HOME"] = old_home
            else:
                os.environ.pop("AISTUDIO_HOME", None)


if __name__ == "__main__":
    unittest.main()
