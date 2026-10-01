import os
import tests._hermetic  # noqa: F401
import json, shutil, subprocess, tempfile, time, unittest, zipfile
from pathlib import Path
from aistudio import editor, trash
from aistudio.service import ServiceError, Workspace

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:
    HAVE_API = False
FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
try:
    import PIL  # noqa: F401
    PILOK = True
except ImportError:
    PILOK = False
H = {"x-aistudio-token": "tok"}


def make_clip(path, secs=2.0, color="red", audio=True):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24:d={secs}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)


def vid(i, src="clips/a.mp4", a=0, b=2, tr="cut", dur=0.5):
    return {"id": i, "src": src, "in": a, "out": b, "volume": 1, "transition": {"type": tr, "dur": dur}}


class TestClean(unittest.TestCase):
    def test_defaults_and_ranges(self):
        d = editor.clean({"tracks": {"video": [vid("v1")], "text": [{"id": "t1", "text": "Hi", "start": 0, "end": 2}]}})
        t = d["tracks"]["text"][0]
        self.assertEqual((d["aspect"], d["fps"], t["font"], t["align"], t["bold"]), ("9:16", 24, "Poppins", "center", True))
        self.assertFalse(t["shadow"]["on"])

    def test_bad_inputs(self):
        bad = [
            {"aspect": "4:3"}, {"fps": 60}, {"tracks": {"video": [vid("v1", src="../x.mp4")]}}, {"tracks": {"video": [vid("v1", src="/etc/x.mp4")]}},
            {"tracks": {"video": [vid("v1", src="clips/_discarded/a.mp4")]}}, {"tracks": {"video": [vid("v1", src="stills/a.png")]}},
            {"tracks": {"video": [vid("v1", a=2, b=2.1)]}}, {"tracks": {"video": [vid("v1"), vid("v1")]}},
            {"tracks": {"video": [vid("v1", tr="spin")]}}, {"tracks": {"video": [vid("v1", tr="wipeleft")]}}, {"tracks": {"text": [{"id": "t", "text": "x" * 101, "start": 0, "end": 2}]}},
            {"tracks": {"text": [{"id": "t", "text": "x", "start": 3, "end": 2}]}}, {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "color": "red"}]}},
            {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "font": "Comic"}]}}, {"tracks": {"text": [{"id": "t", "text": "x", "start": 0, "end": 2, "x": 2}]}},
            {"tracks": {"audio": [{"id": "a", "src": "clips/a.mp4", "in": 0, "out": 2}]}}, {"tracks": {"text": [{"id": "t", "text": "  ", "start": 0, "end": 2}]}},
            {"tracks": {"video": [dict(vid("v1"), volume=True)]}}, {"tracks": {"video": [dict(vid("v1"), **{"in": float("nan")})]}},
        ]
        for doc in bad:
            with self.assertRaises(editor.EditError, msg=str(doc)[:80]):
                editor.clean(doc)

    def test_timeline_length_overlaps_transitions(self):
        v = editor.clean({"tracks": {"video": [vid("a", b=4), vid("b", b=4, tr="crossfade", dur=1), vid("c", b=4)]}})["tracks"]["video"]
        self.assertAlmostEqual(editor.timeline_length(v), 11.0)
        v = editor.clean({"tracks": {"video": [vid("a", b=1), vid("b", b=1, tr="fade", dur=2)]}})["tracks"]["video"]
        self.assertAlmostEqual(editor.timeline_length(v), 2 - 0.95)       # clamped so it never exceeds either clip


