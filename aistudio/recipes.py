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
import subprocess
from pathlib import Path

from aistudio import consent as consent_mod, costlog, formats, project as project_mod, tools as tools_mod
from aistudio.domain import spec as spec_mod
from aistudio.domain.common import ServiceError, _sha

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
# tasks that put a real person's face, body or voice into new media: a recipe using one MUST declare consent "required" (a future data file cannot omit it)
CONSENT_TASKS = {"face_swap", "headshot", "outfit_swap", "lipsync", "character_swap", "motion_transfer", "voice_clone", "tts_clone"}
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
        if task in CONSENT_TASKS and doc.get("consent", "none") != "required":
            _bad(rid, f"step {sid}: task {task} involves a real person and needs consent: required")
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


# ---------------------------------------------------------------- availability
def task_available(ws, p, task):
    """(ok, why not). A paid task is available only when an enabled model of its role lists the task in its capability profile AND that model's
    adapter really implements the call. A task nobody implements yet is unavailable: never guessed."""
    if task == "assemble":
        return True, ""
    if task == "reframe":
        return ("reframe_local" in tools_mod.available(), "ffmpeg is not installed")
    if task not in PAID:
        return False, f"the '{task}' task does not exist in this version"
    from aistudio.providers import base as pbase, config as cfg
    role, method, _ = PAID[task]
    for e in ws.runner().resolve(role, p):
        if e["problem"]:
            continue
        if task not in ws.catalog().profile(e["provider"]["id"], e["ptype"], e["model"], e["card"])["tasks"]:
            continue
        if e["ptype"] in cfg.PROVIDER_TYPES and getattr(cfg.adapter_class(e["ptype"]), method) is getattr(pbase.Adapter, method):
            continue
        return True, ""
    return False, f"no enabled {role} model lists {task.replace('_', ' ')} and implements it"


def availability(ws, recipe, p=None):
    """{"available", "reasons", "skipped"}: reasons block the recipe; skipped lists optional steps that will be left out (with the reason)."""
    reasons, skipped = [], []
    for task in recipe.get("requires", []):
        ok, why = task_available(ws, p, task)
        if not ok:
            reasons.append(f"needs {task}: {why}")
    for s in recipe["steps"]:
        ok, why = task_available(ws, p, s["task"])
        if not ok:
            (skipped if s.get("optional") else reasons).append({"step": s["id"], "reason": why} if s.get("optional") else f"step {s['id']} needs {s['task']}: {why}")
    return {"available": not reasons, "reasons": reasons, "skipped": skipped}


def list_recipes(ws, project=None, only_available=False):
    """Every recipe with whether it can run now. Free; nothing is priced or created."""
    p = ws.pdir(project) if project else None
    out = []
    for r in load_all().values():
        a = availability(ws, r, p)
        if a["available"] or not only_available:
            out.append({"id": r["id"], "label": r["label"], "category": r["category"], "description": r.get("description", ""), "consent": r.get("consent", "none"),
                        "format": r.get("format"), "inputs": r.get("inputs", []), **a})
    return out


def is_number_input(recipe_id, key):
    """CLI helper: --input values arrive as strings; number inputs must be passed as numbers."""
    return any(i["key"] == key and i["type"] == "number" for i in get(recipe_id).get("inputs", []))


# ---------------------------------------------------------------- inputs (validated, then only ever substituted as text)
def _file_input(p, key, value, suffixes):
    rel = value
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        raise RecipeError(f"input {key}: give the file as a path inside the project")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts or "_discarded" in path.parts or path.suffix.lower() not in suffixes:
        raise RecipeError(f"input {key}: must be a project file ({'/'.join(suffixes)}), not an absolute path, '..' or a discarded file")
    root = Path(p).resolve()
    try:
        full = (root / path).resolve()
        full.relative_to(root)
    except (OSError, ValueError):
        raise RecipeError(f"input {key}: must stay inside the project") from None
    if not full.is_file():
        raise RecipeError(f"input {key}: file not found: {rel}")
    return {"path": full.relative_to(root).as_posix(), "sha": _sha(full)}


