"""Recipes (plan 20): one-click tools as data files in catalog/recipes/<id>.json.

A recipe is a declarative list of steps. plan() turns it into ONE awaiting-approval batch (the plan 10 mechanism): a human approves the exact
total, then the batch runner executes the steps as ledger jobs, re-checking model, price and request of every item. A recipe never approves,
spends or runs anything by itself. Placeholders are pure string substitution of validated inputs: no eval, no code, a substituted value is
never scanned again, so '{x}' typed by a user stays literal text.
"""
import hashlib
import json
import re
import secrets
from pathlib import Path

from aistudio import consent as consent_mod, costlog, formats, project as project_mod, tools as tools_mod
from aistudio.domain import spec as spec_mod
from aistudio.domain.common import ServiceError

DIR = Path(__file__).resolve().parent.parent / "catalog" / "recipes"
KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")
INPUT_TYPES = ("image", "text", "choice", "number", "audio")
CONSENT = ("none", "if-real-person", "required")
STEP_KEYS = {"id", "task", "optional", "when", "source", "prompt", "seconds", "direction", "params", "clips", "audio", "text", "aspect", "mode", "export"}
RECIPE_KEYS = {"id", "label", "category", "description", "inputs", "format", "steps", "consent", "requires"}
INPUT_KEYS = {"key", "type", "required", "max", "min", "options", "label"}
TEXT_CAP, PROMPT_CAP = 2000, 1500
IMAGE_SUFFIX, AUDIO_SUFFIX = (".png", ".jpg", ".jpeg", ".webp"), (".mp3", ".wav", ".m4a")
EDIT_MODES = ("inpaint_insertion", "inpaint_removal", "outpaint", "bgswap")
# paid generative tasks that exist TODAY: task -> (role, adapter method that implements it, batch item kind)
PAID = {"text_to_image": ("image", "image", "image"), "image_edit": ("image", "image_edit", "image_edit"),
        "image_to_video": ("video", "video_submit", "clip"), "video_extend": ("video", "video_extend", "clip_extend")}
FREE = ("assemble", "reframe")
TEXT_FIELDS = ("prompt", "text")          # may reference text/choice/number inputs only
REF_FIELDS = ("source", "clips", "audio")  # whole-value references to a file input or an earlier step


class RecipeError(ServiceError):
    pass


def _bad(rid, msg):
    raise RecipeError(f"recipe {rid}: {msg}")


def presets():
    try:
        return {x["id"] for x in json.loads((DIR.parent / "camera_presets.json").read_text(encoding="utf-8"))["presets"]}
    except (OSError, ValueError, KeyError):
        return set()


