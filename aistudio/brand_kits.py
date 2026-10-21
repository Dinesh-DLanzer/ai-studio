"""Workspace storage for reusable brand kits and project attachments."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from aistudio import palette


_KIT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COLORS = re.compile(r"^#[0-9a-fA-F]{6}$")
_WATERMARK_POSITIONS = {"top-left", "top-right", "bottom-left", "bottom-right", "center"}
_MAX_LOGO_BYTES = 5 * 1024 * 1024
_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font_families():
    return {p.stem.rsplit("-", 1)[0] for p in _FONTS_DIR.glob("*.ttf")}


def _base(root):
    root = Path(root)
    return root if root.name == "brand_kits" else root / "brand_kits"


def _kit_dir(root, kit_id):
    if not isinstance(kit_id, str) or not _KIT_ID.fullmatch(kit_id):
        raise ValueError(f"invalid brand kit id: {kit_id!r}")
    return _base(root) / kit_id


def _slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    if not slug:
        raise ValueError("name must contain letters or numbers")
    return slug


def _validate(data):
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("name must be a non-empty string")
    logo = data.get("logo")
    if logo is not None and (not isinstance(logo, str) or logo not in {"logo.png", "logo.jpg", "logo.webp"}):
        raise ValueError("logo must be a managed PNG, JPEG, or WebP filename")
    palette_colors = data.get("palette", [])
    if not isinstance(palette_colors, list) or any(not isinstance(c, str) or not _COLORS.fullmatch(c) for c in palette_colors):
        raise ValueError("palette must be a list of #RRGGBB colors")
    fonts = data.get("fonts", {})
    if not isinstance(fonts, dict):
        raise ValueError("fonts must be an object")
    available = _font_families()
    for role in ("heading", "body"):
        font = fonts.get(role)
        if font is not None and (not isinstance(font, str) or font not in available):
            raise ValueError(f"fonts.{role} must be one of the available font families: {sorted(available)}")
    caption = data.get("caption", {})
    if not isinstance(caption, dict):
        raise ValueError("caption must be an object")
    if "font" in caption and (not isinstance(caption["font"], str) or caption["font"] not in available):
        raise ValueError("caption.font must be an available font family")
    if "size" in caption and (not isinstance(caption["size"], (int, float)) or isinstance(caption["size"], bool) or caption["size"] <= 0):
        raise ValueError("caption.size must be a number > 0")
    if "weight" in caption and (not isinstance(caption["weight"], int) or caption["weight"] not in (400, 500, 600, 700, 800)):
        raise ValueError("caption.weight must be one of 400, 500, 600, 700, 800")
    if "y" in caption and (not isinstance(caption["y"], (int, float)) or isinstance(caption["y"], bool) or not 0 <= caption["y"] <= 1):
        raise ValueError("caption.y must be between 0 and 1")
    if "bg" in caption and (not isinstance(caption["bg"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", caption["bg"])):
        raise ValueError("caption.bg must be a hex color")
    watermark = data.get("watermark", {})
    if not isinstance(watermark, dict):
        raise ValueError("watermark must be an object")
    if "pos" in watermark and watermark["pos"] not in _WATERMARK_POSITIONS:
        raise ValueError(f"watermark.pos must be one of {sorted(_WATERMARK_POSITIONS)}")
    if "opacity" in watermark and (not isinstance(watermark["opacity"], (int, float)) or isinstance(watermark["opacity"], bool) or not 0 <= watermark["opacity"] <= 1):
        raise ValueError("watermark.opacity must be between 0 and 1")
    end_card = data.get("end_card", {})
    if not isinstance(end_card, dict):
        raise ValueError("end_card must be an object")
    if "text" in end_card and not isinstance(end_card["text"], str):
        raise ValueError("end_card.text must be a string")
    if "seconds" in end_card and (not isinstance(end_card["seconds"], (int, float)) or isinstance(end_card["seconds"], bool) or end_card["seconds"] < 0):
        raise ValueError("end_card.seconds must be a number >= 0")
    voice = data.get("voice", {})
    if not isinstance(voice, dict) or any(k in voice and not isinstance(voice[k], str) for k in ("provider", "voice_id")):
        raise ValueError("voice.provider and voice.voice_id must be strings")
    if not isinstance(data.get("style_words", ""), str):
        raise ValueError("style_words must be a string")
    if not isinstance(data.get("avoid", []), list) or any(not isinstance(x, str) for x in data.get("avoid", [])):
        raise ValueError("avoid must be a list of strings")


def _validate_logo(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > _MAX_LOGO_BYTES:
        raise ValueError("logo must be a real image no larger than 5 MB")
    try:
        from PIL import Image
        with Image.open(path) as im:
            if im.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("logo must be PNG, JPEG, or WebP")
            im.verify()
            return {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[im.format]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("logo must be a valid PNG, JPEG, or WebP image") from exc


def _write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def create_kit(root, name, logo_path=None, **fields):
    """Create a kit under root/<slug>, returning its persisted data."""
    kit_id = _slug(name)
    directory = _kit_dir(root, kit_id)
    if directory.exists():
        raise FileExistsError(f"Brand kit {kit_id} already exists")
    data = {
        "id": kit_id, "name": name, "logo": None, "palette": [],
        "fonts": {"heading": None, "body": None},
        "caption": {"font": "Poppins", "size": 46, "weight": 700, "y": 0.86, "bg": "#000000AA"},
        "watermark": {"pos": "bottom-right", "opacity": 0.8},
        "end_card": {"text": "", "seconds": 2},
        "voice": {"provider": "", "voice_id": ""}, "style_words": "", "avoid": [],
    }
    data.update(fields)
    if logo_path is not None:
        suffix = _validate_logo(logo_path)
        data["logo"] = f"logo{suffix}"
        data["palette"] = palette.dominant_colors(logo_path)
    _validate(data)
    if data.get("logo") and logo_path is None:
        raise ValueError("provide logo_path to add a logo")
    directory.mkdir(parents=True)
    try:
        if logo_path is not None:
            shutil.copyfile(logo_path, directory / data["logo"])
        _write(directory / "kit.json", data)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return data


def list_kits(root):
    base = _base(root)
    if not base.is_dir():
        return []
    result = []
    for path in sorted(base.iterdir()):
        if path.is_dir() and path.name != "_trash" and _KIT_ID.fullmatch(path.name) and (path / "kit.json").is_file():
            result.append(get_kit(root, path.name))
    return result


def get_kit(root, kit_id):
    directory = _kit_dir(root, kit_id)
    path = directory / "kit.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"brand kit {kit_id!r} not found") from exc
    _validate(data)
    if data.get("logo"):
        _validate_logo(directory / data["logo"])
    return data


def update_kit(root, kit_id, **fields):
    directory = _kit_dir(root, kit_id)
    data = get_kit(root, kit_id)
    data.update(fields)
    _validate(data)
    if data.get("logo"):
        _validate_logo(directory / data["logo"])
    _write(directory / "kit.json", data)
    return data


def delete_kit(root, kit_id):
    directory = _kit_dir(root, kit_id)
    if not directory.is_dir():
        raise ValueError(f"brand kit {kit_id!r} not found")
    trash_dir = _base(root) / "_trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    destination = trash_dir / kit_id
    if destination.exists():
        import time
        destination = trash_dir / f"{kit_id}-{time.time_ns()}"
    directory.rename(destination)
    return destination


def attach_kit(project_dir, kit_root, kit_id):
    """Copy a kit into a project and seed its shared style, safely and idempotently."""
    kit = get_kit(kit_root, kit_id)
    # kit_root is the brand_kits directory itself for project attachment.
    source = Path(kit_root) / kit_id
    target = Path(project_dir) / "brand"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "kit.json", target / "kit.json")
    logo = kit.get("logo")
    if logo:
        src_logo = source / logo
        if src_logo.is_file():
            shutil.copyfile(src_logo, target / logo)
    from aistudio import project
    shots = project.load_json(project_dir, "shots.json")
    shots["brand_kit"] = kit_id
    project.save_json(project_dir, "shots.json", shots)
    images = project.load_json(project_dir, "images.json")
    if not images.get("style") and kit.get("style_words"):
        images["style"] = kit["style_words"]
        project.save_json(project_dir, "images.json", images)
    edit_path = Path(project_dir) / "edit.json"
    if edit_path.is_file():
        edit = project.load_json(project_dir, "edit.json")
        subtitles = edit.get("tracks", {}).get("subtitles")
        caption = kit.get("caption", {})
        if isinstance(subtitles, dict):
            for source_key, target_key in (("font", "font"), ("size", "size"), ("bg", "bg"), ("y", "y")):
                if source_key in caption:
                    subtitles[target_key] = caption[source_key]
            project.save_json(project_dir, "edit.json", edit)
    return kit


def avoid_terms(project_dir):
    path = Path(project_dir) / "brand" / "kit.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("avoid", []))
