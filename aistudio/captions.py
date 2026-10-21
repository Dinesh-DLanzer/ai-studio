"""Captions: the KNOWN script -> timed cues -> the text track (TText) for edit.json.

Pure module: nothing is written, no provider is called, no network.  The caption text always comes
from the KNOWN script (the voice lines of Story.md / shots.json); only the TIMING comes from a
transcriber's word timestamps, and only when a transcriber gave them.  Words are never invented:
if the transcription heard something the script does not say, the script wins and the extra words
are dropped.

Two ways to time a caption:
  * word timestamps exist -> the script is aligned to them (Needleman-Wunsch over normalised
    tokens), so every caption word gets the time of the word it matched.  Script words the
    transcriber missed get the time of the gap they sit in.
  * no word timestamps -> the script's words are spread evenly over the voiceover duration.

Language care: a caption is broken at word boundaries, and a word that is too long for one line is
broken inside the word only at a grapheme-cluster boundary, so a Tamil vowel sign (a combining mark)
never ends up on the next line without its consonant.

Contract (tests in tests/test_captions.py):
  build_cues(script_text, words=None, duration=None, max_chars=42, max_lines=2) -> [{"text","start","end"}]
      words: [{"text","start","end"}] (whisper.cpp, ElevenLabs).  Cue times never go backwards and
      every cue lasts at least MIN_CUE seconds (the editor's minimum text item length).
  wrap_text(text, max_chars=42, max_lines=2) -> str
      The cue text, wrapped into at most max_lines lines of at most max_chars characters.
  to_text_track(cues, style=None) -> [text item]
      The cues as the editor's text items (TText): the format's or brand kit's caption style, fonts
      only from assets/fonts.  The items go through the editor's own clean() so they are valid.
  place_voiceover(edit, shot_id, audio_rel, duration) -> patch
      Where a voiceover clip goes under its shot (pure: a patch + warnings, never a file).
  preview(pdir, shot_id, ...) -> {"shot", "script", "source", "duration", "cues"}
      Read-only: the cues of one shot from its voice line (or the english gloss).
"""
import difflib
import json
import re
import unicodedata
from pathlib import Path

MIN_CUE = 0.2                 # the editor's shortest text item (clean() refuses less)
MAX_CUE_CHARS = 100           # the editor's longest text item
DEFAULT_MAX_CHARS = 42
DEFAULT_MAX_LINES = 2

# punctuation that never carries meaning of its own: stripped before two tokens are compared
_PUNCT = " \t\n.,!?;:\"'“”‘’()[]{}<>…«»-–—_/\\|"
# the marks that close a sentence (Tamil: ௹ the full stop, । the danda)
_SENTENCE_END = ".!?。！？।॥௹۔؟…"
# the marks that close a clause (a good place to break a caption)
_CLAUSE_END = ",;:،؛、-–—()[]{}\"“”‘’"

_ZWJ = "‍"                       # the zero width joiner (a letter and the next one are one cluster)


# ---------------------------------------------------------------- text helpers
def tokens(text):
    """The script's words (whitespace separated, punctuation kept)."""
    return [t for t in re.split(r"\s+", (text or "").strip()) if t]


def _norm(tok):
    """A token reduced to what matters for comparing two words: no case, no surrounding punctuation."""
    return tok.strip().strip(_PUNCT).strip().lower()


def _is_sentence_end(tok):
    return bool(tok) and tok[-1] in _SENTENCE_END


def _is_clause_end(tok):
    return bool(tok) and tok[-1] in _CLAUSE_END


def _combining(ch):
    """True for a mark that belongs to the letter before it (a Tamil vowel sign, a dot above)."""
    return unicodedata.combining(ch) != 0 or unicodedata.category(ch) in ("Mn", "Mc", "Me")


def _safe_breaks(text):
    """The indexes where a long word may be cut: never between a letter and its combining marks,
    never right after a zero-width joiner, never between two regional indicator symbols."""
    out = []
    for i in range(1, len(text)):
        if _combining(text[i]):
            continue
        if text[i - 1] == _ZWJ:
            continue
        out.append(i)
    return out


