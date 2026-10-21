"""GenerationSpec: the ONE description of what a generation will be (model, seconds, frames, references, price).

Estimate, batch plan, proposal and execution all call resolve(), so they price and run the same thing.
The model is the shot's (or image's) own `model` when it names a usable provider's model, else the first model of the role chain whose
capability profile can serve the request. A feature the chosen model lacks is an error, never silently dropped.
"""
from dataclasses import dataclass, field

from aistudio import catalog as catalog_mod
from aistudio.domain.characters import pick_refs
from aistudio.domain.common import ServiceError

ROLE = {"image": "image", "image_edit": "image", "clip": "video", "clip_extend": "video"}
KIND = {"video": "video", "image": "image"}


def cfg_types():
    from aistudio.providers import config as cfg
    return cfg.PROVIDER_TYPES


def cfg_adapter(ptype):
    from aistudio.providers import config as cfg
    return cfg.adapter_class(ptype)


@dataclass
class GenerationSpec:
    kind: str
    target: str
    role: str
    entry: dict
    task: str
    profile: dict
    seconds: int = 0
    resolution: str = ""
    aspect_ratio: str = ""
    audio: bool = False
    start_frame: str = ""
    end_frame: str = ""
    keyframes: list = field(default_factory=list)
    refs: list = field(default_factory=list)       # [{"id", "path"}] paths relative to the project
    camera: dict = field(default_factory=dict)
    price: float = 0.0
    warnings: list = field(default_factory=list)
    explicit: bool = False      # the shot's / image's own model was used (not the chain's pick)

    @property
    def provider(self):
        return self.entry["provider"]["id"]

    @property
    def model(self):
        return self.entry["model"]

    def required_features(self):
        return {"task": self.task, "end_frame": bool(self.end_frame), "keyframes": len(self.keyframes), "refs": len(self.refs)}

    def to_dict(self):
        result = {"kind": self.kind, "target": self.target, "provider": self.provider, "model": self.model, "task": self.task, "profile": self.profile,
                  "seconds": self.seconds, "resolution": self.resolution, "aspect_ratio": self.aspect_ratio, "audio": self.audio,
                  "start_frame": self.start_frame, "end_frame": self.end_frame, "refs": self.refs, "camera": self.camera,
                  "price": self.price, "warnings": self.warnings}
        if self.keyframes:
            result["keyframes"] = self.keyframes
        return result


def _profile(ws, entry):
    return ws.catalog().profile(entry["provider"]["id"], entry["ptype"], entry["model"], entry["card"])


def _named(ws, p, role, ref):
    """The usable entry a model reference ('provider|model' or a bare model id) points to, else None."""
    runner = ws.runner()
    if not ref or runner._fake(role, p):
        return None
    pid, _, model = ref.rpartition("|") if "|" in ref else ("", "", ref)
    for e in runner.resolve(role, p):
        if e["problem"] is None and e["model"] == model and pid in ("", e["provider"]["id"]):
            return e
    for prov in runner.providers().values():
        if pid in ("", prov["id"]):
            e = runner.entry_for(role, prov["id"], model, p)
            if e and (e["card"] or {}).get("kind") == KIND[role]:      # a model is only picked up this way when its price is known
                return e
    return None