def validate_inputs(recipe, p, raw):
    """-> {"text": {key: str}, "files": {key: {"path", "sha"}}}. Anything unknown, too long or outside the project is an error."""
    raw = raw if isinstance(raw, dict) else {}
    defs = {i["key"]: i for i in recipe.get("inputs", [])}
    if set(raw) - set(defs):
        raise RecipeError(f"unknown input(s): {', '.join(sorted(set(raw) - set(defs)))}")
    text, files = {}, {}
    for key, d in defs.items():
        v, typ = raw.get(key), d["type"]
        if v in (None, ""):
            if d.get("required"):
                raise RecipeError(f"input {key} is required")
            if typ in ("text", "choice", "number"):
                text[key] = ""
            continue
        if typ == "text":
            cap = min(int(d.get("max", 200)), TEXT_CAP)
            if not isinstance(v, str) or len(v) > cap or any(ord(c) < 32 and c not in "\n\t" for c in v):
                raise RecipeError(f"input {key}: text up to {cap} characters, no control characters")
            text[key] = v.strip()
        elif typ == "choice":
            if v not in d["options"]:
                raise RecipeError(f"input {key}: choose one of {', '.join(d['options'])}")
            text[key] = v
        elif typ == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not d.get("min", float("-inf")) <= v <= d.get("max", float("inf")):
                raise RecipeError(f"input {key}: a number between {d.get('min', '-inf')} and {d.get('max', 'inf')}")
            text[key] = f"{v:g}"
        else:
            files[key] = _file_input(p, key, v, IMAGE_SUFFIX if typ == "image" else AUDIO_SUFFIX)
    return {"text": text, "files": files}


def _fill(template, values):
    """Single-pass substitution: a value is never scanned for placeholders again. Whitespace is tidied."""
    return " ".join(PLACEHOLDER.sub(lambda m: values[m.group(1)], template).split())


# ---------------------------------------------------------------- consent
def _consent(ws, p, policy, rels):
    """Same rule as pipeline._require_consent: an asset flagged real_person needs a human-recorded consent. A 'required' recipe also needs
    at least one image that a human flagged as a real person (a typed name is never a face target)."""
    p = Path(p)
    doc = ws._read(p, "images.json", {"images": []})
    by_out = {i.get("out"): i for i in doc.get("images", []) if isinstance(i, dict)}
    by_id = {i.get("id"): i for i in doc.get("images", []) if isinstance(i, dict)}
    ids, flagged = [], False
    shas = []
    for rel in rels:
        asset = by_out.get(rel) or by_id.get(Path(rel).stem)
        ids += [Path(rel).stem] + ([asset["id"]] if asset else [])
        flagged = flagged or bool(asset and asset.get("real_person"))
        f = p / rel
        if f.is_file():
            shas.append(_sha(f))
    marked = consent_mod.real_person_shas(p)
    if any(s in marked for s in shas):
        flagged = True
    consent_mod.require_assets(p, doc, ids)
    if shas:
        consent_mod.require_shas(p, shas)
    if policy == "required" and not flagged:
        raise RecipeError("this recipe involves a real person: add the photo as an asset marked real_person with the subject's name, and have a human "
                          "record their consent first. Nothing was planned.")