def split_word(word, limit):
    """A word that is too long for one line, cut only at grapheme-cluster boundaries.
    The cut is the last cluster boundary that still fits; when no boundary fits, the next one is
    used (the piece is longer than the limit, but no letter loses its mark)."""
    if len(word) <= limit or limit <= 0:
        return [word]
    breaks = _safe_breaks(word)
    pieces, start = [], 0
    while len(word) - start > limit:
        fits = [b for b in breaks if start < b <= start + limit]
        if fits:
            cut = fits[-1]
        else:
            later = [b for b in breaks if b > start + limit]
            if not later:
                break
            cut = later[0]
        pieces.append(word[start:cut])
        start = cut
    pieces.append(word[start:])
    return [p for p in pieces if p]


def wrap_lines(words, max_chars=DEFAULT_MAX_CHARS):
    """The words as lines of at most max_chars characters (a too long word is cut safely)."""
    lines, cur = [], ""
    for word in words:
        for piece in (split_word(word, max_chars) if len(word) > max_chars else [word]):
            if not cur:
                cur = piece
            elif len(cur) + 1 + len(piece) <= max_chars:
                cur += " " + piece
            else:
                lines.append(cur)
                cur = piece
    if cur:
        lines.append(cur)
    return lines


def wrap_text(text, max_chars=DEFAULT_MAX_CHARS, max_lines=DEFAULT_MAX_LINES):
    """The caption text: at most max_lines lines of at most max_chars characters."""
    lines = wrap_lines(tokens(text), max_chars)[:max_lines] if max_lines and max_lines > 0 else wrap_lines(tokens(text), max_chars)
    return "\n".join(lines)