def _strings(value):
    """Every string inside a prompt/text value (text overlays are lists of objects)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for x in value:
            yield from _strings(x)
    elif isinstance(value, dict):
        for x in value.values():
            yield from _strings(x)


def validate(doc, rid=None):
    """Strict schema check of one recipe document; returns it unchanged or raises RecipeError. Unknown keys and unknown placeholders are errors."""
    rid = rid or (doc.get("id") if isinstance(doc, dict) else "?")
    if not isinstance(doc, dict):
        _bad(rid, "must be an object")
    extra = set(doc) - RECIPE_KEYS
    if extra:
        _bad(rid, f"unknown key(s) {sorted(extra)}")
    for k in ("id", "label", "category"):
        if not isinstance(doc.get(k), str) or not doc[k].strip():
            _bad(rid, f"{k} must be a non-empty string")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", doc["id"]):
        _bad(rid, "id must be kebab-case")
    if doc.get("consent", "none") not in CONSENT:
        _bad(rid, f"consent must be one of {CONSENT}")
    if doc.get("format"):
        try:
            formats.get_format(doc["format"])
        except Exception:
            _bad(rid, f"unknown format {doc['format']!r}")
    if not isinstance(doc.get("requires", []), list) or not all(isinstance(x, str) for x in doc.get("requires", [])):
        _bad(rid, "requires must be a list of task names")
    inputs = {}
    for i in doc.get("inputs") or []:
        if not isinstance(i, dict) or set(i) - INPUT_KEYS:
            _bad(rid, f"bad input {i!r}")
        key, typ = i.get("key"), i.get("type")
        if not isinstance(key, str) or not KEY.match(key) or key in inputs:
            _bad(rid, f"input key {key!r} must be unique snake_case")
        if typ not in INPUT_TYPES:
            _bad(rid, f"input {key}: type must be one of {INPUT_TYPES}")
        if typ == "choice" and not (isinstance(i.get("options"), list) and i["options"] and all(isinstance(o, str) and o for o in i["options"])):
            _bad(rid, f"input {key}: choice needs a non-empty options list of strings")
        for n in ("max", "min"):
            if n in i and (isinstance(i[n], bool) or not isinstance(i[n], (int, float))):
                _bad(rid, f"input {key}: {n} must be a number")
        inputs[key] = i
    steps, ids = doc.get("steps"), {}
    if not isinstance(steps, list) or not steps:
        _bad(rid, "steps must be a non-empty list")
    for s in steps:
        if not isinstance(s, dict) or set(s) - STEP_KEYS:
            _bad(rid, f"bad step {s!r}")
        sid, task = s.get("id"), s.get("task")
        if not isinstance(sid, str) or not KEY.match(sid) or sid in ids or sid in inputs:
            _bad(rid, f"step id {sid!r} must be unique snake_case and not an input key")
        if not isinstance(task, str) or not task:
            _bad(rid, f"step {sid}: task is required")
        if s.get("when") is not None and s["when"] not in inputs:
            _bad(rid, f"step {sid}: when must name an input")
        for field in TEXT_FIELDS + ("direction",):       # prompts see text-like inputs only: never a file, never another step's output
            for text in _strings(s.get(field)):
                for ph in PLACEHOLDER.findall(text):
                    if ph not in inputs or inputs[ph]["type"] in ("image", "audio"):
                        _bad(rid, f"step {sid}: unknown placeholder {{{ph}}} in {field}")
                    if inputs[ph]["type"] == "text" and doc.get("consent", "none") == "required" and task in PAID and field != "text":
                        _bad(rid, f"step {sid}: free text may not steer image or video generation in a recipe that involves a real person")
                rest = PLACEHOLDER.sub("", text)
                if "{" in rest or "}" in rest:
                    _bad(rid, f"step {sid}: stray brace in {field}")
        for field in REF_FIELDS:
            for ref in ([s[field]] if isinstance(s.get(field), str) else s.get(field) or []):
                m = PLACEHOLDER.fullmatch(ref) if isinstance(ref, str) else None
                if not m:
                    _bad(rid, f"step {sid}: {field} must be whole {{placeholders}}")
                name = m.group(1)
                if not (name in ids or (name in inputs and inputs[name]["type"] in ("image", "audio"))):
                    _bad(rid, f"step {sid}: unknown or later placeholder {{{name}}} in {field}")
        if s.get("direction") is not None:
            d = s["direction"]
            if not (isinstance(d, dict) and set(d) == {"preset"} and isinstance(d["preset"], str)):
                _bad(rid, f"step {sid}: direction must be {{\"preset\": id}}")
            m = PLACEHOLDER.fullmatch(d["preset"])
            options = inputs[m.group(1)].get("options") if m and m.group(1) in inputs and inputs[m.group(1)]["type"] == "choice" else None
            if not all(o in presets() for o in ([d["preset"]] if not m else options or [None])):
                _bad(rid, f"step {sid}: direction preset must be a camera preset id, or a choice input whose options all are")
        for t in s.get("text") or []:
            if not (isinstance(t, dict) and set(t) <= {"text", "at", "for"} and isinstance(t.get("text"), str)
                    and all(isinstance(t.get(n, 0), (int, float)) and not isinstance(t.get(n, 0), bool) and 0 <= t.get(n, 0) <= 600 for n in ("at", "for"))):
                _bad(rid, f"step {sid}: each text overlay needs text and optional numbers at and for")
        if task == "reframe" and (s.get("aspect") not in tools_mod._ASPECTS or s.get("mode") not in ("crop", "pad", "blur-pad")):
            _bad(rid, f"step {sid}: reframe needs aspect {list(tools_mod._ASPECTS)} and mode crop, pad or blur-pad")
        if s.get("params") is not None:
            pr = s["params"]
            if not (isinstance(pr, dict) and set(pr) <= {"edit_mode", "mask_mode"} and pr.get("edit_mode", "bgswap") in EDIT_MODES
                    and re.fullmatch(r"MASK_MODE_[A-Z_]{1,24}", str(pr.get("mask_mode", "MASK_MODE_BACKGROUND")))):
                _bad(rid, f"step {sid}: params may only set edit_mode and mask_mode")
        if s.get("seconds") is not None and (isinstance(s["seconds"], bool) or not isinstance(s["seconds"], int) or not 1 <= s["seconds"] <= 30):
            _bad(rid, f"step {sid}: seconds must be a whole number from 1 to 30")
        if task in ("image_edit", "image_to_video", "video_extend", "reframe") and not s.get("source"):
            _bad(rid, f"step {sid}: {task} needs a source")
        ids[sid] = s
    return doc


def load_all(directory=DIR):
    out = {}
    for f in sorted(Path(directory).glob("*.json")):
        try:
            doc = validate(json.loads(f.read_text(encoding="utf-8")), f.stem)
        except ValueError as e:      # unreadable JSON is as fatal as a bad schema: a recipe is never half loaded
            raise RecipeError(f"recipe {f.stem}: {e}") from None
        if doc["id"] != f.stem:
            _bad(f.stem, "id must match the file name")
        out[doc["id"]] = doc
    return out


def get(recipe_id, directory=DIR):
    if not isinstance(recipe_id, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", recipe_id):
        raise RecipeError(f"unknown recipe {recipe_id!r}")
    try:
        return load_all(directory)[recipe_id]
    except KeyError:
        raise RecipeError(f"unknown recipe {recipe_id!r}") from None