# ---------------------------------------------------------------- planning
def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _live(ws, p, item):
    """What the item's request looks like in the project right now (spec entries and input bytes), bound into its request hash."""
    rd, live = item["recipe"], {}
    if "input" in (rd.get("source") or {}):
        live["input_sha"] = _sha(Path(p) / rd["source"]["path"])
    if item["kind"] == "clip":
        shot = next((s for s in ws._read(p, "shots.json", {"shots": []})["shots"] if s["id"] == item["target"]), None)
        live["shot"] = shot and {k: shot.get(k) for k in ("prompt", "seconds", "direction", "audio", "resolution", "model")}
        live["aspect_ratio"] = ws._read(p, "shots.json", {}).get("aspect_ratio")
    if item["kind"] == "image":
        img = next((i for i in ws._read(p, "images.json", {"images": []})["images"] if i["id"] == item["target"]), None)
        live["image"] = img and {k: img.get(k) for k in ("prompt", "aspect_ratio", "refs", "out", "model")}
        live["style"] = ws._read(p, "images.json", {}).get("style", "")
    return live


def digest(ws, p, item, model=None, price=None):
    return hashlib.sha256(_canon({"kind": item["kind"], "target": item["target"], "model": model or item["model"], "price": round(float(item["price"] if price is None else price), 6),
                                  "recipe": item["recipe"], "live": _live(ws, p, item)}).encode()).hexdigest()


def _price(ws, p, item):
    """(model, price) exactly as the pipeline would charge it now. Free local steps cost nothing."""
    rd, kind, target = item["recipe"], item["kind"], item["target"]
    if kind in ("assemble", "reframe"):
        return item["model"], 0.0
    if kind in ("image", "clip"):
        price, model = ws.pipeline_domain._item_price(p, kind, target)
        return model, round(float(price), 6)
    sp = spec_mod.resolve(ws, p, kind, target, {"seconds": rd.get("seconds") or 5})
    return sp.model, round(float(sp.price), 6)


def _aspect(recipe, shots_doc):
    fmt = formats.get_format(recipe["format"])["aspect_ratio"] if recipe.get("format") else None
    have = shots_doc.get("aspect_ratio") if shots_doc.get("shots") else None
    if fmt and have and have != fmt:
        raise RecipeError(f"{recipe['id']} makes {fmt} video but this project's shots are {have}; use a new project")
    return fmt or have or "9:16"