def _cap_text(text, limit=MAX_CUE_CHARS):
    """Shorten a cue text to what the editor accepts, at a line break if there is one.
    The cut never separates a letter from its combining marks."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if _combining(text[limit]):                 # the mark of the last letter was cut away
        j = limit - 1
        while j >= 0 and _combining(text[j]):
            j -= 1
        cut = text[:j]
    brk = cut.rfind("\n")
    if brk > limit // 2:
        cut = cut[:brk]
    else:
        sp = cut.rfind(" ")
        if sp > limit // 2:
            cut = cut[:sp]
    return cut.rstrip()


# ---------------------------------------------------------------- alignment (pure)
def _similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _nw(a, b):
    """Needleman-Wunsch over two token lists: the matched pairs [(i, j)], in order.
    A pair is only made when the two tokens are similar enough (a different word costs more than a
    gap), so a transcription that heard something else does not steal the script's word."""
    n, m = len(a), len(b)
    gap = -0.8
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + gap
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = _similarity(a[i - 1], b[j - 1])
            diag = score[i - 1][j - 1] + (2.0 * s if s >= 0.6 else -1.0)
            score[i][j] = max(diag, score[i - 1][j] + gap, score[i][j - 1] + gap)
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            s = _similarity(a[i - 1], b[j - 1])
            diag = score[i - 1][j - 1] + (2.0 * s if s >= 0.6 else -1.0)
            if abs(score[i][j] - diag) < 1e-9:
                pairs.append((i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and abs(score[i][j] - (score[i - 1][j] + gap)) < 1e-9:
            i -= 1
            continue
        j -= 1
    pairs.reverse()
    return pairs


def _word_times(words):
    """The word timestamps as floats, keeping only the usable ones."""
    out = []
    for w in words or []:
        if not isinstance(w, dict):
            continue
        try:
            start, end = float(w.get("start", 0.0)), float(w.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        text = str(w.get("text") or "").strip()
        if not text:
            continue
        out.append({"text": text, "start": start, "end": max(end, start)})
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out


def _even_times(n, duration):
    """The words spread evenly over the voiceover."""
    if n <= 0:
        return []
    step = float(duration) / n
    return [(i * step, (i + 1) * step) for i in range(n)]


def _token_times(n, words, pairs, duration):
    """start/end per script token: the matched word's own times, or the gap it sits in."""
    times = [None] * n
    match = dict(pairs)
    for i, j in match.items():
        times[i] = (words[j]["start"], words[j]["end"])
    matched = sorted(match)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        prev = max([k for k in matched if k < i], default=None)
        nxt = min([k for k in matched if k >= j], default=None)
        lo = times[prev][1] if prev is not None else 0.0
        if nxt is not None:
            hi = times[nxt][0]
        else:
            hi = max([w["end"] for w in words], default=lo)
            if duration:
                hi = max(hi, float(duration))
        hi = max(hi, lo)
        step = (hi - lo) / (j - i)
        for k in range(i, j):
            times[k] = (lo + step * (k - i), lo + step * (k - i + 1))
        i = j
    return times


# ---------------------------------------------------------------- the cues
def _group(toks, max_chars, max_lines):
    """The token indexes of every cue: broken at sentence ends, at clause ends and at the line limit."""
    groups, cur = [], []

    def text_of(idxs):
        return " ".join(toks[i] for i in idxs)

    def lines_of(idxs):
        return len(wrap_lines([toks[i] for i in idxs], max_chars))

    for idx, tok in enumerate(toks):
        trial = cur + [idx]
        if cur and lines_of(trial) > max_lines:
            groups.append(cur)
            cur = [idx]
        else:
            cur = trial
        if _is_sentence_end(tok):
            groups.append(cur)
            cur = []
        elif _is_clause_end(tok) and cur and len(text_of(cur)) >= max_chars * 0.5:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_cues(script_text, words=None, duration=None, max_chars=DEFAULT_MAX_CHARS, max_lines=DEFAULT_MAX_LINES):
    """The caption cues of one voiceover.

    script_text: the known script (the voice line).  It is the only source of caption text.
    words: [{"text","start","end"}] word timestamps, when a transcriber gave them.  The script is
      aligned to them and takes their timing.  Without them the words are spread evenly over
      `duration` seconds.
    duration: the length of the voiceover (needed for the even spread).
    max_chars: the characters one caption line may hold.  max_lines: the lines one caption may hold.

    Returns [{"text","start","end"}] with times that never go backwards."""
    toks = tokens(script_text)
    if not toks:
        return []
    max_chars = max(4, int(max_chars or DEFAULT_MAX_CHARS))
    max_lines = max(1, int(max_lines or DEFAULT_MAX_LINES))
    stamps = _word_times(words)
    if stamps:
        pairs = _nw([_norm(t) for t in toks], [_norm(w["text"]) for w in stamps])
        times = _token_times(len(toks), stamps, pairs, duration)
    else:
        span = float(duration or 0.0)
        if span <= 0:
            span = float(len(toks)) * 0.4
        times = _even_times(len(toks), span)
    cues = []
    for group in _group(toks, max_chars, max_lines):
        start = times[group[0]][0]
        end = times[group[-1]][1]
        text = _cap_text("\n".join(wrap_lines([toks[i] for i in group], max_chars)))
        if not text.strip():
            continue
        cues.append({"text": text, "start": float(start), "end": float(end)})
    return _finalize(cues)


def _finalize(cues):
    """Round the times, keep them monotonic and every cue at least MIN_CUE long."""
    out, prev_start, prev_end = [], 0.0, 0.0
    for c in cues:
        start = max(0.0, round(float(c["start"]), 3))
        end = round(float(c["end"]), 3)
        if end < start:
            end = start
        if end - start < MIN_CUE:
            end = round(start + MIN_CUE, 3)
        if start < prev_start:
            start = prev_start
        if end < prev_end:
            end = prev_end
        if end <= start:
            end = round(start + MIN_CUE, 3)
        out.append({"text": c["text"], "start": start, "end": end})
        prev_start, prev_end = start, end
    return out


# ---------------------------------------------------------------- the text track
def _hex(value):
    """A #rrggbb colour (a brand kit may carry an alpha: it is dropped, the editor has no alpha)."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v.startswith("#"):
        return None
    v = v[1:]
    if len(v) == 8:
        v = v[:6]
    if len(v) != 6:
        return None
    try:
        int(v, 16)
    except ValueError:
        return None
    return "#" + v.lower()


def caption_style(style=None):
    """The caption style of a format or a brand kit, normalised for the editor's text items.
    Fonts come from the editor's font list (the files in assets/fonts); anything else falls back."""
    from aistudio import editor          # local import: the editor imports this module
    st = style if isinstance(style, dict) else {}
    family = str(st.get("font") or "").strip()
    if family not in editor.FONTS:
        family = "Poppins"
    weights = editor.FONTS[family]["weights"]
    try:
        weight = int(st.get("weight") or 700)
    except (TypeError, ValueError):
        weight = 700
    if weight not in weights:
        weight = 700 if 700 in weights else (400 if 400 in weights else next(iter(weights)))
    try:
        size = float(st.get("size") or 46)
    except (TypeError, ValueError):
        size = 46.0
    size = min(300.0, max(8.0, size))
    try:
        y = float(st.get("y")) if st.get("y") is not None else 0.86
    except (TypeError, ValueError):
        y = 0.86
    y = min(1.0, max(0.0, y))
    return {"font": family, "weight": weight, "size": size, "y": y,
            "color": _hex(st.get("color")) or "#ffffff", "bg": _hex(st.get("bg"))}


def style_from_format(format_id):
    """The caption style of a format (templates/formats/<id>.json): {font, size, weight, y, bg}."""
    from aistudio import formats
    return dict(formats.get_format(format_id).get("caption") or {})


def style_from_kit(kit):
    """The caption style of a brand kit: the kit document (or the path of its kit.json)."""
    data = kit
    if isinstance(kit, (str, Path)):
        data = json.loads(Path(kit).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return dict(data.get("caption") or {})


def to_text_track(cues, style=None, prefix="cap"):
    """The cues as the editor's text items (TText), ready for edit.json.
    The items go through the editor's own clean(), so they are valid by construction."""
    from aistudio import editor          # local import: the editor imports this module
    st = caption_style(style)
    items = []
    for n, cue in enumerate(cues or [], 1):
        text = str(cue.get("text", "")).strip()
        if not text:
            continue
        items.append({
            "id": f"{prefix}{n}",
            "text": text,
            "start": float(cue.get("start", 0.0)),
            "end": float(cue.get("end", 0.0)),
            "x": 0.5, "y": st["y"],
            "font": st["font"], "weight": st["weight"], "size": st["size"],
            "color": st["color"], "bg": st["bg"],
            "align": "center", "bold": st["weight"] >= 600, "italic": False, "underline": False,
            "caps": False, "opacity": 1.0,
            "shadow": {"on": True, "color": "#000000", "blur": 14},
        })
    if not items:
        return []
    return editor.clean({"tracks": {"text": items}})["tracks"]["text"]


def with_captions(edit, cues, style=None):
    """The edit with the caption cues as its text track (a new edit list; nothing is written)."""
    from aistudio import editor          # local import: the editor imports this module
    doc = json.loads(json.dumps(edit))    # a copy: the caller's edit is not touched
    tracks = doc.setdefault("tracks", {})
    tracks["text"] = to_text_track(cues, style)
    return editor.clean(doc)


# ---------------------------------------------------------------- voiceover placement
def place_voiceover(edit, shot_id, audio_rel, duration, max_speed=1.12):
    """Where a voiceover clip goes under its shot.  Pure: returns a patch and warnings.

    The clip is placed at the shot's own place on the timeline (transitions included).  When the
    voiceover is longer than the shot it may be sped up, but only within +-12%: a line that needs
    more than that is reported as "speech too long for the clip" and the caller decides whether to
    extend the shot or to shorten the line."""
    from aistudio import editor          # local import: the editor imports this module
    video = (edit.get("tracks") or {}).get("video") or []
    index = next((n for n, c in enumerate(video) if c.get("id") == shot_id), None)
    if index is None:
        raise ValueError(f"no clip for shot {shot_id} in this timeline")
    spans = editor.timeline_spans(video)
    span_start, span_end = spans[index][2], spans[index][3]
    span = max(0.05, span_end - span_start)
    src = editor.safe_rel(audio_rel, "audio", editor.AUDIO_SUFFIX)
    length = max(0.0, float(duration or 0.0))
    warnings, speed, fits = [], 1.0, True
    if length > span + 0.01:
        needed = length / span
        if needed <= float(max_speed) + 1e-9:
            speed = round(needed, 4)
            warnings.append(f"the voiceover is {length:.2f}s but the shot is {span:.2f}s: it is sped up to {speed:.2f}x to fit")
        else:
            fits = False
            warnings.append(f"speech too long for the clip: the voiceover is {length:.2f}s but the shot is only {span:.2f}s "
                            f"(it would need {needed:.2f}x, more than the {max_speed:.2f}x limit): extend the shot or shorten the line")
    clip = {"id": f"vo_{shot_id}", "src": src, "start": round(span_start, 3), "in": 0.0,
            "out": round(length / speed, 3) if speed > 1 else round(min(length, span), 3),
            "volume": 1.0, "fadeIn": 0.0, "fadeOut": 0.0, "name": f"voiceover {shot_id}",
            "speed": speed}
    return {"patch": {"tracks": {"audio": [clip]}},
            "shot": {"id": shot_id, "start": round(span_start, 3), "end": round(span_end, 3)},
            "speed": speed, "fits": fits, "warnings": warnings}


def apply_patch(edit, patch):
    """The edit with a patch applied (pure: a new edit list).  The patch is what place_voiceover
    returns, or the inner 'patch' part of it."""
    inner = patch.get("patch") if isinstance(patch, dict) and "patch" in patch else patch
    doc = json.loads(json.dumps(edit))
    tracks = doc.setdefault("tracks", {})
    for kind, items in ((inner or {}).get("tracks") or {}).items():
        tracks.setdefault(kind, [])
        tracks[kind] = list(tracks[kind]) + list(items)
    return doc


# ---------------------------------------------------------------- read-only preview
def _shots(pdir):
    path = Path(pdir) / "shots.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _story_shot(pdir, shot_id):
    """The shot of Story.md (the voice lines live there).  {} when there is no story."""
    path = Path(pdir) / "Story.md"
    if not path.is_file():
        return {}
    try:
        from aistudio.storyboard import convert
        story = convert.parse_story(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    for shot in story.get("shots", []):
        if shot.get("id") == shot_id:
            return shot
    return {}


def shot_script(pdir, shot_id):
    """The spoken line of one shot: {"script","source"} where source is voice_line or english."""
    shot = next((s for s in (_shots(pdir).get("shots") or []) if s.get("id") == shot_id), {})
    line = str(shot.get("voice_line") or "").strip()
    english = str(shot.get("english") or "").strip()
    source = "voice_line"
    if not line:
        story = _story_shot(pdir, shot_id)
        line = str(story.get("voice_line") or "").strip()
        english = english or str(story.get("english") or "").strip()
    if not line and english:
        line, source = english, "english"
    return {"script": line, "source": source if line else "", "english": english}


def preview(pdir, shot_id, duration=None, max_chars=DEFAULT_MAX_CHARS, max_lines=DEFAULT_MAX_LINES, words=None):
    """Read-only: the caption cues of one shot.  Nothing is written and no provider is called."""
    shots = _shots(pdir)
    shot = next((s for s in (shots.get("shots") or []) if s.get("id") == shot_id), {})
    found = shot_script(pdir, shot_id)
    length = duration
    if not length:
        try:
            length = float(shot.get("seconds") or 0) or None
        except (TypeError, ValueError):
            length = None
    if not length:
        length = _edit_span(pdir, shot_id)
    cues = build_cues(found["script"], words=words, duration=length, max_chars=max_chars, max_lines=max_lines)
    return {"shot": shot_id, "script": found["script"], "source": found["source"],
            "english": found["english"], "duration": round(float(length), 3) if length else 0.0,
            "cues": cues}


def _edit_span(pdir, shot_id):
    """How long the shot is on the timeline (the saved edit), 0 when it is not there."""
    from aistudio import editor          # local import: the editor imports this module
    path = Path(pdir) / "edit.json"
    if not path.is_file():
        return 0.0
    try:
        doc = editor.clean(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0.0
    video = doc["tracks"]["video"]
    index = next((n for n, c in enumerate(video) if c.get("id") == shot_id), None)
    if index is None:
        return 0.0
    spans = editor.timeline_spans(video)
    return round(spans[index][3] - spans[index][2], 3)
