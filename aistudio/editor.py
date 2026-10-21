"""Review & Export: the edit list (edit.json), the ffmpeg renderer and the NLE / caption exporters.  No paid call happens here.

edit.json (one per project) = {"version": 1, "aspect": "9:16", "fps": 24, "filter", "effect", "background",
  "tracks": {"video": [...], "text": [...], "audio": [...], "elements": [...], "subtitles": {...}}}
  video item   : {id, src "clips/..", in, out, volume, transition {type, dur}}   (the transition is the one INTO this clip from the previous one)
  text item    : {id, text (<=100 chars), start, end, x, y (centre, 0..1), font, weight, size, color, bg|null, align, bold, italic, underline,
                  caps, opacity, shadow {on, color, blur}}
  audio item   : {id, src "audio/..", start, in, out, volume, fadeIn, fadeOut}
  filter       : {id (one of FILTERS), intensity 0..1}                       colour grading look, applied to the joined timeline
  effect       : {id (one of EFFECTS), intensity 0..1, speed}                picture effect, applied after the grade
  background   : {type "black" | "blur" | "color" | "gradient", color, blurRadius, gradient {from, to}}   what sits behind letterboxed media
  subtitles    : {cues [{id, start, end, text (<=200 chars)}], style, font, size, color, bg|null, y}      burned in on export, srt/vtt sidecars

Text and subtitles are drawn to a transparent PNG with Pillow and laid over the video with ffmpeg's `overlay` (no libfreetype / drawtext
needed, and the bubble, blur shadow and underline look like the preview).  Paths are checked like discard.py: relative, no '..', never inside
_discarded.  Standard library + Pillow (only to render text) + the ffmpeg / ffprobe programs.

The same edit also leaves the app as Final Cut Pro XML (`export_fcpxml`), a CMX 3600 EDL (`export_edl`), SubRip / WebVTT captions
(`export_srt` / `export_vtt`) and a zip bundle for Canva and Google Vids (`export_bundle`).
"""
import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from aistudio import mixing

REPO = Path(__file__).resolve().parent.parent
FONT_DIR = REPO / "assets" / "fonts"

