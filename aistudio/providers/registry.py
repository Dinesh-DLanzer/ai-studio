"""E7: provider configuration (providers.json). Standard library only.

Contract (tests in tests/test_registry.py):
  default_config() -> dict
     {"mode": "fake",
      "providers": [ {"name":"fake-llm","kind":"llm","model":"fake/llm"}, {"name":"fake-image","kind":"image","model":"fake/image"},
                     {"name":"fake-video","kind":"video","model":"fake/video"}, {"name":"fake-vision","kind":"vision","model":"fake/vision"},
                     {"name":"openrouter-image","kind":"image","model":"qwen/qwen-image-3"},
                     {"name":"openrouter-video","kind":"video","model":"google/veo-3.1-lite"},
                     {"name":"openrouter-vision","kind":"vision","model":"google/gemini-2.5-flash-lite"} ],
      "defaults": {"llm":"fake-llm","image":"openrouter-image","video":"openrouter-video","vision":"openrouter-vision"}}
  validate_config(cfg: dict) -> list[str]     errors ([] = valid): mode in ("fake","real"); every provider has unique non-empty
     "name", "kind" in (llm,image,video,vision), non-empty "model"; every name in cfg["defaults"] exists and has the kind of its
     key.  (Keys are not part of this file: they live in Settings > AI Providers.)
  pick(cfg: dict, kind: str) -> dict          the provider dict to use now.  If cfg["mode"] == "fake": the provider named
     "fake-" + kind.  Otherwise the provider named in cfg["defaults"][kind].  KeyError if none.
  load_config(path: Path) -> dict             default_config() if the file is missing, else the parsed JSON (validated; ValueError
     with the joined errors if invalid).
  save_config(path: Path, cfg: dict) -> None  validates (ValueError if invalid) then writes UTF-8 JSON indent=2.
"""
from pathlib import Path
import json


def default_config():
    return {
        "mode": "fake",
        "providers": [
            {"name": "fake-llm", "kind": "llm", "model": "fake/llm"},
            {"name": "fake-image", "kind": "image", "model": "fake/image"},
            {"name": "fake-video", "kind": "video", "model": "fake/video"},
            {"name": "fake-vision", "kind": "vision", "model": "fake/vision"},
            {"name": "openrouter-image", "kind": "image", "model": "qwen/qwen-image-3"},
            {"name": "openrouter-video", "kind": "video", "model": "google/veo-3.1-lite"},
            {"name": "openrouter-vision", "kind": "vision", "model": "google/gemini-2.5-flash-lite"},
        ],
        "defaults": {"llm": "fake-llm", "image": "openrouter-image",
                     "video": "openrouter-video", "vision": "openrouter-vision"},
    }


_KINDS = ("llm", "image", "video", "vision")


def validate_config(cfg):
    errors = []
    if cfg.get("mode") not in ("fake", "real"):
        errors.append("mode must be 'fake' or 'real'")
    providers = cfg.get("providers", [])
    names = set()
    by_name = {}
    for p in providers:
        name = p.get("name", "")
        if not name:
            errors.append("provider missing name")
        elif name in names:
            errors.append("duplicate provider name: %s" % name)
        else:
            names.add(name)
            by_name[name] = p
        if p.get("kind") not in _KINDS:
            errors.append("provider %s has invalid kind" % name)
        if not p.get("model"):
            errors.append("provider %s missing model" % name)
    for kind, name in cfg.get("defaults", {}).items():
        p = by_name.get(name)
        if p is None:
            errors.append("default %s -> unknown provider %s" % (kind, name))
        elif p.get("kind") != kind:
            errors.append("default %s -> provider %s has kind %s" % (kind, name, p.get("kind")))
    return errors


def pick(cfg, kind):
    if cfg.get("mode") == "fake":
        name = "fake-" + kind
    else:
        name = cfg["defaults"][kind]
    for p in cfg["providers"]:
        if p["name"] == name:
            return p
    raise KeyError(name)


def load_config(path):
    path = Path(path)
    if not path.exists():
        return default_config()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_config(cfg)
    if errors:
        raise ValueError("; ".join(errors))
    return cfg


def save_config(path, cfg):
    errors = validate_config(cfg)
    if errors:
        raise ValueError("; ".join(errors))
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
