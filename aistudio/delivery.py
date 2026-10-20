"""Platform delivery presets and export pre-flight checks."""

import json
import math
from pathlib import Path


_PRESET_DIR = Path(__file__).resolve().parent.parent / "templates" / "delivery"
_REQUIRED = {
    "id", "label", "container", "video_codec", "pixel_format", "crf",
    "max_bitrate_kbps", "audio_codec", "audio_bitrate_kbps", "sample_rate",
    "aspect_ratios", "max_seconds", "min_seconds", "loudness_lufs",
    "caption_mode", "thumbnail", "notes",
}
_CAPTION_MODES = {"sidecar_srt", "burn_in", "none"}


def _number(value, name, *, minimum=None, maximum=None, integer=False):
    valid_type = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not valid_type or not math.isfinite(value):
        raise ValueError(f"preset {name} must be a {'positive integer' if integer else 'number'}")
    if minimum is not None and value < minimum:
        raise ValueError(f"preset {name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"preset {name} must be at most {maximum}")


def _validate_preset(preset, source="preset"):
    if not isinstance(preset, dict):
        raise ValueError(f"{source} must be a JSON object")
    missing = sorted(_REQUIRED - preset.keys())
    if missing:
        raise ValueError(f"{source} is missing required fields: {', '.join(missing)}")
    for field in ("id", "label", "container", "video_codec", "pixel_format", "audio_codec", "notes"):
        if not isinstance(preset[field], str) or not preset[field].strip():
            raise ValueError(f"{source} field {field} must be a non-empty string")
    if preset["container"] != "mp4":
        raise ValueError(f"{source} container must be mp4")
    for field, minimum, maximum, integer in (
        ("crf", 0, 51, True),
        ("max_bitrate_kbps", 1, None, True),
        ("audio_bitrate_kbps", 1, None, True),
        ("sample_rate", 1, None, True),
        ("max_seconds", 0, None, False),
        ("min_seconds", 0, None, False),
        ("loudness_lufs", -100, 0, False),
    ):
        _number(preset[field], field, minimum=minimum, maximum=maximum, integer=integer)
    if preset["min_seconds"] > preset["max_seconds"]:
        raise ValueError(f"{source} min_seconds must not exceed max_seconds")
    ratios = preset["aspect_ratios"]
    if not isinstance(ratios, list) or not ratios:
        raise ValueError(f"{source} aspect_ratios must be a non-empty list")
    for ratio in ratios:
        try:
            parts = ratio.split(":")
            if len(parts) != 2 or min(int(part) for part in parts) <= 0:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"{source} aspect_ratios entries must use positive W:H values") from None
    if preset["caption_mode"] not in _CAPTION_MODES:
        raise ValueError(f"{source} caption_mode must be one of: {', '.join(sorted(_CAPTION_MODES))}")
    thumb = preset["thumbnail"]
    if not isinstance(thumb, dict) or not {"w", "h"}.issubset(thumb):
        raise ValueError(f"{source} thumbnail must contain w and h")
    _number(thumb["w"], "thumbnail.w", minimum=1, integer=True)
    _number(thumb["h"], "thumbnail.h", minimum=1, integer=True)
    if "safe_area" in preset:
        safe = preset["safe_area"]
        if not isinstance(safe, dict):
            raise ValueError(f"{source} safe_area must be an object")
        for band in ("top", "bottom"):
            if band in safe:
                _number(safe[band], f"safe_area.{band}", minimum=0, maximum=1)
        if safe.get("top", 0) + safe.get("bottom", 0) >= 1:
            raise ValueError(f"{source} safe_area top and bottom bands must total less than 1")
    return preset