def plan(ws, name, recipe_id, inputs, actor="local"):
    """Free. Validate the inputs, resolve the steps in order, price every paid step through the same resolver the pipeline uses and freeze ONE
    awaiting-approval batch (total == sum of item prices). Nothing is approved, run or spent; a human approves the batch (batches.approve).
    Steps that use an earlier step's output are priced from their specification and re-checked when they run."""
    recipe, p = get(recipe_id), ws.pdir(name)
    avail = availability(ws, recipe, p)
    if not avail["available"]:
        raise RecipeError(f"{recipe['label']} cannot run here: " + "; ".join(avail["reasons"]))
    vals = validate_inputs(recipe, p, inputs)
    rels = [f["path"] for k, f in vals["files"].items() if next(i for i in recipe["inputs"] if i["key"] == k)["type"] == "image"]
    _consent(ws, p, recipe.get("consent", "none"), rels)
    run = secrets.token_hex(4)
    shots_doc = ws._read(p, "shots.json", {"aspect_ratio": "9:16", "final_resolution": "720p", "shots": []})
    images_doc = ws._read(p, "images.json", {"style": "", "images": []})
    # Clean up previous unexecuted/abandoned rcp* steps from shots.json and images.json
    active_runs = set()
    bdir = p / "batches"
    if bdir.is_dir():
        for bf in bdir.glob("*.json"):
            try:
                bdata = json.loads(bf.read_text(encoding="utf-8"))
                if bdata.get("status") in ("approved", "running", "completed"):
                    if bdata.get("extra", {}).get("recipe", {}).get("run"):
                        active_runs.add(bdata["extra"]["recipe"]["run"])
                    for it in bdata.get("items", []):
                        if isinstance(it.get("recipe"), dict) and "run" in it["recipe"]:
                            active_runs.add(it["recipe"]["run"])
            except Exception:
                pass
    shots_doc["shots"] = [s for s in shots_doc.get("shots", []) if not (str(s.get("id", "")).startswith("rcp") and s.get("recipe") not in active_runs and not s.get("final_clip"))]
    images_doc["images"] = [i for i in images_doc.get("images", []) if not (str(i.get("id", "")).startswith("rcp") and i.get("recipe") not in active_runs and not (p / str(i.get("out", ""))).is_file())]
    old = (json.loads(json.dumps(shots_doc)), json.loads(json.dumps(images_doc)))
    aspect = _aspect(recipe, shots_doc)
    shots_doc["aspect_ratio"] = aspect
    skipped = {s["step"]: s["reason"] for s in avail["skipped"]}
    items, notes, outputs = [], [], {}
    for s in recipe["steps"]:
        sid, task = s["id"], s["task"]
        src = None
        if s.get("source"):
            ref = PLACEHOLDER.fullmatch(s["source"]).group(1)
            src = {"input": ref, **vals["files"][ref]} if ref in vals["files"] else {"step": ref}
        if s.get("when") and not vals["text"].get(s["when"]):
            skipped[sid] = "not used"
        elif sid not in skipped and src and "step" in src and src["step"] in skipped:
            if not (s.get("optional") or s.get("when")):
                raise RecipeError(f"step {sid} needs {src['step']}, which was skipped")
            skipped[sid] = f"depends on skipped step {src['step']}"
        if sid in skipped:
            notes.append({"step": sid, "skipped": skipped[sid]})
            continue
        target = f"rcp{run}_{sid}"
        rd = {"recipe": recipe["id"], "run": run, "step": sid, "task": task, "consent": recipe.get("consent", "none"), "inputs": rels}
        if src:
            rd["source"] = src
        if "prompt" in s:
            rd["prompt"] = _fill(s["prompt"], vals["text"])[:PROMPT_CAP]
        if s.get("seconds"):
            rd["seconds"] = s["seconds"]
        if s.get("direction"):
            rd["direction"] = {"preset": _fill(s["direction"]["preset"], vals["text"])}
            if rd["direction"]["preset"] not in presets():
                raise RecipeError(f"step {sid}: unknown camera preset {rd['direction']['preset']!r}")
        if task in ("image_edit",):
            rd.update(edit_mode=(s.get("params") or {}).get("edit_mode", "bgswap"), mask_mode=(s.get("params") or {}).get("mask_mode", "MASK_MODE_BACKGROUND"))
        if task == "assemble":
            rd["clips"] = [PLACEHOLDER.fullmatch(c).group(1) for c in s.get("clips", []) if PLACEHOLDER.fullmatch(c).group(1) not in skipped]
            rd["audio"] = [a for a in (PLACEHOLDER.fullmatch(c).group(1) for c in s.get("audio", [])) if a not in skipped]
            rd["audio"] = [{"input": a, **vals["files"][a]} if a in vals["files"] else {"step": a} for a in rd["audio"]]
            rd["text"] = [{"text": t, "at": o.get("at", 0), "for": o.get("for", 3)} for o in s.get("text", []) if (t := _fill(o["text"], vals["text"]))]
            rd["aspect"] = aspect
            if not rd["clips"]:
                raise RecipeError("nothing to assemble: no clip step ran")
        if task == "reframe":
            rd.update(aspect=s["aspect"], mode=s["mode"])
        kind = "assemble" if task == "assemble" else "reframe" if task == "reframe" else PAID[task][2]
        items.append({"kind": kind, "target": target, "label": f"{recipe['label']}: {sid}", "model": "local" if kind in ("assemble", "reframe") else "", "price": 0.0, "recipe": rd})
        outputs[sid] = target
    try:
        _materialize(ws, name, p, items, shots_doc, images_doc, aspect)
        for it in items:
            it["model"], it["price"] = _price(ws, p, it)
            it["request_hash"] = digest(ws, p, it)
    except BaseException:       # leave the project's documents exactly as they were
        project_mod.save_json(p, "shots.json", old[0])
        project_mod.save_json(p, "images.json", old[1])
        raise
    b = ws._read(p, "budget.json", {})
    total = round(sum(i["price"] for i in items), 6)
    budget = {"estimate": b.get("estimate"), "stop_loss": b.get("stop_loss"), "spent": round(costlog.spent(p), 6)}
    ready = bool(b.get("approved")) and not ws._costs.stale_budget(p, b)
    extra = {"recipe": {"id": recipe["id"], "label": recipe["label"], "run": run, "skipped": notes, "total": total, "budget_ready": ready,
                        "note": "" if ready else "The project budget must be (re)estimated and approved by a human before this batch can run: the recipe added its steps to the storyboard."}}
    return ws.batches.create(name, actor=actor, plan={"items": items, "total": total, "budget": budget, "extra": extra})


