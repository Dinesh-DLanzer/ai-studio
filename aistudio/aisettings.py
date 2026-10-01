"""AI model settings for the two text roles: CHAT (producer) and VERIFY (reviewer). Standard library only.

Free models are the default. A paid model is refused unless `allow_paid` is on; when on, every call is logged to the cost log and
refused once the per-project AI spend reaches `ai_cap_usd`.
"""
import json
import re
from pathlib import Path

from aistudio.chat import FREE_MODELS, is_free

ROLES = ("chat", "verify")
MODEL_RE = re.compile(r"^[A-Za-z0-9._~/:+-]{3,120}$")


def defaults():
    return {"chat": {"models": list(FREE_MODELS)}, "verify": {"models": list(FREE_MODELS[:3])},
            "allow_paid": False, "ai_cap_usd": 0.5, "auto_verify": True}


def validate(s):
    errs = []
    if not isinstance(s, dict):
        return ["settings must be an object"]
    for r in ROLES:
        ms = (s.get(r) or {}).get("models")
        if not isinstance(ms, list) or not 1 <= len(ms) <= 6 or not all(isinstance(m, str) and MODEL_RE.match(m) for m in ms):
            errs.append(f"{r}: give 1 to 6 model ids (for example nvidia/nemotron-3-ultra-550b-a55b:free)")
        elif len(set(ms)) != len(ms):
            errs.append(f"{r}: a model is listed twice")
        elif not s.get("allow_paid") and any(not is_free(m) for m in ms):
            errs.append(f"{r}: {[m for m in ms if not is_free(m)]} is not a free model; turn on 'Allow paid models' first")
    if not isinstance(s.get("allow_paid"), bool) or not isinstance(s.get("auto_verify"), bool):
        errs.append("allow_paid and auto_verify must be true or false")
    cap = s.get("ai_cap_usd")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not 0 <= cap <= 100:
        errs.append("ai_cap_usd must be a number from 0 to 100")
    return errs


def load(path):
    d = defaults()
    p = Path(path)
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            raw = {}
        for r in ROLES:
            if isinstance(raw.get(r), dict) and raw[r].get("models"):
                d[r] = {"models": raw[r]["models"]}
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            if k in raw:
                d[k] = raw[k]
    return d


def save(path, s):
    errs = validate(s)
    if errs:
        raise ValueError("; ".join(errs))
    clean = {r: {"models": list(s[r]["models"])} for r in ROLES}
    clean.update({"allow_paid": s["allow_paid"], "ai_cap_usd": float(s["ai_cap_usd"]), "auto_verify": s["auto_verify"]})
    Path(path).write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


def effective(s):
    """The saved settings (nothing is overridden from the environment any more).  Returns (settings, locked) with locked always empty."""
    return json.loads(json.dumps(s)), []


def parse_catalog(api_json):
    """OpenRouter /models -> [{id, name, free, prompt_per_m, completion_per_m, context}] for text-output models, free first then cheapest."""
    rows = []
    for m in (api_json or {}).get("data", []):
        mid = m.get("id", "")
        arch = m.get("architecture") or {}
        if "text" not in (arch.get("output_modalities") or ["text"]) or not MODEL_RE.match(mid) or mid.startswith("openrouter/auto") or mid.startswith("~"):
            continue
        try:
            pp, cp = float((m.get("pricing") or {}).get("prompt", 0) or 0) * 1e6, float((m.get("pricing") or {}).get("completion", 0) or 0) * 1e6
        except (TypeError, ValueError):
            continue
        if pp < 0 or cp < 0:
            continue
        rows.append({"id": mid, "name": m.get("name") or mid, "free": mid.endswith(":free") or (pp == 0 and cp == 0) or mid == "openrouter/free",
                     "prompt_per_m": round(pp, 4), "completion_per_m": round(cp, 4), "context": m.get("context_length")})
    rows.sort(key=lambda r: (not r["free"], r["prompt_per_m"] + r["completion_per_m"], r["id"]))
    return rows


def static_catalog():
    return [{"id": m, "name": m, "free": True, "prompt_per_m": 0.0, "completion_per_m": 0.0, "context": None} for m in FREE_MODELS]
