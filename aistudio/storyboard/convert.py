"""S1: parse a Story.md storyboard and convert it to shots.json / images.json content. Standard library only.

Story.md format (see templates/Story.md): a title line "# <name>: ...", then one block per shot:
    ## Shot 01 — 0:00–0:04            (heading: "## Shot <number>"; everything after the number is the time range)
    ### Purpose: HOOK
    **Visual**\\n<text lines>          (a bold label on its own line, then free text until the next bold label/heading)
    **Camera**, **Action**, **Voice**, **English**, **On-screen text**, **Image**, **AI Video Prompt** likewise.
    Lines starting with "> " inside a section are quotes; strip the "> " prefix.
The Voice label may carry a mode in the label line, e.g. "**Voice** (ON-CAMERA)" or "**Voice** (OFF-CAMERA)" or "**Voice** (SILENT)";
anything else defaults to "off-camera" if a voice line exists, else "silent".  The "**Image**" value is a single id (first word).

Contract (tests in tests/test_story_convert.py):
  parse_story(md: str) -> dict   {"title": str, "shots": [ {"id":"s01","number":1,"time":"0:00–0:04","purpose":"HOOK","visual":str,
      "camera":str,"action":str,"voice_mode":"on-camera|off-camera|silent","voice_line":str,"english":str,
      "on_screen_text":[str,...],"image":str,"prompt":str} ]}
     id is "s" + number zero-padded to 2 digits.  Missing sections give "" (or [] / "silent").  Text is stripped, inner lines joined
     with a single space (Tamil text preserved).  on_screen_text = the non-empty lines of that section (quote prefixes stripped).
     Raises ValueError if no "## Shot" heading is found.
  to_shots_doc(story: dict, model="google/veo-3.1-lite", seconds=4, resolution="720p") -> dict
     {"aspect_ratio":"9:16","audio":False,"shots":[ {"id","model","seconds","resolution","audio": voice_mode != "silent",
       "first_frame": "stills/<image>.png" (only when image is non-empty), "prompt": <see below>, "note": purpose + " " + time} ]}
     prompt = the shot's "prompt" text; if voice_mode != "silent" and voice_line: append
       ' AUDIO: ' + ("Speaker" if on-camera else "An off-camera narrator") + ' says this line in the project language, clearly, lips synced to the words: "' + voice_line + '" (' + english + ').'
     (exact string: for on-camera use  ' AUDIO: The speaker says this line, clearly, lips synced to the words: "<voice_line>" (<english>).'
      for off-camera use               ' AUDIO: An off-camera narrator says this line, clearly: "<voice_line>" (<english>).' ).
  to_images_doc(story: dict) -> dict
     {"style":"","images":[ one entry per distinct non-empty shot image id, in order: {"id","kind":"frame","out":"stills/<id>.png",
       "aspect_ratio":"9:16","refs":[],"prompt": shot visual text} ]}
"""
import re

_SHOT_RE = re.compile(r"^##\s+Shot\s+(\d+)\s*(.*)$", re.IGNORECASE)
_PURPOSE_RE = re.compile(r"^#+\s*Purpose\s*:?\s*(.*)$", re.IGNORECASE)
_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$")
_RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")
_LEAD_RE = re.compile(r"^[\s\-–—:]+")

_LABELS = {
    "visual": "visual",
    "camera": "camera",
    "action": "action",
    "voice": "voice",
    "voiceover": "voice",
    "voice over": "voice",
    "english": "english",
    "on-screen text": "on_screen_text",
    "on screen text": "on_screen_text",
    "image": "image",
    "ai video prompt": "prompt",
    "video prompt": "prompt",
    "prompt": "prompt",
    "purpose": "purpose",
    "uses": "uses",
    "use": "uses",
    "references": "uses",
    "refs": "uses",
}

_MODES = ("off-camera", "on-camera", "silent")


def _clean(raw):
    """Quote prefixes stripped, whitespace trimmed, empty lines dropped."""
    out = []
    for line in raw:
        line = line.strip()
        if line.startswith(">"):
            line = line[1:].strip()
        if line:
            out.append(line)
    return out


def _parse_shot(block):
    head = _SHOT_RE.match(block[0])
    number = int(head.group(1))
    time_range = _LEAD_RE.sub("", head.group(2)).strip()

    body, inline, key = {}, {}, None
    for line in block[1:]:
        if _RULE_RE.match(line):
            key = None
            continue
        if _SHOT_RE.match(line) or re.match(r"^#{1,2}\s", line):
            key = None
            continue
        m = _PURPOSE_RE.match(line)
        if m:
            key = "purpose"
            body.setdefault(key, [])
            if m.group(1).strip():
                inline[key] = m.group(1).strip()
            continue
        m = _BOLD_RE.match(line)
        if m:
            key = _LABELS.get(m.group(1).strip().lower().rstrip(":"))
            if key:
                body.setdefault(key, [])
                if m.group(2).strip():
                    inline[key] = m.group(2).strip()
            else:
                key = None
            continue
        if key:
            body[key].append(line)

    def text(name):
        return " ".join([inline[name]] if name in inline else [] + _clean(body.get(name, []))).strip()

    remainder, mode = inline.get("voice", ""), None
    for m in _MODES:
        if m in remainder.lower():
            mode = m
            remainder = re.sub(r"\([^)]*\)", "", remainder).strip()
            break
    voice_line = " ".join(_clean([remainder]) + _clean(body.get("voice", []))).strip()
    if mode is None:
        mode = "off-camera" if voice_line else "silent"

    image = (text("image").split() or [""])[0]
    uses = [slug(x) for x in re.split(r"[,;\s]+", re.sub(r"\([^)]*\)", "", text("uses"))) if x.strip()]
    return {
        "id": "s%02d" % number,
        "number": number,
        "time": time_range,
        "purpose": text("purpose"),
        "visual": text("visual"),
        "camera": text("camera"),
        "action": text("action"),
        "voice_mode": mode,
        "voice_line": voice_line,
        "english": text("english"),
        "on_screen_text": _clean(body.get("on_screen_text", [])),
        "image": image,
        "uses": [u for u in uses if u],
        "prompt": text("prompt"),
    }