def load_presets():
    """Load and validate every JSON preset in templates/delivery."""
    presets = {}
    try:
        files = sorted(_PRESET_DIR.glob("*.json"))
        if not files:
            raise ValueError(f"no delivery presets found in {_PRESET_DIR}")
        for path in files:
            try:
                preset = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"cannot load delivery preset {path.name}: {exc}") from None
            _validate_preset(preset, path.name)
            if preset["id"] != path.stem:
                raise ValueError(f"{path.name} id must match its filename")
            if preset["id"] in presets:
                raise ValueError(f"duplicate delivery preset id: {preset['id']}")
            presets[preset["id"]] = preset
    except OSError as exc:
        raise ValueError(f"cannot read delivery presets: {exc}") from None
    return presets


def get_preset(preset_id):
    """Return a validated preset by id."""
    presets = load_presets()
    try:
        return presets[preset_id]
    except (KeyError, TypeError):
        raise ValueError(f"unknown delivery preset: {preset_id!r}") from None


def ffmpeg_args(preset, src, dst):
    """Build ffmpeg argv for a preset. No shell or filter graph is involved."""
    if isinstance(preset, str):
        preset = get_preset(preset)
    preset = _validate_preset(preset)
    bitrate = preset["max_bitrate_kbps"]
    return [
        "-i", str(src),
        "-c:v", preset["video_codec"],
        "-crf", str(preset["crf"]),
        "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k",
        "-pix_fmt", preset["pixel_format"],
        "-c:a", preset["audio_codec"],
        "-b:a", f"{preset['audio_bitrate_kbps']}k",
        "-ar", str(preset["sample_rate"]),
        "-movflags", "+faststart",
        str(dst),
    ]


def preflight(preset, probe, edit=None):
    """Return export issues using probe metadata and optional editor text tracks."""
    if isinstance(preset, str):
        preset = get_preset(preset)
    preset = _validate_preset(preset)
    if not isinstance(probe, dict):
        raise ValueError("probe must be a dict with duration, width, and height")
    issues = []

    duration = probe.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration):
        raise ValueError("probe duration must be a finite number")
    if duration < preset["min_seconds"]:
        issues.append({"level": "error", "code": "duration_min", "message": f"Duration {duration:g}s is shorter than the {preset['min_seconds']:g}s minimum."})
    if duration > preset["max_seconds"]:
        issues.append({"level": "error", "code": "duration_max", "message": f"Duration {duration:g}s exceeds the {preset['max_seconds']:g}s maximum."})

    width, height = probe.get("width"), probe.get("height")
    if (isinstance(width, bool) or not isinstance(width, (int, float)) or width <= 0
            or isinstance(height, bool) or not isinstance(height, (int, float)) or height <= 0):
        issues.append({"level": "warn", "code": "aspect_unavailable", "message": "Video dimensions are unavailable; aspect ratio could not be checked."})
    else:
        ratio = width / height
        allowed = [tuple(map(int, item.split(":"))) for item in preset["aspect_ratios"]]
        if not any(math.isclose(ratio, w / h, rel_tol=0.01) for w, h in allowed):
            label = ":".join(str(int(v)) for v in (width, height))
            expected = ", ".join(preset["aspect_ratios"])
            issues.append({"level": "error", "code": "aspect_ratio", "message": f"Video aspect ratio {label} does not match preset ratios: {expected}."})

    audio = probe.get("audio", probe.get("has_audio"))
    if audio is False:
        issues.append({"level": "error", "code": "audio_missing", "message": "Audio is missing; this preset expects an audio stream."})

    safe = preset.get("safe_area")
    tracks = (edit or {}).get("tracks", {}) if isinstance(edit, dict) else {}
    if safe and isinstance(tracks, dict):
        top, bottom = safe.get("top", 0), safe.get("bottom", 0)
        for item in tracks.get("text", []) or []:
            y = item.get("y") if isinstance(item, dict) else None
            if isinstance(y, (int, float)) and not isinstance(y, bool) and (y < top or y > 1 - bottom):
                issues.append({
                    "level": "warn", "code": "text_safe_area",
                    "message": f"Text item {item.get('id', '(unnamed)')} at y={y:g} falls in the unsafe top or bottom band.",
                })
    return issues
