"""One-time migration from the OpenRouter-only setup (v1) to provider connections and role chains (v2).  Standard library only.

Reads (never modifies or deletes): <root>/providers.json (v1 mode + provider defaults), <root>/ai_settings.json (chat/verify model lists,
allow_paid, ai_cap_usd, auto_verify).  Keys are never read from the environment: add them in Settings.
Writes: <root>/settings/providers.json and <root>/settings/roles.json  (only when roles.json does not exist yet; running again is a no-op).
"""
from pathlib import Path

from aistudio import aisettings
from aistudio.providers import config as cfg, registry


def plan(root, force_openrouter=False):
    """What migration would write: (providers, roles_doc, report)."""
    root = Path(root)
    try:
        legacy = registry.load_config(root / "providers.json")
    except (ValueError, OSError):
        legacy = registry.default_config()
    ai = aisettings.load(root / "ai_settings.json")
    legacy_files = (root / "providers.json").exists() or (root / "ai_settings.json").exists()
    use_or = legacy_files or force_openrouter
    providers = cfg.default_providers()
    roles = cfg.default_roles()
    notes = []
    if use_or:
        providers.insert(0, {"id": "openrouter", "type": "openrouter", "label": "OpenRouter", "base_url": "", "enabled": True})
        notes.append("OpenRouter provider created (add its key in Settings)")
        for role in ("chat", "verify"):
            roles["roles"][role]["chain"] = [{"provider": "openrouter", "model": m} for m in ai[role]["models"]]
        by_name = {p["name"]: p for p in legacy.get("providers", [])}
        for role in ("vision", "image", "video"):
            p = by_name.get((legacy.get("defaults") or {}).get(role, ""))
            if p and not p["name"].startswith("fake-"):
                roles["roles"][role]["chain"] = [{"provider": "openrouter", "model": p["model"]}]
        for k in ("allow_paid", "ai_cap_usd", "auto_verify"):
            roles[k] = ai[k]
    else:
        notes.append("no legacy settings found: starting with the built-in test provider only")
    return providers, roles, {"openrouter": use_or, "notes": notes}


def migrate(root, force_openrouter=False, dry_run=False):
    root = Path(root)
    sdir = root / "settings"
    if (sdir / "roles.json").exists() and (sdir / "providers.json").exists():
        return {"migrated": False, "notes": ["already on v2"]}
    providers, roles, report = plan(root, force_openrouter)
    if not dry_run:
        cfg.save_providers(sdir, providers)
        cfg.save_roles(sdir, roles, providers)
    return {"migrated": not dry_run, **report, "providers": [p["id"] for p in providers]}