class TestPlan(unittest.TestCase):
    def build(self, doc, pngs=None, audio_in=True):
        e = editor.clean(doc)
        files = {i["src"]: Path("/p") / i["src"] for i in e["tracks"]["video"] + e["tracks"]["audio"]}
        probes = {i["src"]: {"duration": 99, "audio": audio_in} for i in e["tracks"]["video"]}
        return editor.plan(e, files, probes, pngs or {})

    def test_cut_xfade_text_music(self):
        doc = {"aspect": "16:9", "tracks": {"video": [vid("a", b=3), vid("b", "clips/b.mp4", b=3, tr="crossfade", dur=1), vid("c", "clips/c.mp4", b=2)],
                "text": [{"id": "t1", "text": "Hi", "start": 1, "end": 4}], "audio": [{"id": "m", "src": "audio/m.mp3", "in": 0, "out": 8, "start": 1, "fadeIn": 1, "fadeOut": 2, "volume": 0.5}]}}
        pl = self.build(doc, {"t1": (Path("/tmp/t1.png"), 200, 100)})
        fc = pl["args"][pl["args"].index("-filter_complex") + 1]
        self.assertAlmostEqual(pl["total"], 7.0)
        for needle in ("scale=1280:720", "xfade=transition=fade:duration=1.000:offset=2.000", "acrossfade=d=1.000", "concat=n=2:v=1:a=0",
                       "overlay=x=540:y=382:enable='between(t,1.000,4.000)'", "afade=t=in", "afade=t=out:st=6.000:d=2.000", "adelay=1000|1000",
                       "amix=inputs=2", "[vout]", "[aout]"):
            self.assertIn(needle, fc)
        self.assertEqual(pl["args"].count("-i"), 5)

    def test_silent_clip_gets_silence(self):
        pl = self.build({"tracks": {"video": [vid("a")]}}, audio_in=False)
        self.assertIn("anullsrc", pl["args"][pl["args"].index("-filter_complex") + 1])

    def test_empty_refused(self):
        with self.assertRaises(editor.EditError):
            self.build({"tracks": {}})


@unittest.skipUnless(PILOK, "needs Pillow")
class TestTextPng(unittest.TestCase):
    def test_png_renders_with_bubble_shadow(self):
        from PIL import Image
        t = editor.clean({"tracks": {"text": [{"id": "t", "text": "Turn Ideas into\nStunning Videos", "start": 0, "end": 2, "bg": "#9b30ff", "underline": True,
                                              "shadow": {"on": True, "blur": 20}, "opacity": 0.8, "caps": True, "align": "left"}]}})["tracks"]["text"][0]
        f = Path(tempfile.mkdtemp()) / "t.png"
        w, h = editor.render_text_png(t, 720, f)
        im = Image.open(f)
        self.assertEqual(im.size, (w, h))
        self.assertTrue(im.getchannel("A").getextrema()[1] > 0)
        self.assertLess(im.getchannel("A").getextrema()[1], 256)


@unittest.skipUnless(FF and PILOK, "needs ffmpeg + Pillow")
class TestRender(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        self.p = self.ws.pdir("demo")
        (self.p / "clips").mkdir(exist_ok=True)
        make_clip(self.p / "clips" / "s01_final_a1.mp4", 2, "red")
        make_clip(self.p / "clips" / "s02_final_a1.mp4", 2, "blue", audio=False)
        self.ws.put_shots("demo", {"aspect_ratio": "9:16", "audio": False, "shots": [
            {"id": "s01", "model": "m", "seconds": 4, "prompt": "p"}, {"id": "s02", "model": "m", "seconds": 4, "prompt": "p"}]})

    def probe(self, rel):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(self.p / rel)], capture_output=True, text=True)
        return json.loads(r.stdout)

    def test_default_edit_uses_real_durations(self):
        g = self.ws.edit_get("demo")
        v = g["edit"]["tracks"]["video"]
        self.assertEqual([x["src"] for x in v], ["clips/s01_final_a1.mp4", "clips/s02_final_a1.mp4"])
        self.assertAlmostEqual(v[0]["out"], 2.0, delta=0.1)
        self.assertFalse(g["saved"])

    def test_export_with_transition_text_music(self):
        mus = self.p / "audio"
        mus.mkdir()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=5", str(mus / "bg.mp3")], check=True)
        doc = self.ws.edit_get("demo")["edit"]
        doc["tracks"]["video"][1]["transition"] = {"type": "crossfade", "dur": 0.5}
        doc["tracks"]["text"] = [{"id": "t1", "text": "Hello\nWorld", "start": 0.5, "end": 3, "bg": "#9b30ff", "shadow": {"on": True, "blur": 10}}]
        doc["tracks"]["audio"] = [{"id": "m1", "src": "audio/bg.mp3", "in": 0, "out": 4, "volume": 0.5, "fadeIn": 0.5, "fadeOut": 0.5}]
        self.ws.edit_put("demo", doc)
        seen = []
        res = self.ws.edit_export("demo", seen.append)
        info = self.probe(res["file"])
        self.assertAlmostEqual(float(info["format"]["duration"]), 3.5, delta=0.15)
        kinds = {s["codec_type"] for s in info["streams"]}
        self.assertEqual(kinds, {"video", "audio"})
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((vs["width"], vs["height"]), (720, 1280))
        self.assertTrue(seen and seen[-1] == 100.0)
        # the text frame differs from the same frame of an export without text
        doc["tracks"]["text"] = []
        self.ws.edit_put("demo", doc)
        time.sleep(1.1)
        plain = self.ws.edit_export("demo")["file"]
        fa, fb = self.p / "a.png", self.p / "b.png"
        for rel, out in ((res["file"], fa), (plain, fb)):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(self.p / rel), "-frames:v", "1", str(out)], check=True)
        self.assertNotEqual(fa.read_bytes(), fb.read_bytes())
        self.assertEqual(len(self.ws.exports("demo")), 2)

    def test_every_transition_renders(self):
        """All transition ids map to a real xfade name: one render chains every one of them."""
        ids = [t for t in editor.TRANSITIONS if t != "cut"]
        doc = {"aspect": "1:1", "tracks": {"video": [vid("c0", "clips/s01_final_a1.mp4", 0, 1)] + [vid(f"c{i + 1}", "clips/s0%d_final_a1.mp4" % (1 + (i + 1) % 2), 0, 1, tr=t, dur=0.2) for i, t in enumerate(ids)]}}
        self.ws.edit_put("demo", doc)
        res = self.ws.edit_export("demo")
        d = float(self.probe(res["file"])["format"]["duration"])
        self.assertAlmostEqual(d, 1 + len(ids) * 0.8, delta=0.3)

    def test_missing_clip_and_overlong_clip_refused(self):
        doc = self.ws.edit_get("demo")["edit"]
        doc["tracks"]["video"][0]["out"] = 30
        self.ws.edit_put("demo", doc)
        with self.assertRaises(ServiceError) as cm:
            self.ws.edit_export("demo")
        self.assertIn("only", str(cm.exception))
        (self.p / "clips" / "s02_final_a1.mp4").unlink()
        self.assertEqual(self.ws.edit_get("demo")["missing"], ["s02"])