def slug(name):
    """An asset id from a name: letters, digits and underscores only ("Ramesh (owner)" -> "ramesh_owner")."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:40]


_SECTIONS = {"shared style": "style", "style": "style", "characters": "characters", "character direction": "characters",
             "backgrounds": "backgrounds", "places": "backgrounds", "locations": "backgrounds", "settings": "backgrounds"}


def _parse_sections(lines):
    """Style text, characters and backgrounds from the sections that come outside the shots (## Shared style, ## Characters, ## Backgrounds)."""
    out = {"style": "", "characters": [], "backgrounds": []}
    kind, name, buf = None, None, []

    def flush():
        nonlocal name, buf
        if kind in ("characters", "backgrounds") and name and not re.search(r"[<>]", name):
            text = " ".join(x for x in _clean([re.sub(r"^[-*]\s+", "", b) for b in buf]) if "consistency rule" not in x.lower())
            out[kind].append({"name": name, "id": slug(name), "prompt": text})
        name, buf = None, []

    style_lines = []
    for line in lines:
        m = re.match(r"^(#{1,3})\s+(.*?)\s*$", line)
        if m and len(m.group(1)) <= 2:
            flush()
            kind = _SECTIONS.get(re.sub(r"[:\s]+$", "", m.group(2).strip().lower())) if len(m.group(1)) == 2 else None
            continue
        if kind == "style":
            style_lines.append(line)
        elif kind in ("characters", "backgrounds"):
            if m and len(m.group(1)) == 3:
                flush()
                name = m.group(2).strip()
            elif _RULE_RE.match(line):
                flush()
            else:
                buf.append(line)
    flush()
    out["style"] = " ".join(_clean(style_lines)).strip()
    return out


def parse_story(md):
    lines = (md or "").splitlines()
    title = ""
    for line in lines:
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            title = m.group(1).split(":")[0].strip()
            break
    starts = [i for i, line in enumerate(lines) if _SHOT_RE.match(line)]
    if not starts:
        raise ValueError("no '## Shot' heading found")
    shots = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        shots.append(_parse_shot(lines[i:end]))
    sec = _parse_sections(lines)
    used, seen = {sh["image"] for sh in shots if sh.get("image")}, set()
    for kind in ("characters", "backgrounds"):
        for item in sec[kind]:
            base, n = item["id"] or kind[:-1], 2
            while base in used or base in seen:
                base, n = "%s_%d" % (item["id"] or kind[:-1], n), n + 1
            item["id"] = base
            seen.add(base)
    return {"title": title, "shots": shots, "style": sec["style"], "characters": sec["characters"], "backgrounds": sec["backgrounds"]}


def _audio_suffix(shot, language=None):
    if shot.get("voice_mode") == "silent" or not shot.get("voice_line"):
        return ""
    spoken = '"%s" (%s).' % (shot["voice_line"], shot.get("english", ""))
    lang = " in %s" % language if language else ""      # tells the video model which language to speak
    if shot["voice_mode"] == "on-camera":
        return " AUDIO: The speaker says this line%s, clearly, lips synced to the words: " % lang + spoken
    return " AUDIO: An off-camera narrator says this line%s, clearly: " % lang + spoken


def to_shots_doc(story, model="google/veo-3.1-lite", seconds=4, resolution="720p", language=None):
    shots = []
    for shot in story.get("shots", []):
        entry = {
            "id": shot["id"],
            "model": model,
            "seconds": seconds,
            "resolution": resolution,
            "audio": shot.get("voice_mode", "silent") != "silent",
        }
        if shot.get("image"):
            entry["first_frame"] = "stills/%s.png" % shot["image"]
        entry["prompt"] = shot.get("prompt", "") + _audio_suffix(shot, language)
        entry["note"] = ("%s %s" % (shot.get("purpose", ""), shot.get("time", ""))).strip()
        shots.append(entry)
    doc = {"aspect_ratio": "9:16", "audio": False, "shots": shots}
    if language:
        doc["language"] = language
    return doc


def to_images_doc(story, known_ids=()):
    """images.json content: character masters, then background masters, then one frame per shot image (its refs are the characters / places the
    shot uses).  known_ids = ids of assets that already exist (for example uploads) and may also be referenced."""
    images, ids = [], set()
    for kind, key in (("character", "characters"), ("background", "backgrounds")):
        for item in story.get(key, []):
            ids.add(item["id"])
            images.append({"id": item["id"], "kind": kind, "out": "stills/%s.png" % item["id"], "aspect_ratio": "9:16", "refs": [],
                           "prompt": item.get("prompt") or item.get("name", "")})
    allowed = ids | set(known_ids)
    seen = set()
    for shot in story.get("shots", []):
        image_id = shot.get("image") or ""
        if not image_id or image_id in seen:
            continue
        seen.add(image_id)
        images.append({
            "id": image_id,
            "kind": "frame",
            "out": "stills/%s.png" % image_id,
            "aspect_ratio": "9:16",
            "refs": [r for r in shot.get("uses", []) if r in allowed and r != image_id][:4],
            "prompt": shot.get("visual", ""),
        })
    return {"style": story.get("style", ""), "images": images}