def select_entry(ws, p, role, model_ref=None, required=None, label="request"):
    """-> (entry, explicit). Raises ServiceError when no usable model has what the request needs."""
    runner, required = ws.runner(), required or {}
    chain = runner.resolve(role, p)
    if not chain:
        from aistudio.providers import config as pconf
        raise ServiceError(f"No {pconf.ROLE_INFO[role]['title'].lower()} model is set. Open Settings, add a provider and choose a model for '{role}'.")
    usable = [e for e in chain if e["problem"] is None]
    if not usable:
        raise ServiceError(f"The {role} models cannot be used: " + "; ".join(f"{e['model']} ({e['problem']})" for e in chain) + ". Open Settings to fix the provider.")
    cat = ws.catalog()
    named = _named(ws, p, role, model_ref)
    if named:
        why = catalog_mod.missing(_profile(ws, named), named["ptype"], required)
        if why:
            hint = ", ".join(catalog_mod.suggest(cat, required)[:4]) or "none known"
            raise ServiceError(f"{label} uses {named['model']}, which has {why}. Pick a model that can (built-in catalog: {hint}).")
        return named, True
    reasons = []
    for e in usable:
        why = catalog_mod.missing(_profile(ws, e), e["ptype"], required)
        if why is None:
            return e, False
        reasons.append(f"{e['model']}: {why}")
    hint = ", ".join(catalog_mod.suggest(cat, required)[:4]) or "none known"
    raise ServiceError(f"No {role} model can serve this {label} ({'; '.join(reasons)}). Add one that can (built-in catalog: {hint}).")


def _age(pricing, entry):
    """[warning] when the model's price card is undated or older than 30 days (shown to the approver; never blocks)."""
    w = pricing.age_warning(entry.get("card"))
    return [w] if w and entry.get("ptype") != "fake" and not pricing.is_free(entry.get("card")) else []


def _snap(profile, seconds, warnings):
    ds = profile["durations"]
    if not ds or seconds in ds:
        return seconds
    best = min(ds, key=lambda d: (abs(d - seconds), d))
    warnings.append(f"{seconds}s is not offered by this model; using {best}s (offered: {', '.join(map(str, ds))})")
    return best


