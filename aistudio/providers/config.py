"""Provider connections and role chains (settings v2).  Standard library only.

Files, inside <workspace>/settings/ (no secrets in them; secrets live in aistudio.secrets):
  providers.json  {"version":2,"providers":[{"id","type","label","base_url","enabled"}]}
  roles.json      {"version":2,"roles":{role:{"chain":[{"provider","model"}],"policy":{"retries","timeout"}}},
                   "allow_paid":bool,"ai_cap_usd":number,"auto_verify":bool}
A project may carry roles.override.json with the same "roles" shape (only the roles it overrides).
"""
import importlib
import json
import re
from pathlib import Path

ROLES = ("chat", "verify", "vision", "image", "video")
ROLE_CAPABILITY = {"chat": "chat", "verify": "chat", "vision": "vision", "image": "image", "video": "video"}
ROLE_INFO = {
    "chat": {"title": "Chat", "sub": "Text generation, planning, ideas"},
    "verify": {"title": "Verify", "sub": "Review the brief, story, assets and shots"},
    "vision": {"title": "Vision", "sub": "Analyze images and clip frames"},
    "image": {"title": "Image generation", "sub": "Generate images and scene frames"},
    "video": {"title": "Video generation", "sub": "Text to video, image to video"},
}
MAX_CHAIN = 8
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._~/:+@-]{1,120}$")

# type -> adapter location, UI metadata
PROVIDER_TYPES = {
    "openrouter": {"label": "OpenRouter", "sub": "Many models behind one key", "adapter": "openrouter.OpenRouterAdapter", "fields": ["api_key"], "base_url": False},
    "openai": {"label": "OpenAI", "sub": "GPT and image models", "adapter": "openai.OpenAIAdapter", "fields": ["api_key"], "base_url": False},
    "anthropic": {"label": "Anthropic", "sub": "Claude models for chat & vision", "adapter": "anthropic.AnthropicAdapter", "fields": ["api_key"], "base_url": False},
    "google": {"label": "Google Gemini", "sub": "Gemini chat, vision, image and Veo video", "adapter": "google.GoogleAdapter", "fields": ["api_key"], "base_url": False},
    "runway": {"label": "Runway", "sub": "Gen-3/Gen-4 video generation", "adapter": "runway.RunwayAdapter", "fields": ["api_key"], "base_url": False},
    "kling": {"label": "Kling", "sub": "Kling AI video generation", "adapter": "kling.KlingAdapter", "fields": ["access_key", "secret_key"], "base_url": False},
    "replicate": {"label": "Replicate", "sub": "Open source image and video models", "adapter": "replicate.ReplicateAdapter", "fields": ["api_key"], "base_url": False},
    "custom": {"label": "Custom (OpenAI-compatible)", "sub": "Any server with /chat/completions", "adapter": "openai.OpenAIAdapter", "fields": ["api_key"], "base_url": True},
    "fake": {"label": "Built-in test", "sub": "Free, offline, for trying things out", "adapter": "fake.FakeAdapter", "fields": [], "base_url": False},
}


def adapter_class(ptype):
    mod, cls = PROVIDER_TYPES[ptype]["adapter"].rsplit(".", 1)
    return getattr(importlib.import_module("aistudio.providers.adapters." + mod), cls)


def capabilities_of(ptype):
    return sorted(adapter_class(ptype).capabilities)


def provider_types():
    return [{"type": t, "label": m["label"], "sub": m["sub"], "fields": m["fields"], "base_url": m["base_url"], "capabilities": capabilities_of(t)}
            for t, m in PROVIDER_TYPES.items()]


def build_adapter(provider, secrets, transport=None):
    """provider = one entry of providers.json; secrets = a SecretStore. Returns a ready adapter."""
    conn = {"id": provider["id"], "type": provider["type"], "base_url": provider.get("base_url") or "",
            "secret": secrets.get(provider.get("secret_ref") or provider["id"]) if provider["type"] != "fake" else {}}
    return adapter_class(provider["type"])(conn, transport=transport) if transport else adapter_class(provider["type"])(conn)


# ---------------------------------------------------------------- providers
def validate_providers(providers):
    errs, seen = [], set()
    if not isinstance(providers, list):
        return ["providers must be a list"]
    for p in providers:
        pid = p.get("id", "") if isinstance(p, dict) else ""
        if not ID_RE.match(str(pid)):
            errs.append(f"invalid provider id {pid!r} (lowercase letters, digits, - and _)")
            continue
        if pid in seen:
            errs.append(f"duplicate provider id: {pid}")
        seen.add(pid)
        if p.get("type") not in PROVIDER_TYPES:
            errs.append(f"provider {pid}: unknown type {p.get('type')!r}")
            continue
        if not str(p.get("label") or "").strip():
            errs.append(f"provider {pid}: label is required")
        meta = PROVIDER_TYPES[p["type"]]
        bu = p.get("base_url") or ""
        if meta["base_url"] and not re.match(r"^https?://", bu):
            errs.append(f"provider {pid}: a base URL starting with http:// or https:// is required")
        if bu and not re.match(r"^https?://\S+$", bu):
            errs.append(f"provider {pid}: base URL must start with http:// or https://")
    return errs