ASPECTS = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}
FPS_OK = (24, 25, 30)
# editor id -> ffmpeg xfade name.  "crossfade" / "fade" / "wipe" keep their old meaning so saved edits still work.
# Names checked against `ffmpeg -h filter=xfade` (ffmpeg 9) and the xfade docs.
TRANSITIONS = {
    "cut": None,
    # dissolves and fades
    "crossfade": "fade", "dissolve": "fade", "fade": "fadeblack", "fadewhite": "fadewhite", "fadegrays": "fadegrays", "fadefast": "fadefast", "fadeslow": "fadeslow", "dither": "dissolve",
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
IMAGE_SUFFIX = (".png", ".jpg", ".jpeg", ".webp", ".svg")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CLIPS, MAX_TEXTS, MAX_AUDIO, MAX_ELEMENTS, MAX_TEXT_CHARS = 100, 200, 20, 100, 100
# colour grading looks and picture effects (the ids the inspector shows).  "none" is a real value: it renders the original picture.
FILTERS = {"cinema", "teal_orange", "vintage", "noir", "vibrant", "cyberpunk", "warm", "none"}
EFFECTS = {"vignette", "grain", "shake", "zoompulse", "glitch", "blur", "none"}
BACKGROUNDS = ("black", "blur", "color", "gradient")
SUBTITLE_STYLES = {"tiktok", "classic", "minimal", "karaoke"}
MAX_CUES, MAX_CUE_CHARS = 500, 200

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
    """Project-relative path 'folder/name.ext' with no '..', not absolute, not inside _discarded.  Returns the posix string.
    A sub-folder is allowed (the voiceover files live in 'audio/vo/'), but the first part must be one of the folders."""
    if not isinstance(rel, str) or not rel:
        raise EditError("a clip, sound or element has no file")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or "\\" in rel:
        raise EditError(f"invalid path: {rel}")
    if "_discarded" in p.parts:
        raise EditError(f"{rel} is in Discarded; restore it first")
    allowed = (folder,) if isinstance(folder, str) else tuple(folder)
    if not p.parts or p.parts[0] not in allowed or len(p.parts) < 2 or p.suffix.lower() not in suffixes:
        raise EditError(f"{rel} must be {'/'.join(allowed)}/<file>{'|'.join(suffixes)}")
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


def _optnum(d, key, lo, hi, default, what):
    """A number that may be absent (or null): only a value that is there is range-checked."""
    if d.get(key) is None:
        return float(default)
    return _num(d, key, lo, hi, default, what)


def _as_dict(v, what):
    """Accept {"id": ...} or a bare id string; reject anything else."""
    if isinstance(v, str):
        return {"id": v}
    if not isinstance(v, dict):
        raise EditError(f"{what} must be an object")
    return v


def clean_filter(v):
    """Normalise the grading look: {id: one of FILTERS, intensity: 0..1}.  Absent = no grading."""
    d = _as_dict(v, "filter") if v is not None else {}
    fid = d.get("id", "none")
    if fid not in FILTERS:
        raise EditError(f"filter must be one of {', '.join(sorted(FILTERS))}")
    return {"id": fid, "intensity": _optnum(d, "intensity", 0, 1, 1, "filter")}


def clean_effect(v):
    """Normalise the picture effect: {id: one of EFFECTS, intensity: 0..1, speed: 0.1..4}.  Absent = no effect."""
    d = _as_dict(v, "effect") if v is not None else {}
    eid = d.get("id", "none")
    if eid not in EFFECTS:
        raise EditError(f"effect must be one of {', '.join(sorted(EFFECTS))}")
    out = {"id": eid, "intensity": _optnum(d, "intensity", 0, 1, 1, "effect")}
    if d.get("speed") is not None:
        out["speed"] = _num(d, "speed", 0.1, 4, 1, "effect")
    return out


def clean_background(v):
    """Normalise what sits behind letterboxed media: {type: black | blur | color | gradient, color, blurRadius, gradient {from, to}}."""
    d = _as_dict(v, "background") if v is not None else {}
    kind = d.get("type", "black")
    if kind not in BACKGROUNDS:
        raise EditError(f"background must be one of {', '.join(BACKGROUNDS)}")
    if kind == "color":
        return {"type": kind, "color": _color(d.get("color", "#0b0c16"), "background colour")}
    if kind == "gradient":
        g = d.get("gradient")
        if not isinstance(g, dict):
            raise EditError("background gradient must be an object with from and to colours")
        return {"type": kind, "gradient": {"from": _color(g.get("from"), "gradient from"), "to": _color(g.get("to"), "gradient to")}}
    if kind == "blur":
        return {"type": kind, "blurRadius": _optnum(d, "blurRadius", 0, 100, 25, "background")}
    return {"type": kind}


def clean_subtitles(v):
    """Normalise the subtitle track: {cues [{id, start, end, text}], style, font, size, color, bg, y}.  A bare list is taken as the cues."""
    if v is None:
        d = {}
    elif isinstance(v, dict):
        d = v
    elif isinstance(v, list):
        d = {"cues": v}                     # a bare list of cues (an older edit.json) still works
    else:
        raise EditError("subtitles must be an object")
    style = d.get("style", "classic")
    if style not in SUBTITLE_STYLES:
        raise EditError(f"subtitle style must be one of {', '.join(sorted(SUBTITLE_STYLES))}")
    family = d.get("font", "Poppins")
    if family not in FONTS:
        raise EditError(f"subtitle font must be one of {', '.join(FONTS)}")
    cues, seen = d.get("cues") or [], set()
    if not isinstance(cues, list) or len(cues) > MAX_CUES:
        raise EditError(f"subtitles must be a list of at most {MAX_CUES} cues")
    out_cues = []
    for n, c in enumerate(cues):
        w = f"subtitle {n + 1}"
        if not isinstance(c, dict):
            raise EditError(f"{w} must be an object")
        i = c.get("id") or f"cue{n + 1}"
        if not isinstance(i, str) or not ID_RE.match(i):
            raise EditError(f"{w}: invalid id {i!r}")
        if i in seen:
            raise EditError(f"{w}: duplicate id {i}")
        seen.add(i)
        text = c.get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CUE_CHARS:
            raise EditError(f"{w}: text must be 1 to {MAX_CUE_CHARS} characters")
        s, e = _num(c, "start", 0, 36000, 0, w), _num(c, "end", 0, 36000, 0, w)
        if e - s < 0.05:
            raise EditError(f"{w}: end must be at least 0.05 s after start")
        out_cues.append({"id": i, "start": s, "end": e, "text": text.strip()})
    return {"cues": out_cues, "style": style, "font": family,
            "size": _optnum(d, "size", 8, 300, 46, "subtitles"),
            "color": _color(d.get("color", "#ffffff"), "subtitle colour"),
            "bg": _color(d.get("bg"), "subtitle background", True),
            "y": _optnum(d, "y", 0, 1, 0.86, "subtitles")}


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
    out = {"version": 1, "aspect": aspect, "fps": fps,
           "filter": clean_filter(doc.get("filter")), "effect": clean_effect(doc.get("effect")),
           "background": clean_background(doc.get("background")),
           "tracks": {"video": [], "text": [], "audio": [], "elements": [], "subtitles": clean_subtitles(tracks.get("subtitles"))}}

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
        tr_clean = {"type": tr.get("type", "cut"), "dur": _num(tr, "dur", 0.1, 5, 0.5, w + " transition")}
        if "direction" in tr and tr["direction"] in ("left", "right", "up", "down", "tl"):
            tr_clean["direction"] = tr["direction"]
        if "color" in tr and tr["color"] in ("black", "white", "gray"):
            tr_clean["color"] = tr["color"]
        if "curve" in tr and tr["curve"] in ("linear", "smooth", "fast", "slow"):
            tr_clean["curve"] = tr["curve"]
        item = {"id": i, "src": safe_rel(c.get("src"), "clips", VIDEO_SUFFIX), "in": a, "out": b, "volume": _num(c, "volume", 0, 2, 1, w),
                "transition": tr_clean}
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
                                       "speed": _optnum(a, "speed", 0.5, 2, 1, w),
                                       "name": str(a.get("name") or Path(a["src"]).stem)[:60]})

    elem, seen = tracks.get("elements") or [], set()
    if not isinstance(elem, list) or len(elem) > MAX_ELEMENTS:
        raise EditError(f"elements must be a list of at most {MAX_ELEMENTS} items")
    for n, el in enumerate(elem):
        w = f"element {n + 1}"
        if not isinstance(el, dict):
            raise EditError(f"{w} must be an object")
        i = _id(el, seen, w)
        s, e = _num(el, "start", 0, 36000, 0, w), _num(el, "end", 0, 36000, 0, w)
        if e - s < 0.2:
            raise EditError(f"{w}: end must be at least 0.2 s after start")
        src = safe_rel(el.get("src"), ("elements", "stills", "assets"), IMAGE_SUFFIX)
        out["tracks"]["elements"].append({
            "id": i, "src": src, "start": s, "end": e,
            "x": _num(el, "x", 0, 1, 0.5, w), "y": _num(el, "y", 0, 1, 0.5, w),
            "scale": _num(el, "scale", 0.05, 3.0, 0.3, w),
            "opacity": _num(el, "opacity", 0, 1, 1.0, w),
            "name": str(el.get("name") or Path(src).stem)[:60],
        })
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
    """{'duration', 'audio', 'width', 'height'} from ffprobe, or None when ffprobe is missing or the file is unreadable.
    width/height are 0 for audio-only files (the NLE exporters need them for the media format)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout or "{}")
        streams = j.get("streams", [])
        vid = next((s for s in streams if s.get("codec_type") == "video"), {})
        try:
            w, h = int(vid.get("width") or 0), int(vid.get("height") or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        return {"duration": float(j["format"]["duration"]), "audio": any(s.get("codec_type") == "audio" for s in streams),
                "width": w, "height": h}
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
    return {"version": 1, "aspect": aspect if aspect in ASPECTS else "9:16", "fps": 24, "tracks": {"video": video, "text": [], "audio": [], "elements": []}}


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


def subtitle_item(cue, cfg):
    """Shape one subtitle cue like a text item so it renders through render_text_png (same look, still no libfreetype needed).
    The style only fills in what the config left out: tiktok/karaoke get a pill and a heavy weight, classic a drop shadow, minimal neither."""
    style = cfg.get("style", "classic")
    family = cfg.get("font", "Poppins")
    if family not in FONTS:
        family = "Poppins"
    want = 800 if style in ("tiktok", "karaoke") else (400 if style == "minimal" else 700)
    weights = FONTS[family]["weights"]
    weight = want if want in weights else (400 if 400 in weights else next(iter(weights)))
    bg = cfg.get("bg")
    if bg is None:
        bg = {"tiktok": "#000000", "karaoke": "#000000", "minimal": "#0b0c16"}.get(style)
    return {"id": cue["id"], "text": cue["text"], "start": cue["start"], "end": cue["end"],
            "x": 0.5, "y": float(cfg.get("y", 0.86)), "font": family, "weight": weight,
            "size": float(cfg.get("size", 46)), "color": cfg.get("color") or "#ffffff", "bg": bg,
            "align": "center", "bold": weight >= 600, "italic": False, "underline": False, "caps": False,
            "opacity": 1.0, "shadow": {"on": style != "minimal", "color": "#000000", "blur": 14}}


# ---------------------------------------------------------------- captions
def caption_items(cues, style=None):
    """The caption cues as the editor's text items (TText): the format's or brand kit's caption
    style, fonts only from assets/fonts.  The items are valid by construction (they go through
    clean())."""
    from aistudio import captions
    return captions.to_text_track(cues, style)


def with_captions(edit, cues, style=None):
    """The edit with the caption cues as its text track (a new edit list; nothing is written)."""
    from aistudio import captions
    return captions.with_captions(edit, cues, style)


# ---------------------------------------------------------------- ffmpeg command (pure)
def _filter_chain(f):
    """Colour grading look -> ffmpeg chain (eq / colorbalance, mixed towards the original by `intensity`).  '' = nothing to do."""
    fid = (f or {}).get("id", "none")
    k = float((f or {}).get("intensity", 1) or 0)
    if fid == "none" or k <= 0:
        return ""
    k = min(k, 1.0)
    q = lambda v: f"{max(0.0, v):.4f}"                     # keeps the chain readable and deterministic
    if fid == "cinema":
        return f"eq=contrast={q(1 + 0.12 * k)}:saturation={q(1 + 0.18 * k)},colorbalance=rs={q(0.05 * k)}:bs={q(-0.05 * k)}"
    if fid == "teal_orange":
        return (f"colorbalance=rs={q(0.15 * k)}:gs={q(-0.05 * k)}:bs={q(-0.10 * k)}:rh={q(-0.10 * k)}:bh={q(0.15 * k)},"
                f"eq=saturation={q(1 + 0.10 * k)}")
    if fid == "vintage":
        return (f"eq=contrast={q(1 - 0.10 * k)}:saturation={q(1 - 0.25 * k)}:gamma={q(1 + 0.06 * k)},"
                f"colorbalance=rs={q(0.12 * k)}:gs={q(0.04 * k)}:bs={q(-0.12 * k)}")
    if fid == "noir":
        return f"eq=saturation={q(1 - k)}:contrast={q(1 + 0.25 * k)}"
    if fid == "vibrant":
        return f"eq=saturation={q(1 + 0.40 * k)}:contrast={q(1 + 0.05 * k)}"
    if fid == "cyberpunk":
        return (f"colorbalance=rs={q(0.10 * k)}:gs={q(0.05 * k)}:bs={q(0.15 * k)}:rh={q(0.20 * k)}:gh={q(-0.10 * k)}:bh={q(0.15 * k)},"
                f"eq=saturation={q(1 + 0.25 * k)}")
    if fid == "warm":
        return f"colorbalance=rs={q(0.10 * k)}:gs={q(0.03 * k)}:bs={q(-0.10 * k)},eq=brightness={q(0.03 * k)}:saturation={q(1 + 0.10 * k)}"
    return ""


def _effect_chain(e, W, H, fps):
    """Picture effect -> ffmpeg chain, sized for the output frame.  '' = nothing to do."""
    eid = (e or {}).get("id", "none")
    k = float((e or {}).get("intensity", 1) or 0)
    if eid == "none" or k <= 0:
        return ""
    k = min(k, 1.0)
    speed = float((e or {}).get("speed", 1) or 1)
    if eid == "vignette":
        return f"vignette=angle={0.7854 * k:.4f}"                       # PI/4 * intensity
    if eid == "grain":
        return f"noise=alls={max(1, round(40 * k))}:allf=t+u"
    if eid == "shake":
        mx = max(2, round(W * 0.015 * k))                               # a fixed crop that wanders = handheld drift
        my = max(2, round(H * 0.015 * k))
        return (f"crop=iw-{2 * mx}:ih-{2 * my}:x='(iw-ow)/2+{mx}*sin(t*{6.2832 * speed:.4f})':y='(ih-oh)/2+{my}*cos(t*{8.1681 * speed:.4f})',"
                f"scale={W}:{H}")
    if eid == "zoompulse":
        rate = 0.0012 * k * speed                                       # ~1.35x over 30 s of push-in
        return (f"zoompan=z='min(1+{rate:.6f}*on,1.4)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps}")
    if eid == "glitch":
        px = max(1, round(3 * k))
        return f"rgbashift=rh={px}:bh=-{px}"
    if eid == "blur":
        return f"gblur=sigma={4.0 * k:.3f}"
    return ""


def _background_parts(bg, W, H, fps, head, out, idx):
    """The per-clip chain that lays the trimmed clip on its background: a blurred fill of the clip itself, a flat colour, or black letterbox
    bars.  `head` is the "[i:v]trim=...,setpts=..." start of the chain, `out` the label it produces."""
    kind = (bg or {}).get("type", "black")
    if kind == "blur":
        r = max(1, min(63, int(round(float((bg or {}).get("blurRadius", 25) or 25)))))
        return [f"{head},split=2[fgr{idx}][bgs{idx}]",
                f"[bgs{idx}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur={r}:2[bgc{idx}]",
                f"[fgr{idx}]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs{idx}]",
                f"[bgc{idx}][fgs{idx}]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1,fps={fps},settb=1/{fps},format=yuv420p{out}"]
    # a gradient fills flat with its first colour (the preview shows the full ramp; ffmpeg would need a second source input for it)
    color = "black"
    if kind == "color":
        color = (bg or {}).get("color") or "#000000"
    elif kind == "gradient":
        color = ((bg or {}).get("gradient") or {}).get("from") or "#000000"
    color = "0x" + color[1:] if color.startswith("#") else color   # #rrggbb is a filtergraph comment character, 0xrrggbb is not
    return [f"{head},scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={color},setsar=1,fps={fps},settb=1/{fps},format=yuv420p{out}"]


def mix_options(doc=None, options=None):
    """The optional export mix settings: {"loudness": LUFS, "duck": ..., "denoise": bool}.
    They come from the edit document (the "audio" or "mix" object) and are OFF when they are not
    there, so an export without them is exactly the export of before."""
    if options is None:
        raw = (doc or {}).get("audio") or (doc or {}).get("mix") or {}
        options = raw if isinstance(raw, dict) else {}
    out = {}
    lufs = options.get("loudness")
    if isinstance(lufs, (int, float)) and not isinstance(lufs, bool) and -70 <= lufs <= -5:
        out["loudness"] = float(lufs)
    if options.get("duck"):
        out["duck"] = options["duck"]
    if options.get("denoise"):
        out["denoise"] = True
    return out


def _duck_pairs(audio, options):
    """The (voice, music) pairs the music is ducked under.
    duck = {"voice": id, "music": id} | [{"voice","music"}, ...] | True (the voiceover clips are
    the ones whose id starts with 'vo', the rest is the music).  [] when there is nothing to duck."""
    duck = (options or {}).get("duck")
    if not duck:
        return []
    ids = [a["id"] for a in audio]
    if duck is True:
        voice = next((a["id"] for a in audio if a["id"].startswith("vo") or str(a.get("name") or "").lower().startswith("voiceover")), None)
        return [(voice, m) for m in ids if m != voice] if voice else []
    raw = duck if isinstance(duck, list) else [duck]
    pairs = []
    for item in raw:
        if isinstance(item, dict) and item.get("voice") and item.get("music"):
            pairs.append((item["voice"], item["music"]))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((item[0], item[1]))
    return [(v, m) for v, m in pairs if v in ids and m in ids]


def plan(edit, files, probes, text_pngs, sub_pngs=None, options=None):
    """Build the ffmpeg arguments.  edit is clean(); files = {src: absolute path}; probes = {src: {'duration','audio'}};
    text_pngs = {text id: (png path, width, height)}; sub_pngs = {subtitle cue id: (png path, width, height)}.
    options = the mix settings (see mix_options): the music is ducked under the voice and the
    dialogue is cleaned of noise.  Without them the arguments are exactly the ones of before.
    Returns {'args': [...], 'total': seconds}."""
    W, H = ASPECTS[edit["aspect"]]
    fps = edit["fps"]
    options = mix_options(options=options)
    pairs = _duck_pairs(edit["tracks"]["audio"], options)
    voice_ids = {v for v, _ in pairs}
    voice_of = {m: v for v, m in pairs}
    video, texts, audio, elements = edit["tracks"]["video"], edit["tracks"]["text"], edit["tracks"]["audio"], edit["tracks"].get("elements", [])
    if not video:
        raise EditError("Add at least one video clip before exporting")
    args, parts = [], []
    for c in video:
        args += ["-i", str(files[c["src"]])]
    n_in = len(video)
    for i, c in enumerate(video):
        d = c["out"] - c["in"]
        head = f"[{i}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},setpts=PTS-STARTPTS"
        parts += _background_parts(edit.get("background"), W, H, fps, head, f"[v{i}]", i)
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
            parts.append(f"{cur_v}[v{i}]concat=n=2:v=1:a=0,settb=1/{fps}[cv{i}]")
            parts.append(f"{cur_a}[a{i}]concat=n=2:v=0:a=1[ca{i}]")
            length += d
        else:
            tr = c["transition"]
            tr_type = tr["type"]
            direction = tr.get("direction")
            color = tr.get("color")
            if tr_type == "wipe" and direction:
                mapped = f"wipe{direction}" if direction != "left" else "wipe"
                if mapped in TRANSITIONS:
                    tr_type = mapped
            elif tr_type.startswith("slide") and direction:
                mapped = f"slide{direction}"
                if mapped in TRANSITIONS:
                    tr_type = mapped
            elif tr_type.startswith("smooth") and direction in ("left", "right"):
                mapped = f"smooth{direction}"
                if mapped in TRANSITIONS:
                    tr_type = mapped
            elif tr_type.startswith("cover") and direction in ("left", "right", "up", "down"):
                mapped = f"cover{direction}"
                if mapped in TRANSITIONS:
                    tr_type = mapped
            elif tr_type.startswith("reveal") and direction in ("left", "right", "up", "down"):
                mapped = f"reveal{direction}"
                if mapped in TRANSITIONS:
                    tr_type = mapped
            elif tr_type == "fade" and color:
                if color == "white":
                    tr_type = "fadewhite"
                elif color == "gray":
                    tr_type = "fadegrays"
            xfade_name = TRANSITIONS.get(tr_type) or TRANSITIONS.get(tr["type"], "fade")
            parts.append(f"{cur_v}[v{i}]xfade=transition={xfade_name}:duration={td:.3f}:offset={length - td:.3f},settb=1/{fps}[cv{i}]")
            parts.append(f"{cur_a}[a{i}]acrossfade=d={td:.3f}[ca{i}]")
            length += d - td
        cur_v, cur_a = f"[cv{i}]", f"[ca{i}]"
    total = length
    stage = 0
    for chain in (_filter_chain(edit.get("filter")), _effect_chain(edit.get("effect"), W, H, fps)):
        if chain:                                   # graded and effected picture, but still under the text and element overlays
            stage += 1
            parts.append(f"{cur_v}{chain}[look{stage}]")
            cur_v = f"[look{stage}]"
    for el in elements:
        if el["src"] not in files:
            continue
        args += ["-i", str(files[el["src"]])]
        k = n_in
        n_in += 1
        target_w = max(16, int(round(W * el["scale"] / 2.0) * 2))
        op = el.get("opacity", 1.0)
        if op < 0.999:
            filter_chain = f"[{k}:v]scale={target_w}:-2:force_original_aspect_ratio=decrease,format=rgba,colorchannelmixer=aa={op:.3f}[el{k}]"
        else:
            filter_chain = f"[{k}:v]scale={target_w}:-2:force_original_aspect_ratio=decrease,format=rgba[el{k}]"
        parts.append(filter_chain)
        parts.append(f"{cur_v}[el{k}]overlay=x='W*{el['x']:.4f}-w/2':y='H*{el['y']:.4f}-h/2':eof_action=repeat:enable='between(t,{el['start']:.3f},{el['end']:.3f})'[o{k}]")
        cur_v = f"[o{k}]"
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
    subs = edit["tracks"].get("subtitles") or {}
    sub_y = float(subs.get("y", 0.86))
    for cue in subs.get("cues", []):
        if not sub_pngs or cue["id"] not in sub_pngs:
            continue
        png, w, h = sub_pngs[cue["id"]]
        args += ["-i", str(png)]
        k = n_in
        n_in += 1
        x, y = round(0.5 * W - w / 2), round(sub_y * H - h / 2)
        parts.append(f"{cur_v}[{k}:v]overlay=x={x}:y={y}:enable='between(t,{cue['start']:.3f},{cue['end']:.3f})'[o{k}]")
        cur_v = f"[o{k}]"
    mus = []
    labels = {}
    for a in audio:
        args += ["-i", str(files[a["src"]])]
        k = n_in
        n_in += 1
        d = a["out"] - a["in"]
        chain = (f"[{k}:a]atrim=start={a['in']:.3f}:end={a['out']:.3f},asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a['volume']:.3f}")
        if a.get("speed") and abs(a["speed"] - 1.0) > 1e-6:
            chain += f",atempo={a['speed']:.4f}"      # a voiceover that had to be sped up to fit its shot
        if a["fadeIn"]:
            chain += f",afade=t=in:st=0:d={min(a['fadeIn'], d):.3f}"
        if a["fadeOut"]:
            fo = min(a["fadeOut"], d)
            chain += f",afade=t=out:st={d - fo:.3f}:d={fo:.3f}"
        if options.get("denoise") and a["id"] in voice_ids:
            chain += "," + mixing.denoise_filter()   # the dialogue is cleaned of hiss
        ms = int(a["start"] * 1000)
        parts.append(f"{chain},adelay={ms}|{ms}[m{k}]")
        mus.append(f"[m{k}]")
        labels[a["id"]] = (k, f"[m{k}]")
    mixed = list(mus)
    if pairs:                                   # the music ducks under the voice (the sidechain)
        counts = {}
        for v, m in pairs:
            counts[v] = counts.get(v, 0) + 1
        for v, n in counts.items():             # one copy of the voice for the mix, one per music track
            outs = "".join(f"[vsc{labels[v][0]}c{i}]" for i in range(n))
            parts.append(f"{labels[v][1]}asplit={n + 1}{outs}[vmix{labels[v][0]}]")
        used = {}
        mixed = []
        for a in audio:
            k, lab = labels[a["id"]]
            if a["id"] in voice_of:
                v = voice_of[a["id"]]
                i = used.get(v, 0)
                used[v] = i + 1
                parts.append(mixing.duck_filter(f"[vsc{labels[v][0]}c{i}]", lab, out=f"[dk{k}]"))
                mixed.append(f"[dk{k}]")
            elif a["id"] in voice_ids:
                mixed.append(f"[vmix{k}]")
            else:
                mixed.append(lab)
    if options.get("denoise") and not voice_ids:
        parts.append(f"{cur_a}{mixing.denoise_filter()}[aclean]")   # no voiceover: the clips carry the dialogue
        cur_a = "[aclean]"
    parts.append(f"{cur_v}format=yuv420p[vout]")
    if mixed:
        parts.append(f"{cur_a}{''.join(mixed)}amix=inputs={1 + len(mixed)}:duration=first:normalize=0:dropout_transition=0,atrim=duration={total:.3f}[aout]")
    else:
        parts.append(f"{cur_a}anull[aout]")
    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}", "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    return {"args": args, "total": total}


# ---------------------------------------------------------------- render
def render(pdir, edit, progress=None, options=None):
    """Render the edit to projects/<name>/exports/<name>_<time>.mp4 (never overwrites).  progress(percent) is called while it runs.
    options = the mix settings (see mix_options): {"loudness": LUFS, "duck": ..., "denoise": bool}.
    They are OFF when they are not given, so the export is exactly the export of before.
    Returns the relative path 'exports/<file>'."""
    pdir = Path(pdir)
    options = mix_options(edit, options)
    edit = clean(edit)
    if not tools()["ffmpeg"]:
        raise EditError("ffmpeg is not installed. Install it (macOS: brew install ffmpeg) and restart AI Studio.")
    files, probes = {}, {}
    for it in edit["tracks"]["video"] + edit["tracks"]["audio"] + edit["tracks"].get("elements", []):
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    final = out_dir / f"{pdir.name}_{stamp}.mp4"
    n = 2
    while final.exists():
        final = out_dir / f"{pdir.name}_{stamp}_{n}.mp4"
        n += 1
    tmp = Path(tempfile.mkdtemp(prefix="aistudio-render-"))
    try:
        W = ASPECTS[edit["aspect"]][0]
        pngs, sub_pngs = {}, {}
        for t in edit["tracks"]["text"]:
            p = tmp / f"{t['id']}.png"
            w, h = render_text_png(t, W, p)
            pngs[t["id"]] = (p, w, h)
        subs = edit["tracks"].get("subtitles") or {}
        for cue in subs.get("cues", []):
            p = tmp / f"sub_{cue['id']}.png"
            w, h = render_text_png(subtitle_item(cue, subs), W, p)
            sub_pngs[cue["id"]] = (p, w, h)
        pl = plan(edit, files, probes, pngs, sub_pngs, options=options)
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
        if options.get("loudness"):      # the two-pass loudnorm: measure the mix, then apply the target
            loud = tmp / "loud.mp4"
            try:
                mixing.normalise(part, loud, options["loudness"], pdir=tmp)
            except mixing.MixError as e:
                raise EditError(str(e)) from None
            shutil.move(str(loud), str(part))
        shutil.move(str(part), str(final))
        refs = [{"path": rel, "sha": hashlib.sha256((pdir / rel).read_bytes()).hexdigest()}
                for rel in files if (pdir / rel).is_file()]
        from aistudio import consent
        consent.write_lineage(pdir, final, {"editor_render": True, "refs": refs},
                              source_sha=(refs[0].get("sha", "") if refs else ""), kind="editor_render")
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


# ---------------------------------------------------------------- NLE, captions and bundle exports
def media(pdir, edit):
    """What an export needs from disk: ({src: absolute path}, {video src: ffprobe result or None}).
    The paths are built even when a file is missing: the XML/EDL still describe the timeline (the NLE shows offline media) and the bundle
    skips what is not there."""
    pdir, tracks = Path(pdir), edit["tracks"]
    files = {it["src"]: pdir / it["src"] for it in tracks["video"] + tracks["audio"] + tracks.get("elements", [])}
    probes = {c["src"]: probe(pdir / c["src"]) for c in tracks["video"]}
    return files, probes


def timeline_spans(video):
    """[(src_in, src_out, record_in, record_out, transition_in)] per clip: where it sits on the timeline, transitions overlapping the previous
    clip exactly like timeline_length() (which is the last record_out)."""
    spans, cur = [], 0.0
    for n, c in enumerate(video):
        d = c["out"] - c["in"]
        td = 0.0 if n == 0 else _td(c, cur, d)
        ri = cur - td
        spans.append((c["in"], c["out"], ri, ri + d, td))
        cur = ri + d
    return spans


def _timecode(t, fps):
    """HH:MM:SS:FF at the edit frame rate (EDL and the header comments)."""
    total = int(round(max(0.0, float(t)) * fps))
    f = total % fps
    s = (total // fps) % 60
    m = (total // (fps * 60)) % 60
    h = total // (fps * 3600)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _clock(t, sep):
    """HH:MM:SS<sep>mmm (SubRip wants ',', WebVTT '.')."""
    ms = int(round(max(0.0, float(t)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _cue_list(cues):
    """The cues of a subtitles config (or a bare list of cues)."""
    return cues.get("cues", []) if isinstance(cues, dict) else list(cues or [])


def export_srt(cues):
    """SubRip text: numbered blocks of `start --> end` and the cue line.  Uploads to YouTube, TikTok, Canva and Google Vids."""
    blocks = [f"{n}\n{_clock(c['start'], ',')} --> {_clock(c['end'], ',')}\n{str(c.get('text', '')).strip()}"
              for n, c in enumerate(_cue_list(cues), 1)]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def export_vtt(cues):
    """WebVTT: the same timing with '.' milliseconds and the WEBVTT header."""
    blocks = [f"{n}\n{_clock(c['start'], '.')} --> {_clock(c['end'], '.')}\n{str(c.get('text', '')).strip()}"
              for n, c in enumerate(_cue_list(cues), 1)]
    return "WEBVTT\n\n" + ("\n\n".join(blocks) + "\n" if blocks else "")


def _project_name(files):
    """Project folder name, read from a media path (<project>/clips/x.mp4): the timeline name of the NLE exports."""
    for f in files.values():
        name = Path(f).parent.parent.name
        if name:
            return name
    return "AI Studio"


def _xml_time(t, fps):
    """Frame-exact FCPXML duration: '12/24s'."""
    return f"{max(0, int(round(float(t) * fps)))}/{fps}s"


def export_fcpxml(edit, files, probes):
    """Final Cut Pro XML (fcpxml): the video spine with its real record points, the dissolves, and the music in a lane below.
    Final Cut Pro opens it directly; DaVinci Resolve through File > Import > Timeline; other tools take it through their XML importer.
    files = {src: path}, probes = {src: probe result or None}."""
    video, audio = edit["tracks"]["video"], edit["tracks"]["audio"]
    if not video:
        raise EditError("Add at least one video clip before exporting")
    fps, W, H = edit["fps"], *ASPECTS[edit["aspect"]]
    esc = lambda s: xml_escape(str(s), {'"': "&quot;", "'": "&apos;"})
    project = _project_name(files)
    order, ids = [], {}
    for src in [c["src"] for c in video] + [a["src"] for a in audio]:
        if src not in ids:
            ids[src] = f"r{len(order) + 2}"               # r1 = the output format, rf* = the media formats
            order.append(src)
    for src in order:
        if src not in files:
            raise EditError(f"file not found: {src}")
    res = [f'<format id="r1" name="FFVideoFormat{W}x{H}p{fps}" frameDuration="1/{fps}s" width="{W}" height="{H}" '
           f'colorSpace="1-1-1 (Rec. 709)"/>']
    fmt_ids, fmt_of = {}, {}
    for src in order:
        pr = probes.get(src) or {}
        w, h = int(pr.get("width") or 0), int(pr.get("height") or 0)
        if w <= 0 or h <= 0:
            w, h = W, H
        if (w, h) not in fmt_ids:
            fid = f"rf{len(fmt_ids) + 1}"
            fmt_ids[(w, h)] = fid
            res.append(f'<format id="{fid}" name="FFVideoFormat{w}x{h}" frameDuration="1/{fps}s" width="{w}" height="{h}" '
                       f'colorSpace="1-1-1 (Rec. 709)"/>')
        fmt_of[src] = fmt_ids[(w, h)]
    for src in order:
        pr = probes.get(src) or {}
        f = Path(files[src]).resolve()
        dur = pr.get("duration")
        fallback = max([c["out"] for c in video if c["src"] == src] + [a["out"] for a in audio if a["src"] == src] + [1.0])
        dur = float(dur) if isinstance(dur, (int, float)) and dur > 0 else fallback
        uid = "AIStudio-" + re.sub(r"[^A-Za-z0-9]+", "-", src).strip("-")
        has_video = any(c["src"] == src for c in video)
        fmt_attr = f' format="{fmt_of[src]}"' if has_video else ""
        res.append(f'<asset id="{ids[src]}" name="{esc(f.name)}" uid="{esc(uid)}" start="0s" duration="{_xml_time(dur, fps)}" '
                   f'hasVideo="{1 if has_video else 0}" hasAudio="{1 if (pr.get("audio") or not has_video) else 0}"{fmt_attr} '
                   f'src="{f.as_uri()}"/>')
    spine = []
    for c, (si, so, ri, ro, td) in zip(video, timeline_spans(video)):
        attrs = (f'ref="{ids[c["src"]]}" name="{esc(Path(c["src"]).name)}" offset="{_xml_time(ri, fps)}" '
                 f'start="{_xml_time(si, fps)}" duration="{_xml_time(so - si, fps)}"')
        if td > 0:                                       # the dissolve INTO this clip
            label = {"fade": "Dip to Black", "fadewhite": "Dip to White", "fadegrays": "Dip to Grey"}.get(c["transition"]["type"], "Cross Dissolve")
            inner = " " * 12
            spine.append(f'<asset-clip {attrs}>\n{inner}<transition alignment="center" displayName="{esc(label)}" '
                         f'outgoingDuration="{_xml_time(td, fps)}" incomingDuration="{_xml_time(td, fps)}"/>\n{inner}</asset-clip>')
        else:
            spine.append(f'<asset-clip {attrs}/>')
    for a in audio:
        spine.append(f'<asset-clip ref="{ids[a["src"]]}" name="{esc(Path(a["src"]).name)}" offset="{_xml_time(a["start"], fps)}" '
                     f'start="{_xml_time(a["in"], fps)}" duration="{_xml_time(a["out"] - a["in"], fps)}" lane="-1" role="music"/>')
    total = timeline_spans(video)[-1][3]
    indent = "          "                                # spine items sit under <spine>
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.9">\n  <resources>\n'
            + "\n".join(f"    {r}" for r in res)
            + f'\n  </resources>\n  <library location="{Path(files[order[0]]).resolve().parent.parent.as_uri()}/">\n'
            f'    <event name="{esc(project)}">\n      <project name="{esc(project)}">\n'
            f'        <sequence format="r1" duration="{_xml_time(total, fps)}" tcStart="0s" tcFormat="NDF">\n          <spine>\n'
            + "\n".join(f"{indent}{s}" for s in spine)
            + "\n          </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n")


def _reel(src):
    """A CMX 3600 reel name: upper case letters and digits, at most 8 characters."""
    return re.sub(r"[^A-Za-z0-9]", "", Path(src).stem).upper()[:8] or "AX"


def export_edl(edit, files):
    """CMX 3600 edit decision list: picture events with their source and record timecodes (dissolves overlap the previous record-out),
    the clip audio on A1 when ffprobe can see it, and the music after that.  Reads in Premiere, Resolve, Avid and Lightworks."""
    video, audio = edit["tracks"]["video"], edit["tracks"]["audio"]
    if not video:
        raise EditError("Add at least one video clip before exporting")
    fps = edit["fps"]
    lines = [f"TITLE: {_project_name(files)[:31]}", "FCM: NON-DROP FRAME", ""]

    def event(n, src, track, kind, si, so, ri, ro):
        # CMX 3600 columns: event, reel (8), track, transition, source in/out, record in/out
        return f"{n:03d}  {_reel(src):<9}{track:<6}{kind:<9}{_timecode(si, fps)} {_timecode(so, fps)} " \
               f"{_timecode(ri, fps)} {_timecode(ro, fps)}"

    known, n = {}, 0
    for c, (si, so, ri, ro, td) in zip(video, timeline_spans(video)):
        if c["src"] not in files:
            raise EditError(f"file not found: {c['src']}")
        if c["src"] not in known:
            known[c["src"]] = probe(files[c["src"]])
        for track in ("V", "A1") if (known[c["src"]] or {}).get("audio") else ("V",):
            n += 1
            lines.append(event(n, c["src"], track, "D" if (td > 0 and track == "V") else "C", si, so, ri, ro))
            lines.append(f"* FROM CLIP NAME: {Path(c['src']).name}")
            lines.append(f"* SOURCE FILE: {c['src']}")
            if track == "V" and td > 0:
                lines.append(f"* TRANSITION IN: DISSOLVE DURATION {_timecode(td, fps)}")
            lines.append("")
    for a in audio:
        if a["src"] not in files:
            raise EditError(f"file not found: {a['src']}")
        n += 1
        lines.append(event(n, a["src"], "A1", "C", a["in"], a["out"], a["start"], a["start"] + (a["out"] - a["in"])))
        lines.append(f"* FROM CLIP NAME: {Path(a['src']).name}")
        lines.append(f"* SOURCE FILE: {a['src']}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _otio_time(value, fps):
    return {"OTIO_SCHEMA": "RationalTime.1", "value": round(float(value) * fps), "rate": fps}


def _otio_range(start, duration, fps):
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _otio_time(start, fps),
            "duration": _otio_time(duration, fps)}


def _otio_marker(name, start, end, notes, fps):
    return {"OTIO_SCHEMA": "Marker.2", "name": str(name), "marked_range": _otio_range(start, end - start, fps),
            "color": "GREEN", "metadata": {"aistudio": {"notes": str(notes)}}}


def export_otio(edit, files, probes):
    """OpenTimelineIO JSON for video/audio tracks, transitions and title/caption markers."""
    video, audio = edit["tracks"]["video"], edit["tracks"]["audio"]
    if not video:
        raise EditError("Add at least one video clip before exporting")
    fps = edit["fps"]

    def clip(src, name, source_in, source_out):
        if src not in files:
            raise EditError(f"file not found: {src}")
        path = Path(files[src]).resolve()
        duration = max(0, round((source_out - source_in) * fps))
        media_duration = (probes.get(src) or {}).get("duration")
        available = float(media_duration) if isinstance(media_duration, (int, float)) and media_duration > 0 else source_out
        return {"OTIO_SCHEMA": "Clip.2", "name": name,
                "media_reference": {"OTIO_SCHEMA": "ExternalReference.1", "target_url": path.as_uri(),
                                    "available_range": _otio_range(0, available, fps), "metadata": {}},
                "source_range": _otio_range(source_in, duration / fps, fps),
                "effects": [], "markers": [], "metadata": {}}

    spans = timeline_spans(video)
    vchildren = []
    for index, (item, (si, so, ri, ro, td)) in enumerate(zip(video, spans)):
        if index and spans[index][4] > 0:
            half = round(spans[index][4] * fps) / (2 * fps)
            vchildren.append({"OTIO_SCHEMA": "Transition.1", "name": "Dissolve", "transition_type": "SMPTE_Dissolve",
                              "in_offset": _otio_time(half, fps), "out_offset": _otio_time(half, fps), "metadata": {}})
        vchildren.append(clip(item["src"], Path(item["src"]).name, si, so))
    markers = []
    for item in edit["tracks"].get("text", []):
        markers.append(_otio_marker(item.get("text", "Text"), item["start"], item["end"], item.get("text", ""), fps))
    for item in _cue_list(edit["tracks"].get("subtitles") or {}):
        markers.append(_otio_marker(item.get("text", "Caption"), item["start"], item["end"], item.get("text", ""), fps))
    video_track = {"OTIO_SCHEMA": "Track.1", "name": "Video", "kind": "Video", "children": vchildren,
                   "source_range": None, "effects": [], "markers": markers, "metadata": {}}
    achildren, cursor = [], 0
    for item in audio:
        start_frame = round(item["start"] * fps)
        if start_frame > cursor:
            achildren.append({"OTIO_SCHEMA": "Gap.1", "name": "Gap", "duration": _otio_time((start_frame - cursor) / fps, fps),
                              "effects": [], "markers": [], "metadata": {}})
        achildren.append(clip(item["src"], Path(item["src"]).name, item["in"], item["out"]))
        cursor = start_frame + round((item["out"] - item["in"]) * fps)
    audio_track = {"OTIO_SCHEMA": "Track.1", "name": "Audio", "kind": "Audio", "children": achildren,
                   "source_range": None, "effects": [], "markers": [], "metadata": {}}
    timeline = {"OTIO_SCHEMA": "Timeline.1", "name": _project_name(files),
                "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": [video_track, audio_track],
                           "source_range": None, "effects": [], "markers": [], "metadata": {}},
                "global_start_time": _otio_time(0, fps), "metadata": {}}
    return json.dumps(timeline, indent=2) + "\n"


def export_otioz(pdir, edit, files, probes):
    """A portable OTIO archive with project media and archive-relative references."""
    from io import BytesIO
    root = Path(pdir).resolve()
    timeline = json.loads(export_otio(edit, files, probes))
    by_url = {Path(path).resolve().as_uri(): src for src, path in files.items()}
    media = {}
    def rewrite(node):
        if isinstance(node, dict):
            ref = node.get("media_reference")
            if isinstance(ref, dict) and ref.get("target_url") in by_url:
                src = by_url[ref["target_url"]]
                path = (root / src).resolve()
                try:
                    path.relative_to(root)
                except ValueError:
                    raise EditError("media is outside the project") from None
                if not path.is_file():
                    raise EditError(f"file not found: {src}")
                member = "media/" + Path(src).as_posix()
                media[member] = path
                ref["target_url"] = member
            for value in node.values():
                rewrite(value)
        elif isinstance(node, list):
            for value in node:
                rewrite(value)
    rewrite(timeline)
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.otio", json.dumps(timeline, indent=2) + "\n")
        for member, path in media.items():
            archive.write(path, member)
    return out.getvalue()


def export_xmeml(edit, files, probes):
    """Final Cut Pro 7 XML (xmeml version 4), with one video track, audio tracks and dissolve transition items."""
    import xml.etree.ElementTree as ET
    video, audio = edit["tracks"]["video"], edit["tracks"]["audio"]
    if not video:
        raise EditError("Add at least one video clip before exporting")
    fps = edit["fps"]
    root = ET.Element("xmeml", version="4")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    ET.SubElement(seq, "name").text = _project_name(files)
    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(fps)
    ET.SubElement(rate, "ntsc").text = "FALSE"
    spans = timeline_spans(video)
    duration = round(spans[-1][3] * fps)
    ET.SubElement(seq, "duration").text = str(duration)
    media = ET.SubElement(seq, "media")

    def file_element(parent, src, has_video):
        if src not in files:
            raise EditError(f"file not found: {src}")
        fid = "file-" + re.sub(r"[^A-Za-z0-9_-]", "_", src)
        f = ET.SubElement(parent, "file", id=fid)
        ET.SubElement(f, "name").text = Path(src).name
        ET.SubElement(f, "pathurl").text = Path(files[src]).resolve().as_uri()
        fr = ET.SubElement(f, "rate")
        ET.SubElement(fr, "timebase").text = str(fps)
        ET.SubElement(fr, "ntsc").text = "FALSE"
        fallback = max([c["out"] for c in video if c["src"] == src] +
                       [a["out"] for a in audio if a["src"] == src] + [1.0])
        source_duration = float((probes.get(src) or {}).get("duration") or fallback)
        ET.SubElement(f, "duration").text = str(round(source_duration * fps))
        return fid

    vmedia = ET.SubElement(media, "video")
    vtrack = ET.SubElement(vmedia, "track")
    for index, (item, (si, so, ri, ro, td)) in enumerate(zip(video, spans), 1):
        if index > 1 and td > 0:
            transition = ET.SubElement(vtrack, "transitionitem")
            ET.SubElement(transition, "start").text = str(round(ri * fps))
            ET.SubElement(transition, "end").text = str(round((ri + td) * fps))
            ET.SubElement(transition, "alignment").text = "center"
            effect = ET.SubElement(transition, "effect")
            ET.SubElement(effect, "name").text = "Cross Dissolve"
            ET.SubElement(effect, "effectid").text = "crossdissolve"
        ci = ET.SubElement(vtrack, "clipitem", id=f"video-{index}")
        ET.SubElement(ci, "name").text = Path(item["src"]).name
        ET.SubElement(ci, "duration").text = str(round((so - si) * fps))
        cr = ET.SubElement(ci, "rate")
        ET.SubElement(cr, "timebase").text = str(fps)
        ET.SubElement(cr, "ntsc").text = "FALSE"
        for tag, val in (("start", ri), ("end", ro), ("in", si), ("out", so)):
            ET.SubElement(ci, tag).text = str(round(val * fps))
        fid = file_element(ci, item["src"], True)
        ET.SubElement(ci, "link")
    amedia = ET.SubElement(media, "audio")
    for index, item in enumerate(audio, 1):
        track = ET.SubElement(amedia, "track")
        ci = ET.SubElement(track, "clipitem", id=f"audio-{index}")
        ET.SubElement(ci, "name").text = Path(item["src"]).name
        ET.SubElement(ci, "duration").text = str(round((item["out"] - item["in"]) * fps))
        ar = ET.SubElement(ci, "rate")
        ET.SubElement(ar, "timebase").text = str(fps)
        ET.SubElement(ar, "ntsc").text = "FALSE"
        for tag, val in (("start", item["start"]), ("end", item["start"] + item["out"] - item["in"]),
                         ("in", item["in"]), ("out", item["out"])):
            ET.SubElement(ci, tag).text = str(round(val * fps))
        file_element(ci, item["src"], False)
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def _summary(pdir, edit, files, probes):
    """timeline_summary.json of the bundle: the whole timeline in one readable document."""
    video, audio, subs = edit["tracks"]["video"], edit["tracks"]["audio"], edit["tracks"].get("subtitles") or {}
    spans = timeline_spans(video)
    return {"project": Path(pdir).name, "aspect": edit["aspect"], "fps": edit["fps"],
            "duration": round(spans[-1][3], 3) if spans else 0.0,
            "filter": edit["filter"], "effect": edit["effect"], "background": edit["background"],
            "clips": [{"id": c["id"], "src": c["src"], "file": str(files.get(c["src"], "")),
                       "in": c["in"], "out": c["out"], "start": round(ri, 3), "end": round(ro, 3),
                       "transition": c["transition"]} for c, (_, _, ri, ro, _) in zip(video, spans)],
            "audio": [{"id": a["id"], "src": a["src"], "start": a["start"], "in": a["in"], "out": a["out"], "volume": a["volume"]} for a in audio],
            "subtitles": {"style": subs.get("style", "classic"), "cues": len(subs.get("cues", []))},
            "files": [{"src": src, "present": Path(f).is_file(), "duration": round((probes.get(src) or {}).get("duration") or 0, 3),
                       "audio": bool((probes.get(src) or {}).get("audio"))} for src, f in sorted(files.items())],
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def export_bundle(pdir, edit, files):
    """The Canva / Google Vids zip: the media the timeline uses, captions.srt and captions.vtt, the NLE timeline (fcpxml + edl),
    timeline_summary.json and the newest rendered preview as storyboard_guide.mp4 when the project has one.
    The clips are the project files themselves (the trims live in timeline_summary.json), so nothing is re-encoded.
    Returns the zip path: the caller downloads it and deletes it."""
    pdir = Path(pdir)
    video, subs = edit["tracks"]["video"], edit["tracks"].get("subtitles") or {}
    if not video:
        raise EditError("Add at least one video clip before exporting")
    probes = {c["src"]: probe(files[c["src"]]) for c in video if c["src"] in files}
    fd, tmp = tempfile.mkstemp(prefix="aistudio-bundle-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, f in sorted(files.items()):
                if Path(f).is_file():
                    z.write(f, rel)
            z.writestr("captions.srt", export_srt(subs))
            z.writestr("captions.vtt", export_vtt(subs))
            z.writestr("timeline.fcpxml", export_fcpxml(edit, files, probes))
            z.writestr("timeline.edl", export_edl(edit, files))
            z.writestr("timeline.otio", export_otio(edit, files, probes))
            z.writestr("timeline.xml", export_xmeml(edit, files, probes))
            z.writestr("timeline_summary.json", json.dumps(_summary(pdir, edit, files, probes), indent=2))
            previews = sorted((pdir / "exports").glob("*.mp4")) if (pdir / "exports").is_dir() else []
            if previews:
                z.write(previews[-1], "storyboard_guide.mp4")
        return tmp
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