def resolve(ws, p, kind, target, options=None, loose=False):
    """GenerationSpec for an image, image_edit, clip or clip_extend. loose=True lets a first frame that is not made yet pass (planning)."""
    options = options or {}
    role = ROLE.get(kind) or (_ for _ in ()).throw(ServiceError("kind must be image, clip, image_edit or clip_extend"))
    pricing, warnings = ws.pricing(), []
    if kind == "image":
        if loose:      # planning: referenced stills may not be made yet, so only count them
            spec = next((i for i in ws._read(p, "images.json", {"images": []})["images"] if i["id"] == target), None) or (_ for _ in ()).throw(ServiceError(f"unknown image id {target}"))
            refs = [p / r for r in spec.get("refs", [])]
        else:
            spec, refs, _prompt = ws._image_spec(p, target)
        req = {"task": "text_to_image", "refs": len(refs)}
        entry, explicit = select_entry(ws, p, role, spec.get("model"), req, f"image {target}")
        profile = _profile(ws, entry)
        price = pricing.image_price(entry["card"], len(refs))
        if price is None:
            raise ServiceError(f"No price set for {entry['model']}. Set it in Settings > Model Configuration before generating images.")
        warnings += _age(pricing, entry)
        return GenerationSpec(kind, target, role, entry, "text_to_image", profile, aspect_ratio=spec.get("aspect_ratio", "9:16"), explicit=explicit,
                              refs=[{"id": r.stem, "path": r.relative_to(p).as_posix()} for r in refs if r.is_relative_to(p)], price=price, warnings=warnings)
    if kind == "image_edit":
        entry, _ = select_entry(ws, p, role, None, {}, "image edit")
        price = pricing.image_price(entry["card"])
        if price is None:
            raise ServiceError(f"No price set for {entry['model']}. Set it in Settings > Model Configuration before editing stills.")
        return GenerationSpec(kind, target, role, entry, "image_edit", _profile(ws, entry), price=price, warnings=_age(pricing, entry))
    runner = ws.runner()
    if kind == "clip_extend":
        entry, _ = select_entry(ws, p, role, None, {}, "clip extension")
        profile = _profile(ws, entry)
        seconds = _snap(profile, int(options.get("seconds", 5)), warnings)
        price = runner.video_price(entry, {"seconds": seconds, "resolution": "720p", "audio": False})
        if price is None:
            raise ServiceError(f"No price for {entry['model']} at 720p ({seconds}s). Set it in Settings > Model Configuration.")
        return GenerationSpec(kind, target, role, entry, "video_extend", profile, seconds, "720p", "16:9", price=price, warnings=warnings + _age(pricing, entry))
    pipe = ws.pipeline_domain
    shot, doc, res, audio, ff = (pipe._clip_spec_loose if loose else pipe._clip_spec)(p, target)
    end = shot.get("end_frame") or ""
    keyframes = list(shot.get("keyframes") or [])
    image_doc = ws._read(p, "images.json", {"images": []})
    image_paths = {i.get("id"): i.get("out") for i in image_doc.get("images", []) if i.get("id") and i.get("out")}
    def frame_path(value):
        return image_paths.get(value, value)
    if end and not (p / frame_path(end)).is_file() and not loose:
        raise ServiceError(f"end frame missing: {end}")
    for frame in keyframes:
        image = frame.get("image") if isinstance(frame, dict) else None
        if image and not (p / frame_path(image)).is_file() and not loose:
            raise ServiceError(f"keyframe missing: {image}")
    req = {"task": "image_to_video" if ff else "text_to_video", "end_frame": bool(end), "keyframes": len(keyframes), "refs": 0}
    entry, explicit = select_entry(ws, p, role, shot.get("model"), req, f"shot {target}")
    profile = _profile(ws, entry)
    shot_refs, dropped = pick_refs(shot, profile, image_doc, root=p)
    if dropped:
        warnings.append("reference limit; dropped: " + ", ".join(r["id"] for r in dropped))
        req["refs"] = len(shot_refs)
    seconds = _snap(profile, int(shot["seconds"]), warnings)
    if profile["resolutions"] and res not in profile["resolutions"]:
        warnings.append(f"{res} is not in this model's known resolutions ({', '.join(profile['resolutions'])})")
    aspect = doc.get("aspect_ratio", "9:16")
    if profile["aspect_ratios"] and aspect not in profile["aspect_ratios"]:
        warnings.append(f"{aspect} is not in this model's known aspect ratios ({', '.join(profile['aspect_ratios'])})")
    if audio and profile["audio"] == "none":
        warnings.append("this model does not generate audio")
    why = shot_refs and catalog_mod.missing(profile, entry["ptype"], {"refs": len(shot_refs)})
    if why:
        warnings.append(f"reference images cannot be sent: {why}")
    from aistudio.storyboard.direction import split
    direction = shot.get("direction") or {}
    native, prompt_text = split(direction, profile) if direction and not shot.get("camera") else ({}, "")
    cam = {"prompt_text": shot.get("camera") or prompt_text, "native": native}
    if cam["prompt_text"] and profile["camera"]["mode"] == "none":
        warnings.append("this model has no camera control; the camera note stays in the prompt only")
    if not loose and entry.get("ptype") in cfg_types():      # a request the adapter will certainly refuse is never offered for approval
        try:
            adapter = cfg_adapter(entry["ptype"])
            sent = [r for r in shot_refs if (p / r["path"]).is_file()]
            objection = adapter.preflight(entry["model"], {"first_frame": ff or None, "last_frame": end or None, "refs": sent, "seconds": seconds,
                                                           "resolution": res, "camera_native": cam["native"]})
        except Exception:
            objection = None
        if objection:
            raise ServiceError(f"{entry['model']} cannot run this shot: {objection}")
    price = runner.video_price(entry, {"seconds": seconds, "resolution": res, "audio": audio}, len(shot_refs))      # reference charges are part of the quote
    if price is None:
        raise ServiceError(f"No price for {entry['model']} at {res} ({seconds}s). Set it in Settings > Model Configuration.")
    return GenerationSpec(kind, target, role, entry, req["task"], profile, seconds, res, aspect, audio, ff or "", end,
                          keyframes=keyframes, refs=shot_refs, camera=cam, price=price, warnings=warnings + _age(pricing, entry), explicit=explicit)
