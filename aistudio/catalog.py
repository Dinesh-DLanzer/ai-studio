"""Model capability profiles (plan 13).  Lookup order, first layer wins per field:
user override (settings/models.json "capabilities") > comfy workflow manifest > provider metadata cache (settings/catalog_cache.json) > built-in catalog/models.json > conservative default.
Each layer is merged over the next, so a partial profile (for example only the fields a provider API reported) is enough.
"""
from copy import deepcopy
import fnmatch
import json
from pathlib import Path

from aistudio.pricing import key
from aistudio.providers import config as cfg
from aistudio.schemas.catalog import validate_profile

AI_TOOL_TASKS = ("upscale", "reframe", "video_to_video", "motion_transfer")      # paid clip tools (plan 17)
AUDIO_TASKS = ("tts", "music", "sfx", "lipsync", "transcribe")
BUILTIN = Path(__file__).resolve().parent.parent / "catalog" / "models.json"


def _merge(base, over):
    out = deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else deepcopy(v)
    return out


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def default_profile(ptype, card=None):
    """What a model nobody described can safely do: camera through the prompt, a start frame, no end frame.
    Empty durations/aspect_ratios mean "not constrained" (today's behaviour)."""
    caps = cfg.capabilities_of(ptype) if ptype in cfg.PROVIDER_TYPES else []
    kind = (card or {}).get("kind")
    video = kind == "video" or (kind is None and "video" in caps)
    image = kind == "image" or (kind is None and not video and "image" in caps)
    return {"tasks": ["text_to_video", "image_to_video"] if video else ["text_to_image"] if image else [],
            "durations": [], "resolutions": list(card["per_second"]) if kind == "video" else [], "aspect_ratios": [],
            "audio": "optional" if video else "none", "frames": {"start": True, "end": False, "keyframes": 0},
            "references": {"max": 1 if video else 14 if image else 0, "roles": []},
            "camera": {"mode": "prompt", "native": [], "param": None}, "seed": False, "negative_prompt": False, "tools": "json",
            "source": "default", "verified_at": None, "provider_type": ptype}


class Catalog:
    def __init__(self, settings_dir, pricing=None, builtin=BUILTIN):
        self.dir, self.pricing = Path(settings_dir), pricing
        self.entries = _read(builtin, {}).get("entries", [])

    def comfy_manifest(self, workflow_id):
        """Load the capability profile from a ComfyUI workflow manifest.
        Returns the profile dict with source='comfy_manifest' or None if not found/invalid.
        """
        from aistudio.comfy_workflows import get_workflow
        try:
            m = get_workflow(self.dir, workflow_id)
            profile = {**m["profile"], "source": "comfy_manifest"}
            # Derive tasks from the manifest's task field if not explicitly in profile
            if "tasks" not in profile:
                task = m["task"]
                if task == "image":
                    profile["tasks"] = ["text_to_image"]
                elif task in ("text_to_video", "image_to_video", "video"):
                    profile["tasks"] = ["text_to_video", "image_to_video"]
                elif task == "text_to_image":
                    profile["tasks"] = ["text_to_image"]
                else:
                    profile["tasks"] = [task]
            return profile
        except ServiceError:
            return None
        except ValueError:
            return None

    def builtin(self, ptype, model):
        for e in self.entries:
            if e["provider_type"] == ptype and fnmatch.fnmatchcase(model, e["pattern"]):
                return {**e["profile"], "source": "builtin", "verified_at": e.get("verified_at"), "note": e.get("note")}
        return None

    def cached(self, provider_id, model):
        return _read(self.dir / "catalog_cache.json", {}).get(key(provider_id, model))

    def override(self, provider_id, model):
        return (_read(self.dir / "models.json", {}).get("capabilities") or {}).get(key(provider_id, model))

    def profile(self, provider_id, ptype, model, card=None):
        if card is None and self.pricing:
            card = self.pricing.card(provider_id, ptype, model)
        out = default_profile(ptype, card)
        user = self.override(provider_id, model)
        # Check if this is a ComfyUI workflow model (wf:<id>)
        comfy_layer = None
        if model.startswith("wf:"):
            wf_id = model[3:]
            comfy_layer = self.comfy_manifest(wf_id)
        for layer in (comfy_layer, self.builtin(ptype, model), self.cached(provider_id, model), user and {**user, "source": "user"}):
            if layer:
                out = _merge(out, layer)
        out["provider_type"] = ptype
        return out

    def store(self, provider_id, model, partial):
        """Cache what a provider API reported (source provider_api)."""
        cache = _read(self.dir / "catalog_cache.json", {})
        cache[key(provider_id, model)] = {**partial, "source": "provider_api"}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "catalog_cache.json").write_text(json.dumps(cache, indent=1), encoding="utf-8")

    def refresh(self, provider_id, adapter, model):
        """Ask the adapter to describe the model; cache and return the partial profile (None when it cannot)."""
        partial = adapter.describe_model(model)
        if partial and not validate_profile(_merge(default_profile(adapter.type), partial)):
            self.store(provider_id, model, partial)
            return partial
        return None


def missing(profile, ptype, req):
    """Why a model cannot serve a request, or None. req = {"task", "end_frame": bool, "refs": int}."""
    ptype = ptype or (profile or {}).get("provider_type") or (profile or {}).get("ptype") or ""
    task = req.get("task")
    if task in AI_TOOL_TASKS + AUDIO_TASKS:      # fail closed: profile and adapter must both declare support
        if task not in profile["tasks"]:
            return f"no {task.replace('_', ' ')} support"
        if not ptype or ptype not in cfg.PROVIDER_TYPES or task not in cfg.adapter_class(ptype).task_methods:
            return f"its adapter cannot run {task.replace('_', ' ')} yet"
    if task and profile["tasks"] and task not in profile["tasks"]:
        return f"no {task.replace('_', ' ')} support"
    if req.get("end_frame"):
        if not profile["frames"]["end"]:
            return "no end-frame support"
        if not ptype or ptype not in cfg.PROVIDER_TYPES or "end_frame" not in cfg.adapter_class(ptype).request_features:
            return "its adapter cannot send an end frame yet"
    if req.get("keyframes"):
        if profile["frames"].get("keyframes", 0) < req["keyframes"]:
            return f"accepts {profile['frames'].get('keyframes', 0)} keyframe(s), {req['keyframes']} given"
        if not ptype or ptype not in cfg.PROVIDER_TYPES or "keyframes" not in cfg.adapter_class(ptype).request_features:
            return "its adapter cannot send keyframes yet"
    if req.get("refs", 0) > profile["references"]["max"]:
        return f"accepts at most {profile['references']['max']} reference image(s), {req['refs']} given"
    if req.get("refs") and str(task).endswith("_video") and (not ptype or ptype not in cfg.PROVIDER_TYPES or "refs" not in cfg.adapter_class(ptype).request_features):
        return "its adapter cannot send reference images yet"
    return None


def suggest(catalog, req):
    """Built-in models that have what the request needs (named in error messages)."""
    return [f"{e['provider_type']}:{e['pattern']}" for e in catalog.entries
            if e["provider_type"] != "fake" and missing(_merge(default_profile(e["provider_type"]), e["profile"]), e["provider_type"], req) is None]
