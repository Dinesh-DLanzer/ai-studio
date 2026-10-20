"""Format definitions for project templates.

A format is a JSON file in templates/formats/<id>.json with:
  id: unique identifier (kebab-case)
  label: human-readable name
  aspect_ratio: one of "9:16", "16:9", "1:1", "4:5"
  shots: int >= 1
  seconds_per_shot: int > 0
  resolution: one of "480p", "720p", "1080p"
  audio: bool
  safe_area: {top, bottom, left, right} floats 0..1
  caption: {font, size, weight, y, bg}
  cta: {text, last_seconds}
  loudness: int (LUFS target)
  brief: {length, purpose}
  suggested_models: {video: [model_ids]}
  notes: string (e.g., "Platform margins must be re-verified")
"""
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
FORMATS_DIR = REPO_ROOT / "templates" / "formats"

VALID_ASPECT_RATIOS = ("9:16", "16:9", "1:1", "4:5")
VALID_RESOLUTIONS = ("480p", "720p", "1080p")


def _validate_format(data: dict, filepath: Path) -> None:
    """Raise ValueError with a clear message for bad values."""
    # id
    fid = data.get("id")
    if not isinstance(fid, str) or not fid:
        raise ValueError(f"{filepath.name}: 'id' must be a non-empty string")
    if fid != filepath.stem:
        raise ValueError(f"{filepath.name}: 'id' must match filename (expected '{filepath.stem}')")

    # label
    label = data.get("label")
    if not isinstance(label, str) or not label:
        raise ValueError(f"{filepath.name}: 'label' must be a non-empty string")

    # aspect_ratio
    aspect = data.get("aspect_ratio")
    if aspect not in VALID_ASPECT_RATIOS:
        raise ValueError(f"{filepath.name}: 'aspect_ratio' must be one of {VALID_ASPECT_RATIOS}, got {aspect!r}")

    # shots
    shots = data.get("shots")
    if not isinstance(shots, int) or shots < 1:
        raise ValueError(f"{filepath.name}: 'shots' must be an int >= 1, got {shots!r}")

    # seconds_per_shot
    sps = data.get("seconds_per_shot")
    if not isinstance(sps, int) or sps <= 0:
        raise ValueError(f"{filepath.name}: 'seconds_per_shot' must be an int > 0, got {sps!r}")

    # resolution
    resolution = data.get("resolution")
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError(f"{filepath.name}: 'resolution' must be one of {VALID_RESOLUTIONS}, got {resolution!r}")

    # audio
    audio = data.get("audio")
    if not isinstance(audio, bool):
        raise ValueError(f"{filepath.name}: 'audio' must be a bool, got {audio!r}")

    # safe_area
    safe = data.get("safe_area")
    if not isinstance(safe, dict):
        raise ValueError(f"{filepath.name}: 'safe_area' must be an object")
    for key in ("top", "bottom", "left", "right"):
        val = safe.get(key)
        if not isinstance(val, (int, float)) or val < 0 or val > 1:
            raise ValueError(f"{filepath.name}: 'safe_area.{key}' must be a float 0..1, got {val!r}")

    # caption
    cap = data.get("caption")
    if not isinstance(cap, dict):
        raise ValueError(f"{filepath.name}: 'caption' must be an object")
    for key in ("font", "size", "weight", "y", "bg"):
        if key not in cap:
            raise ValueError(f"{filepath.name}: 'caption.{key}' is required")
    if not isinstance(cap["font"], str) or not cap["font"]:
        raise ValueError(f"{filepath.name}: 'caption.font' must be a non-empty string")
    if not isinstance(cap["size"], (int, float)) or cap["size"] <= 0:
        raise ValueError(f"{filepath.name}: 'caption.size' must be a number > 0")
    if not isinstance(cap["weight"], int) or cap["weight"] not in (400, 500, 600, 700, 800):
        raise ValueError(f"{filepath.name}: 'caption.weight' must be one of 400, 500, 600, 700, 800")
    if not isinstance(cap["y"], (int, float)) or cap["y"] < 0 or cap["y"] > 1:
        raise ValueError(f"{filepath.name}: 'caption.y' must be a float 0..1")
    if not isinstance(cap["bg"], str) or not cap["bg"].startswith("#"):
        raise ValueError(f"{filepath.name}: 'caption.bg' must be a hex color string")

    # cta
    cta = data.get("cta")
    if not isinstance(cta, dict):
        raise ValueError(f"{filepath.name}: 'cta' must be an object")
    if "text" not in cta or not isinstance(cta["text"], str) or not cta["text"]:
        raise ValueError(f"{filepath.name}: 'cta.text' must be a non-empty string")
    if "last_seconds" not in cta or not isinstance(cta["last_seconds"], (int, float)) or cta["last_seconds"] < 0:
        raise ValueError(f"{filepath.name}: 'cta.last_seconds' must be a number >= 0")

    # loudness
    loudness = data.get("loudness")
    if not isinstance(loudness, int):
        raise ValueError(f"{filepath.name}: 'loudness' must be an int (LUFS)")

    # brief
    brief = data.get("brief")
    if not isinstance(brief, dict):
        raise ValueError(f"{filepath.name}: 'brief' must be an object")
    if "length" not in brief or not isinstance(brief["length"], str) or not brief["length"]:
        raise ValueError(f"{filepath.name}: 'brief.length' must be a non-empty string")
    if "purpose" not in brief or not isinstance(brief["purpose"], str) or not brief["purpose"]:
        raise ValueError(f"{filepath.name}: 'brief.purpose' must be a non-empty string")

    # suggested_models
    sm = data.get("suggested_models")
    if not isinstance(sm, dict):
        raise ValueError(f"{filepath.name}: 'suggested_models' must be an object")
    if "video" not in sm or not isinstance(sm["video"], list):
        raise ValueError(f"{filepath.name}: 'suggested_models.video' must be a list")
    for m in sm["video"]:
        if not isinstance(m, str) or not m:
            raise ValueError(f"{filepath.name}: 'suggested_models.video[]' must be non-empty strings")

    # notes (optional but recommended)
    if "notes" not in data:
        raise ValueError(f"{filepath.name}: 'notes' field is required (e.g., 'Platform margins must be re-verified')")
    if not isinstance(data["notes"], str) or not data["notes"]:
        raise ValueError(f"{filepath.name}: 'notes' must be a non-empty string")


def load_formats() -> list[dict]:
    """Load and validate all format JSON files from templates/formats/.
    Returns a list of format dicts, sorted by id.
    Raises ValueError if any file is invalid.
    """
    if not FORMATS_DIR.is_dir():
        return []
    formats = []
    for path in sorted(FORMATS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name}: invalid JSON: {e}") from e
        _validate_format(data, path)
        formats.append(data)
    return formats


def get_format(format_id: str) -> dict:
    """Load a single format by id (e.g., 'instagram-reel').
    Raises ValueError if not found or invalid.
    """
    path = FORMATS_DIR / f"{format_id}.json"
    if not path.is_file():
        raise ValueError(f"Format '{format_id}' not found in {FORMATS_DIR}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Format '{format_id}': invalid JSON: {e}") from e
    _validate_format(data, path)
    return data