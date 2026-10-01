"""Review & Export: the edit list (edit.json) and the ffmpeg renderer.  No paid call happens here.

edit.json (one per project) = {"version": 1, "aspect": "9:16", "fps": 24, "tracks": {"video": [...], "text": [...], "audio": [...]}}
  video item: {id, src "clips/..", in, out, volume, transition {type, dur}}   (the transition is the one INTO this clip from the previous one)
  text item : {id, text (<=100 chars), start, end, x, y (centre, 0..1), font, weight, size, color, bg|null, align, bold, italic, underline, caps,
               opacity, shadow {on, color, blur}}
  audio item: {id, src "audio/..", start, in, out, volume, fadeIn, fadeOut}

Text is drawn to a transparent PNG with Pillow and laid over the video with ffmpeg's `overlay` (no libfreetype / drawtext needed, and the
bubble, blur shadow and underline look like the preview).  Paths are checked like discard.py: relative, no '..', never inside _discarded.
Standard library + Pillow (only to render text) + the ffmpeg / ffprobe programs.
"""
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FONT_DIR = REPO / "assets" / "fonts"

ASPECTS = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}
FPS_OK = (24, 25, 30)
# editor id -> ffmpeg xfade name.  "crossfade" / "fade" / "wipe" keep their old meaning so saved edits still work.
# Names checked against `ffmpeg -h filter=xfade` (ffmpeg 9) and the xfade docs.
TRANSITIONS = {
    "cut": None,
    # dissolves and fades
    "crossfade": "fade", "dissolve": "dissolve", "fade": "fadeblack", "fadewhite": "fadewhite", "fadegrays": "fadegrays", "fadefast": "fadefast", "fadeslow": "fadeslow",
    # wipes
    "wipe": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup", "wipedown": "wipedown", "wipetl": "wipetl",
    # slides and pushes
    "slideleft": "slideleft", "slideright": "slideright", "slideup": "slideup", "slidedown": "slidedown", "smoothleft": "smoothleft", "smoothright": "smoothright",
    # cover and reveal
    "coverleft": "coverleft", "coverright": "coverright", "revealleft": "revealleft", "revealright": "revealright",
    # shapes
    "circleopen": "circleopen", "circleclose": "circleclose", "radial": "radial", "vertopen": "vertopen", "horzopen": "horzopen", "diagtl": "diagtl",
    # effects
    "pixelize": "pixelize", "zoomin": "zoomin", "hblur": "hblur", "squeezeh": "squeezeh", "hlslice": "hlslice", "vuslice": "vuslice", "hlwind": "hlwind", "distance": "distance",
}
ALIGNS = ("left", "center", "right", "justify")
AUDIO_SUFFIX = (".mp3", ".wav", ".m4a", ".aac", ".ogg")
VIDEO_SUFFIX = (".mp4", ".mov", ".m4v", ".webm")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CLIPS, MAX_TEXTS, MAX_AUDIO, MAX_TEXT_CHARS = 100, 200, 20, 100

# family -> {weight: file}, italic files exist for 400 and 700 of Poppins only (other weights show a synthetic slant in the preview only)
FONTS = {
    "Poppins": {"weights": {400: "Poppins-Regular.ttf", 500: "Poppins-Medium.ttf", 600: "Poppins-SemiBold.ttf", 700: "Poppins-Bold.ttf", 800: "Poppins-ExtraBold.ttf"},
                "italic": {400: "Poppins-Italic.ttf", 700: "Poppins-BoldItalic.ttf"}},
    "Anton": {"weights": {400: "Anton-Regular.ttf"}, "italic": {}},
    "Bebas Neue": {"weights": {400: "BebasNeue-Regular.ttf"}, "italic": {}},
    "Pacifico": {"weights": {400: "Pacifico-Regular.ttf"}, "italic": {}},
}
WEIGHT_NAMES = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold"}


class EditError(ValueError):
    """Bad edit list, missing tool or failed render (message is safe to show the user)."""


def fonts_info():
    return [{"family": f, "weights": [{"weight": w, "name": WEIGHT_NAMES[w], "file": fn} for w, fn in v["weights"].items()],
             "italic": [{"weight": w, "file": fn} for w, fn in v["italic"].items()]} for f, v in FONTS.items()]


def font_file(family, weight, italic):
    fam = FONTS[family]
    if italic and weight in fam["italic"]:
        return FONT_DIR / fam["italic"][weight]
    return FONT_DIR / fam["weights"][weight]