def _materialize(ws, name, p, items, shots_doc, images_doc, aspect):
    """Image and clip steps live in images.json / shots.json (like an identity sheet): the pipeline prices, hashes and gates them as usual."""
    for it in items:
        rd, target = it["recipe"], it["target"]
        if it["kind"] == "image":
            images_doc["images"].append({"id": target, "kind": "other", "out": f"stills/{target}.png", "refs": [], "aspect_ratio": aspect, "prompt": rd["prompt"], "recipe": rd["run"]})
        elif it["kind"] == "clip":
            src = rd["source"]
            first = src["path"] if "input" in src else f"stills/rcp{rd['run']}_{src['step']}.png"      # replaced by the real file when the step runs
            shot = {"id": target, "prompt": rd["prompt"], "seconds": rd.get("seconds", 4), "model": "", "first_frame": first, "recipe": rd["run"]}
            if rd.get("direction"):
                shot["direction"] = rd["direction"]
            shots_doc["shots"].append(shot)
    if any(i["kind"] == "image" for i in items):
        ws.put_images(name, images_doc)
    if any(i["kind"] == "clip" for i in items):
        ws.put_shots(name, shots_doc)


# ---------------------------------------------------------------- running (called by BatchDomain.run for items that carry a recipe)
def _source_file(ws, name, p, rd, batch):
    src = rd["source"]
    if "input" in src:
        return src["path"]
    done = next((i for i in batch["items"] if i["recipe"]["step"] == src["step"] and i["status"] == "done" and i.get("file")), None)
    if not done:
        raise RecipeError(f"step {src['step']} produced no file to use")
    return _contained(p, done["file"])


def _contained(p, rel):
    """A path read from batch json is data: it must be project-relative, stay inside the project and be a media file."""
    root = Path(p).resolve()
    f = (root / str(rel)).resolve()
    if Path(str(rel)).is_absolute() or not f.is_relative_to(root) or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".wav", ".mp3", ".m4a"):
        raise RecipeError(f"refusing step output path {rel!r}: it must be a media file inside the project")
    return str(rel)


def _step_file(batch, step):
    done = next((i for i in batch["items"] if i["recipe"]["step"] == step and i["status"] == "done" and i.get("file")), None)
    return done and done["file"]