def default_providers():
    return [{"id": "fake", "type": "fake", "label": "Built-in test", "base_url": "", "enabled": True}]


# ---------------------------------------------------------------- roles
def default_policy(role=None):
    return {"retries": 1, "timeout": 1500 if role == "video" else 120}


def default_roles():
    return {"version": 2, "roles": {r: {"chain": [], "policy": default_policy(r)} for r in ROLES},
            "allow_paid": False, "ai_cap_usd": 0.5, "auto_verify": True}


def validate_chain(role, chain, providers):
    errs = []
    by_id = {p["id"]: p for p in providers}
    if role not in ROLES:
        return [f"unknown role {role!r}"]
    if not isinstance(chain, list) or len(chain) > MAX_CHAIN:
        return [f"{role}: a chain has 0 to {MAX_CHAIN} models"]
    seen = set()
    cap = ROLE_CAPABILITY[role]
    for i, ref in enumerate(chain, 1):
        if not isinstance(ref, dict) or not MODEL_RE.match(str(ref.get("model") or "")):
            errs.append(f"{role} #{i}: invalid model id")
            continue
        prov = by_id.get(ref.get("provider"))
        if prov is None:
            errs.append(f"{role} #{i}: unknown provider {ref.get('provider')!r}")
            continue
        if cap not in capabilities_of(prov["type"]):
            errs.append(f"{role} #{i}: {PROVIDER_TYPES[prov['type']]['label']} cannot do {cap}")
        key = (ref["provider"], ref["model"])
        if key in seen:
            errs.append(f"{role} #{i}: {ref['model']} is listed twice")
        seen.add(key)
    return errs


def validate_roles(doc, providers):
    errs = []
    if not isinstance(doc, dict) or not isinstance(doc.get("roles"), dict):
        return ["roles must be an object"]
    for role, r in doc["roles"].items():
        errs += validate_chain(role, (r or {}).get("chain", []), providers)
        pol = (r or {}).get("policy") or {}
        if not isinstance(pol.get("retries", 1), int) or not 0 <= pol.get("retries", 1) <= 5:
            errs.append(f"{role}: retries must be 0 to 5")
        if not isinstance(pol.get("timeout", 120), (int, float)) or not 5 <= pol.get("timeout", 120) <= 1800:
            errs.append(f"{role}: timeout must be 5 to 1800 seconds")
    cap = doc.get("ai_cap_usd", 0.5)
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not 0 <= cap <= 100:
        errs.append("ai_cap_usd must be a number from 0 to 100")
    for k in ("allow_paid", "auto_verify"):
        if not isinstance(doc.get(k, False), bool):
            errs.append(f"{k} must be true or false")
    return errs


# ---------------------------------------------------------------- files
def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_providers(sdir):
    doc = _load(Path(sdir) / "providers.json", None)
    return doc["providers"] if isinstance(doc, dict) and isinstance(doc.get("providers"), list) else default_providers()


def save_providers(sdir, providers):
    errs = validate_providers(providers)
    if errs:
        raise ValueError("; ".join(errs))
    _save(Path(sdir) / "providers.json", {"version": 2, "providers": providers})


def load_roles(sdir):
    d = default_roles()
    raw = _load(Path(sdir) / "roles.json", {})
    for role, r in (raw.get("roles") or {}).items():
        if role in d["roles"] and isinstance(r, dict):
            d["roles"][role] = {"chain": list(r.get("chain") or []), "policy": {**default_policy(role), **(r.get("policy") or {})}}
    for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
        if k in raw:
            d[k] = raw[k]
    return d


def save_roles(sdir, doc, providers):
    errs = validate_roles(doc, providers)
    if errs:
        raise ValueError("; ".join(errs))
    _save(Path(sdir) / "roles.json", {**doc, "version": 2})


def effective_roles(sdir, project_dir=None):
    """Workspace roles with the project's roles.override.json applied on top (chains only)."""
    d = load_roles(sdir)
    if project_dir:
        ov = _load(Path(project_dir) / "roles.override.json", {})
        for role, r in (ov.get("roles") or {}).items():
            if role in d["roles"] and isinstance(r, dict) and r.get("chain"):
                d["roles"][role] = {"chain": r["chain"], "policy": {**d["roles"][role]["policy"], **(r.get("policy") or {})}}
    return d