def tools():
    return {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe"))}


# ---------------------------------------------------------------- validation (pure)
def safe_rel(rel, folder, suffixes):
    """Project-relative path 'folder/name.ext' with no '..', not absolute, not inside _discarded.  Returns the posix string."""
    if not isinstance(rel, str) or not rel:
        raise EditError("a clip or sound has no file")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or "\\" in rel:
        raise EditError(f"invalid path: {rel}")
    if "_discarded" in p.parts:
        raise EditError(f"{rel} is in Discarded; restore it first")
    if p.parts[0] != folder or len(p.parts) != 2 or p.suffix.lower() not in suffixes:
        raise EditError(f"{rel} must be {folder}/<file>{'|'.join(suffixes)}")
    return p.as_posix()


def _num(d, key, lo, hi, default, what):
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < lo or v > hi:
        raise EditError(f"{what}: {key} must be a number from {lo} to {hi}")
    return float(v)


def _id(d, seen, what):
    i = d.get("id")
    if not isinstance(i, str) or not ID_RE.match(i):
        raise EditError(f"{what}: invalid id {i!r}")
    if i in seen:
        raise EditError(f"{what}: duplicate id {i}")
    seen.add(i)
    return i


def _color(v, what, allow_none=False):
    if v is None and allow_none:
        return None
    if not isinstance(v, str) or not HEX_RE.match(v):
        raise EditError(f"{what} must look like #aabbcc")
    return v.lower()


def clean(doc):
    """Validate and normalise an edit list (fills defaults).  Raises EditError with the first problem."""
    if not isinstance(doc, dict):
        raise EditError("edit must be an object")
    aspect = doc.get("aspect", "9:16")
    if aspect not in ASPECTS:
        raise EditError(f"aspect must be one of {', '.join(ASPECTS)}")
    fps = doc.get("fps", 24)
    if fps not in FPS_OK:
        raise EditError("fps must be 24, 25 or 30")
    tracks = doc.get("tracks") or {}
    if not isinstance(tracks, dict):
        raise EditError("tracks must be an object")
    out = {"version": 1, "aspect": aspect, "fps": fps, "tracks": {"video": [], "text": [], "audio": []}}

    vid, seen = tracks.get("video") or [], set()
    if not isinstance(vid, list) or len(vid) > MAX_CLIPS:
        raise EditError(f"video must be a list of at most {MAX_CLIPS} clips")
    for n, c in enumerate(vid):
        w = f"clip {n + 1}"
        if not isinstance(c, dict):
            raise EditError(f"{w} must be an object")
        i, a, b = _id(c, seen, w), _num(c, "in", 0, 36000, 0, w), _num(c, "out", 0, 36000, 0, w)
        if b - a < 0.2:
            raise EditError(f"{w}: out must be at least 0.2 s after in")
        tr = c.get("transition") or {"type": "cut", "dur": 0.5}
        if not isinstance(tr, dict) or tr.get("type", "cut") not in TRANSITIONS:
            raise EditError(f"{w}: transition type must be one of {', '.join(TRANSITIONS)}")
        item = {"id": i, "src": safe_rel(c.get("src"), "clips", VIDEO_SUFFIX), "in": a, "out": b, "volume": _num(c, "volume", 0, 2, 1, w),
                "transition": {"type": tr.get("type", "cut"), "dur": _num(tr, "dur", 0.1, 2, 0.5, w + " transition")}}
        out["tracks"]["video"].append(item)

    txt, seen = tracks.get("text") or [], set()
    if not isinstance(txt, list) or len(txt) > MAX_TEXTS:
        raise EditError(f"text must be a list of at most {MAX_TEXTS} items")
    for n, t in enumerate(txt):
        w = f"text {n + 1}"
        if not isinstance(t, dict):
            raise EditError(f"{w} must be an object")
        i = _id(t, seen, w)
        text = t.get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise EditError(f"{w}: text must be 1 to {MAX_TEXT_CHARS} characters")
        s, e = _num(t, "start", 0, 36000, 0, w), _num(t, "end", 0, 36000, 0, w)
        if e - s < 0.2:
            raise EditError(f"{w}: end must be at least 0.2 s after start")
        family = t.get("font", "Poppins")
        if family not in FONTS:
            raise EditError(f"{w}: font must be one of {', '.join(FONTS)}")
        weight = t.get("weight", 700 if 700 in FONTS[family]["weights"] else 400)
        if weight not in FONTS[family]["weights"]:
            weight = 400 if 400 in FONTS[family]["weights"] else next(iter(FONTS[family]["weights"]))
        al = t.get("align", "center")
        if al not in ALIGNS:
            raise EditError(f"{w}: align must be one of {', '.join(ALIGNS)}")
        sh = t.get("shadow") or {}
        if not isinstance(sh, dict):
            raise EditError(f"{w}: shadow must be an object")
        flag = lambda k, d=False: bool(t.get(k, d))
        out["tracks"]["text"].append({
            "id": i, "text": text, "start": s, "end": e, "x": _num(t, "x", 0, 1, 0.5, w), "y": _num(t, "y", 0, 1, 0.6, w),
            "font": family, "weight": weight, "size": _num(t, "size", 8, 300, 56, w), "color": _color(t.get("color", "#ffffff"), w + " color"),
            "bg": _color(t.get("bg"), w + " background", True), "align": al, "bold": flag("bold", weight >= 600), "italic": flag("italic"),
            "underline": flag("underline"), "caps": flag("caps"), "opacity": _num(t, "opacity", 0, 1, 1, w),
            "shadow": {"on": bool(sh.get("on", False)), "color": _color(sh.get("color", "#000000"), w + " shadow colour"), "blur": _num(sh, "blur", 0, 100, 20, w + " shadow")}})

    aud, seen = tracks.get("audio") or [], set()
    if not isinstance(aud, list) or len(aud) > MAX_AUDIO:
        raise EditError(f"audio must be a list of at most {MAX_AUDIO} sounds")
    for n, a in enumerate(aud):
        w = f"sound {n + 1}"
        if not isinstance(a, dict):
            raise EditError(f"{w} must be an object")
        i, lo, hi = _id(a, seen, w), _num(a, "in", 0, 36000, 0, w), _num(a, "out", 0, 36000, 0, w)
        if hi - lo < 0.2:
            raise EditError(f"{w}: out must be at least 0.2 s after in")
        out["tracks"]["audio"].append({"id": i, "src": safe_rel(a.get("src"), "audio", AUDIO_SUFFIX), "start": _num(a, "start", 0, 36000, 0, w), "in": lo, "out": hi,
                                       "volume": _num(a, "volume", 0, 2, 0.6, w), "fadeIn": _num(a, "fadeIn", 0, 30, 0, w), "fadeOut": _num(a, "fadeOut", 0, 30, 0, w),
                                       "name": str(a.get("name") or Path(a["src"]).stem)[:60]})
    return out


def timeline_length(video):
    """Length of the joined video track in seconds (transitions overlap the clips)."""
    total = 0.0
    for n, c in enumerate(video):
        d = c["out"] - c["in"]
        total += d if n == 0 else d - _td(c, total, d)
    return total


def _td(clip, cur_len, d):
    """Transition length actually used into this clip (0 = hard cut): never longer than either side."""
    tr = clip["transition"]
    if TRANSITIONS[tr["type"]] is None:
        return 0.0
    td = min(tr["dur"], cur_len - 0.05, d - 0.05)
    return td if td >= 0.1 else 0.0


# ---------------------------------------------------------------- defaults
def probe(path):
    """{'duration', 'audio'} from ffprobe, or None when ffprobe is missing or the file is unreadable."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout or "{}")
        return {"duration": float(j["format"]["duration"]), "audio": any(s.get("codec_type") == "audio" for s in j.get("streams", []))}
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None


def clip_for_shot(pdir, shot):
    """Best clip file for a shot: its approved final clip, else the newest clips/<id>_final_a*.mp4.  None if there is none."""
    fc = shot.get("final_clip")
    if fc and (Path(pdir) / fc).is_file() and "_discarded" not in Path(fc).parts:
        return fc
    found = sorted((Path(pdir) / "clips").glob(f"{shot['id']}_final_a*.mp4"), key=lambda f: (len(f.stem), f.stem))
    return f"clips/{found[-1].name}" if found else None


def default_edit(pdir, shots_doc):
    """One clip per shot that has a clip, in shot order, no text, no music."""
    video = []
    for shot in (shots_doc or {}).get("shots", []):
        rel = clip_for_shot(pdir, shot)
        if not rel:
            continue
        pr = probe(Path(pdir) / rel)
        dur = round(pr["duration"], 2) if pr else float(shot.get("seconds") or 4)
        video.append({"id": re.sub(r"[^A-Za-z0-9_-]", "_", shot["id"])[:60], "src": rel, "in": 0.0, "out": max(dur, 0.3), "volume": 1.0, "transition": {"type": "cut", "dur": 0.5}})
    aspect = (shots_doc or {}).get("aspect_ratio")
    return {"version": 1, "aspect": aspect if aspect in ASPECTS else "9:16", "fps": 24, "tracks": {"video": video, "text": [], "audio": []}}


# ---------------------------------------------------------------- text -> PNG
def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def render_text_png(t, out_w, path):
    """Draw one text item on a transparent PNG sized for an output frame `out_w` wide.  Returns (width, height) in pixels."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        raise EditError("Text needs the Pillow package: run  pip install Pillow  and restart") from None
    ff = font_file(t["font"], t["weight"], t["italic"])
    if not ff.exists():
        raise EditError(f"font file missing: {ff.name}")
    s = out_w / 1080.0
    size = t["size"] * s
    font = ImageFont.truetype(str(ff), max(4, round(size)))
    lines = (t["text"].upper() if t["caps"] else t["text"]).split("\n")
    probe_draw = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    widths = [probe_draw.textlength(ln, font=font) for ln in lines]
    asc, desc = font.getmetrics()
    lh = size * 1.3
    bw, bh = max(widths + [1]), lh * len(lines)
    padx, pady = (size * 0.4, size * 0.2) if t["bg"] else (0, 0)
    sh = t["shadow"]
    blur = sh["blur"] * s / 3 if sh["on"] else 0
    m = int(blur * 3 + size * 0.3 + 4)
    cw, ch = int(bw + 2 * padx + 2 * m), int(bh + 2 * pady + 2 * m)
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if t["bg"]:
        ImageDraw.Draw(img).rounded_rectangle([m, m, m + bw + 2 * padx, m + bh + 2 * pady], radius=size * 0.28, fill=_rgb(t["bg"]) + (255,))
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    for n, ln in enumerate(lines):
        w = widths[n]
        x = m + padx + {"left": 0, "right": bw - w}.get(t["align"], (bw - w) / 2)
        base = m + pady + n * lh + (lh - (asc + desc)) / 2 + asc
        d.text((x, base), ln, font=font, fill=_rgb(t["color"]) + (255,), anchor="ls")
        ds.text((x, base + size * 0.04), ln, font=font, fill=_rgb(sh["color"]) + (255,), anchor="ls")
        if t["underline"] and ln:
            y = base + size * 0.12
            th = max(1, round(size * 0.06))
            d.rectangle([x, y, x + w, y + th], fill=_rgb(t["color"]) + (255,))
    if sh["on"]:
        if blur:
            shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
        img = Image.alpha_composite(img, shadow)
    img = Image.alpha_composite(img, layer)
    if t["opacity"] < 1:
        img.putalpha(img.getchannel("A").point(lambda v: int(v * t["opacity"])))
    img.save(path, "PNG")
    return cw, ch


# ---------------------------------------------------------------- ffmpeg command (pure)
def plan(edit, files, probes, text_pngs):
    """Build the ffmpeg arguments.  edit is clean(); files = {src: absolute path}; probes = {src: {'duration','audio'}};
    text_pngs = {text id: (png path, width, height)}.  Returns {'args': [...], 'total': seconds}."""
    W, H = ASPECTS[edit["aspect"]]
    fps = edit["fps"]
    video, texts, audio = edit["tracks"]["video"], edit["tracks"]["text"], edit["tracks"]["audio"]
    if not video:
        raise EditError("Add at least one video clip before exporting")
    args, parts = [], []
    for c in video:
        args += ["-i", str(files[c["src"]])]
    n_in = len(video)
    for i, c in enumerate(video):
        d = c["out"] - c["in"]
        parts.append(f"[{i}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p[v{i}]")
        if probes.get(c["src"], {}).get("audio"):
            parts.append(f"[{i}:a]atrim=start={c['in']:.3f}:end={c['out']:.3f},asetpts=PTS-STARTPTS,aresample=44100,"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={c['volume']:.3f}[a{i}]")
        else:
            parts.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={d:.3f},asetpts=PTS-STARTPTS[a{i}]")
    cur_v, cur_a, length = "[v0]", "[a0]", video[0]["out"] - video[0]["in"]
    for i in range(1, len(video)):
        c = video[i]
        d = c["out"] - c["in"]
        td = _td(c, length, d)
        if td == 0:
            parts.append(f"{cur_v}[v{i}]concat=n=2:v=1:a=0[cv{i}]")
            parts.append(f"{cur_a}[a{i}]concat=n=2:v=0:a=1[ca{i}]")
            length += d
        else:
            parts.append(f"{cur_v}[v{i}]xfade=transition={TRANSITIONS[c['transition']['type']]}:duration={td:.3f}:offset={length - td:.3f}[cv{i}]")
            parts.append(f"{cur_a}[a{i}]acrossfade=d={td:.3f}[ca{i}]")
            length += d - td
        cur_v, cur_a = f"[cv{i}]", f"[ca{i}]"
    total = length
    for t in texts:
        if t["id"] not in text_pngs:
            continue
        png, w, h = text_pngs[t["id"]]
        args += ["-i", str(png)]
        k = n_in
        n_in += 1
        x, y = round(t["x"] * W - w / 2), round(t["y"] * H - h / 2)
        parts.append(f"{cur_v}[{k}:v]overlay=x={x}:y={y}:enable='between(t,{t['start']:.3f},{t['end']:.3f})'[o{k}]")
        cur_v = f"[o{k}]"
    mus = []
    for a in audio:
        args += ["-i", str(files[a["src"]])]
        k = n_in
        n_in += 1
        d = a["out"] - a["in"]
        chain = (f"[{k}:a]atrim=start={a['in']:.3f}:end={a['out']:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a['volume']:.3f}")
        if a["fadeIn"]:
            chain += f",afade=t=in:st=0:d={min(a['fadeIn'], d):.3f}"
        if a["fadeOut"]:
            fo = min(a["fadeOut"], d)
            chain += f",afade=t=out:st={d - fo:.3f}:d={fo:.3f}"
        ms = int(a["start"] * 1000)
        parts.append(f"{chain},adelay={ms}|{ms}[m{k}]")
        mus.append(f"[m{k}]")
    parts.append(f"{cur_v}format=yuv420p[vout]")
    if mus:
        parts.append(f"{cur_a}{''.join(mus)}amix=inputs={1 + len(mus)}:duration=first:normalize=0:dropout_transition=0,atrim=duration={total:.3f}[aout]")
    else:
        parts.append(f"{cur_a}anull[aout]")
    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}", "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    return {"args": args, "total": total}


# ---------------------------------------------------------------- render
def render(pdir, edit, progress=None):
    """Render the edit to projects/<name>/exports/<name>_<time>.mp4 (never overwrites).  progress(percent) is called while it runs.
    Returns the relative path 'exports/<file>'."""
    pdir = Path(pdir)
    edit = clean(edit)
    if not tools()["ffmpeg"]:
        raise EditError("ffmpeg is not installed. Install it (macOS: brew install ffmpeg) and restart AI Studio.")
    files, probes = {}, {}
    for it in edit["tracks"]["video"] + edit["tracks"]["audio"]:
        f = pdir / it["src"]
        if not f.is_file():
            raise EditError(f"file not found: {it['src']}")
        files[it["src"]] = f
    for it in edit["tracks"]["video"]:
        pr = probe(files[it["src"]])
        if pr is None:
            raise EditError(f"cannot read the video file {it['src']}")
        probes[it["src"]] = pr
        if it["out"] > pr["duration"] + 0.05:
            raise EditError(f"clip {it['id']} ends at {it['out']:.2f}s but the file is only {pr['duration']:.2f}s long")
    for it in edit["tracks"]["audio"]:
        pr = probe(files[it["src"]])
        if pr is None or not pr["audio"]:
            raise EditError(f"cannot read the sound file {it['src']}")
    out_dir = pdir / "exports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = out_dir / f"{pdir.name}_{stamp}.mp4"
    n = 2
    while final.exists():
        final = out_dir / f"{pdir.name}_{stamp}_{n}.mp4"
        n += 1
    tmp = Path(tempfile.mkdtemp(prefix="aistudio-render-"))
    try:
        W = ASPECTS[edit["aspect"]][0]
        pngs = {}
        for t in edit["tracks"]["text"]:
            p = tmp / f"{t['id']}.png"
            w, h = render_text_png(t, W, p)
            pngs[t["id"]] = (p, w, h)
        pl = plan(edit, files, probes, pngs)
        part = tmp / "out.mp4"
        err = tmp / "err.txt"
        cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *pl["args"], str(part)]
        with open(err, "w") as ef:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
            for line in proc.stdout:
                if progress and line.startswith("out_time_us="):
                    try:
                        progress(min(99.0, max(0.0, int(line.split("=", 1)[1]) / 1e6 / pl["total"] * 100)))
                    except ValueError:
                        pass
            proc.stdout.close()
            proc.wait()
        if proc.returncode != 0 or not part.exists():
            tail = err.read_text(errors="replace").strip().splitlines()[-4:]
            raise EditError("ffmpeg failed: " + " | ".join(tail)[:500])
        shutil.move(str(part), str(final))
        if progress:
            progress(100.0)
        return f"exports/{final.name}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_exports(pdir):
    d = Path(pdir) / "exports"
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.mp4"), reverse=True):
            st = f.stat()
            out.append({"file": f"exports/{f.name}", "bytes": st.st_size, "when": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return out