def run_item(ws, name, p, item, batch):
    """Run ONE recipe item the way BatchDomain runs a normal one: re-check consent, model, price and request, then propose, pre-approve (the human
    approved the batch at exactly this price) and execute through the normal pipeline so every gate, grant and cost-log row still applies.
    Returns None on success or the batch status to stop with."""
    rd = item["recipe"]
    try:
        _consent(ws, p, rd["consent"], rd["inputs"])
        model, price = _price(ws, p, item)
        changes = []
        if model != item["model"]:
            changes.append(f"model {item['model']} -> {model}")
        if price != item["price"]:
            changes.append(f"price ${item['price']:.3f} -> ${price:.3f}")
        if digest(ws, p, item, model, price) != item["request_hash"]:
            changes.append("request changed")
    except ServiceError as error:
        item.update(status="error", error=str(error))
        return "error"
    if changes:
        item.update(status="needs_reapproval", changes=changes)
        return "needs_reapproval"
    try:
        if item["kind"] == "assemble":
            item.update(status="done", file=_assemble(ws, name, p, item, batch), cost=0)
            return None
        if item["kind"] == "reframe":
            src = _source_file(ws, name, p, rd, batch)
            out = tools_mod.run_local("reframe_local", src, f"stills/{item['target']}.png", {"aspect": rd["aspect"], "mode": rd["mode"]}, p)
            item.update(status="done", file=Path(out).resolve().relative_to(Path(p).resolve()).as_posix(), cost=0)
            return None
        options = None
        if item["kind"] in ("image_edit", "clip_extend"):
            options = {"source": _source_file(ws, name, p, rd, batch), "prompt": rd.get("prompt", "")}
            options.update({"edit_mode": rd["edit_mode"], "mask_mode": rd["mask_mode"]} if item["kind"] == "image_edit" else {"seconds": rd.get("seconds", 5)})
        elif item["kind"] == "clip":
            doc = ws._read(p, "shots.json")
            next(s for s in doc["shots"] if s["id"] == item["target"])["first_frame"] = _source_file(ws, name, p, rd, batch)
            project_mod.save_json(p, "shots.json", doc)
        prop = ws.propose(name, item["kind"], item["target"], options=options)
        if prop["model"] != item["model"] or prop["price"] != item["price"]:
            ws.reject(name, prop["id"])
            item.update(status="needs_reapproval", changes=["model or price changed while starting"])
            return "needs_reapproval"
        ws.approve_human(name, prop["id"])      # authorised by the human's approval of this batch, at exactly this price
        res = ws.execute(name, prop["id"]) or {}
    except (ServiceError, StopIteration, ValueError, OSError, subprocess.SubprocessError) as error:
        item.update(status="error", error=str(error) or "step failed")
        return "error"
    if res.get("error") or res.get("pending") or not res.get("file"):
        item.update(status="error", error=str(res.get("error") or "the provider has not finished; sync the job, then plan again"), proposal=prop["id"])
        return "error"
    item.update(status="done", proposal=prop["id"], cost=res.get("cost"), file=res["file"])
    return None


def _assemble(ws, name, p, item, batch):
    """Free: write edit.json (schema-validated, with history) from the clips and sounds the earlier steps made. Never exports unless asked."""
    from aistudio import editor
    rd = item["recipe"]
    video, t = [], 0.0
    for n, step in enumerate(rd["clips"], 1):
        rel = _step_file(batch, step)
        if not rel:
            raise RecipeError(f"step {step} produced no clip")
        rel = _contained(p, rel)
        info = editor.probe(Path(p) / rel)
        secs = float((info or {}).get("duration") or next((i["recipe"].get("seconds") for i in batch["items"] if i["recipe"]["step"] == step), None) or 4)
        video.append({"id": f"c{n}", "src": rel, "in": 0, "out": round(max(secs, 0.3), 2), "volume": 1, "transition": {"type": "cut", "dur": 0.5}})
        t += video[-1]["out"]
    audio = []
    for n, a in enumerate(rd["audio"], 1):
        rel = a["path"] if "input" in a else _step_file(batch, a["step"])
        rel = _contained(p, rel) if rel else rel
        if rel:
            audio.append({"id": f"a{n}", "src": rel, "in": 0, "out": round(t, 2), "start": 0, "volume": 0.6})
    text = []
    for n, o in enumerate(rd["text"], 1):
        start = min(float(o["at"]), max(t - 0.2, 0))
        text.append({"id": f"t{n}", "text": o["text"], "start": start, "end": round(min(start + float(o["for"]), t), 2)})
    ws.edit_put(name, {"version": 1, "aspect": rd["aspect"], "fps": 24, "tracks": {"video": video, "text": text, "audio": audio, "elements": []}})
    if rd.get("export"):
        ws.edit_export(name)
    return "edit.json"