class TestEditService(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")

    def test_put_get_roundtrip_and_bad(self):
        with self.assertRaises(ServiceError):
            self.ws.edit_put("demo", {"aspect": "4:3"})
        d = self.ws.edit_put("demo", {"aspect": "1:1", "tracks": {"video": [vid("a")]}})
        self.assertTrue(self.ws.edit_get("demo")["saved"])
        self.assertEqual(self.ws.edit_get("demo")["edit"], d)

    def test_corrupt_edit_json_falls_back(self):
        (self.ws.pdir("demo") / "edit.json").write_text("{\"aspect\": \"9:99\"}")
        g = self.ws.edit_get("demo")
        self.assertIn("could not be used", g["warning"])

    def test_audio_upload_rules(self):
        with self.assertRaises(ServiceError):
            self.ws.add_audio("demo", "evil.exe", b"x")
        r = self.ws.add_audio("demo", "My Song!.mp3", b"not audio") if not shutil.which("ffprobe") else None
        if r:
            self.assertEqual(r["src"], "audio/My_Song.mp3")
        else:
            with self.assertRaises(ServiceError):
                self.ws.add_audio("demo", "My Song!.mp3", b"not audio")
            self.assertTrue((self.ws.pdir("demo") / "audio" / "My_Song.mp3.rejected").exists())


class TestTrash(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())
        self.ws.create_project("demo")
        p = self.ws.pdir("demo")
        (p / "clips" / "_discarded").mkdir(parents=True)
        (p / "clips" / "a.mp4").write_bytes(b"a")
        (p / "clips" / "_discarded" / "old.mp4").write_bytes(b"old")

    def test_delete_needs_exact_name_and_moves(self):
        with self.assertRaises(ServiceError):
            self.ws.delete_project("demo", "dem")
        self.assertTrue(self.ws.pdir("demo").exists())
        tid = self.ws.delete_project("demo", "demo")["trash"]
        self.assertEqual([x["name"] for x in self.ws.list_projects()], [])
        item = self.ws.trash_list()[0]
        self.assertEqual((item["id"], item["name"]), (tid, "demo"))
        self.assertTrue((Path(self.ws.root) / "_trash" / tid / "clips" / "a.mp4").exists())      # nothing was erased

    def test_restore_and_conflict(self):
        tid = self.ws.delete_project("demo", "demo")["trash"]
        self.ws.create_project("demo")
        with self.assertRaises(ServiceError):
            self.ws.trash_restore(tid)
        self.assertEqual(self.ws.trash_restore(tid, "demo2")["name"], "demo2")
        self.assertTrue((self.ws.pdir("demo2") / "clips" / "a.mp4").exists())
        for bad in ("../x", "nope", ""):
            with self.assertRaises(ServiceError):
                self.ws.trash_restore(bad)

    def test_same_second_twice_keeps_both(self):
        a = trash.move_to_trash(self.ws.root, "demo")
        self.ws.create_project("demo")
        b = trash.move_to_trash(self.ws.root, "demo")
        self.assertNotEqual(a, b)
        self.assertEqual(len(self.ws.trash_list()), 2)

    def test_zip(self):
        p = self.ws.pdir("demo")
        if os.name == "nt":
            self.skipTest("symlinks need privileges on Windows")
        (p / "link").symlink_to(p / "clips" / "a.mp4")
        z = self.ws.export_project("demo")
        names = zipfile.ZipFile(z).namelist()
        z.unlink()
        self.assertIn("demo/clips/a.mp4", names)
        self.assertIn("demo/Story.md", names)
        self.assertNotIn("demo/clips/_discarded/old.mp4", names)
        self.assertNotIn("demo/link", names)
        z = self.ws.export_project("demo", True)
        self.assertIn("demo/clips/_discarded/old.mp4", zipfile.ZipFile(z).namelist())
        z.unlink()


@unittest.skipUnless(HAVE_API, "needs the venv with fastapi + httpx")
class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.call("post", "/api/projects", json={"name": "demo"})

    def call(self, m, url, **kw):
        return self.c.request(m.upper(), url, headers=H, **kw)

    def test_auth_required_everywhere(self):
        for m, u in (("get", "/api/projects/demo/edit"), ("put", "/api/projects/demo/edit"), ("post", "/api/projects/demo/edit/export"),
                     ("get", "/api/projects/demo/export-project"), ("delete", "/api/projects/demo"), ("get", "/api/trash"),
                     ("post", "/api/projects/demo/audio?filename=a.mp3")):
            self.assertEqual(getattr(self.c, m)(u).status_code, 401, u)

    def test_edit_roundtrip_and_errors(self):
        self.assertEqual(self.call("put", "/api/projects/demo/edit", json={"aspect": "7:7"}).status_code, 400)
        r = self.call("put", "/api/projects/demo/edit", json={"tracks": {"video": [vid("a")]}})
        self.assertEqual(r.status_code, 200)
        g = self.call("get", "/api/projects/demo/edit").json()
        self.assertTrue(g["saved"])
        self.assertEqual(g["missing"], ["a"])
        self.assertEqual(self.call("get", "/api/projects/nope/edit").status_code, 400)

    def test_fonts_public_and_whitelisted(self):
        self.assertTrue(self.c.get("/api/fonts").json()["fonts"])
        self.assertEqual(self.c.get("/api/fonts/Poppins-Bold.ttf").status_code, 200)
        self.assertEqual(self.c.get("/api/fonts/..%2Fsecret.txt").status_code, 404)
        self.assertEqual(self.c.get("/api/fonts/OFL.txt").status_code, 404)

    def test_delete_flow_and_zip_download(self):
        z = self.call("get", "/api/projects/demo/export-project")
        self.assertEqual(z.status_code, 200)
        self.assertIn("demo.zip", z.headers["content-disposition"])
        self.assertEqual(self.call("delete", "/api/projects/demo", json={"confirm": "x"}).status_code, 400)
        self.assertEqual(self.call("delete", "/api/projects/demo").status_code, 400)
        tid = self.call("delete", "/api/projects/demo", json={"confirm": "demo"}).json()["trash"]
        self.assertEqual(self.call("get", "/api/projects").json()["projects"], [])
        self.assertEqual(self.call("get", "/api/trash").json()["items"][0]["id"], tid)
        self.assertEqual(self.call("post", f"/api/trash/{tid}/restore").json(), {"name": "demo"})
        self.assertEqual(len(self.call("get", "/api/projects").json()["projects"]), 1)

    @unittest.skipUnless(FF and PILOK, "needs ffmpeg + Pillow")
    def test_export_job(self):
        p = Path(self.root) / "projects" / "demo"
        (p / "clips").mkdir(exist_ok=True)
        make_clip(p / "clips" / "a.mp4", 1.5)
        self.call("put", "/api/projects/demo/edit", json={"tracks": {"video": [vid("a", b=1.5)]}})
        j = self.call("post", "/api/projects/demo/edit/export").json()["job"]
        for _ in range(200):
            r = self.call("get", f"/api/jobs/{j}").json()
            if r["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(r["status"], "done", r)
        f = self.call("get", f"/files/demo/{r['result']['file']}")
        self.assertEqual(f.status_code, 200)
        self.assertGreater(len(f.content), 1000)


if __name__ == "__main__":
    unittest.main()
