"""E1: project folders. A project is a folder of plain files. Standard library only.

Contract (implement exactly; tests in tests/test_project.py):
  create_project(root: Path, name: str, format: str | None = None, brand_kit: str | None = None, kit_root: Path | None = None) -> Path
      Creates root/name with subfolders clips/ and stills/ and files brief.md, Story.md, TODO.md (each a short
      non-empty text containing the project name), shots.json = {"aspect_ratio":"9:16","audio":false,"shots":[]},
      images.json = {"style":"","images":[]}.  Raises FileExistsError if the folder exists.  Rejects names that are
      empty, contain '/', '\\' or '..' with ValueError.  Returns the project path.
      If format is provided (format id like "instagram-reel"), writes shots.json with that format's aspect_ratio
      and audio, plus "format": id; pre-fills brief length/purpose if brief.md is written; seeds a Story.md
      skeleton with N empty shot sections following templates/Story.md; seeds edit.json with aspect + caption
      defaults only if the editor's default structure is easy to reuse. format=None must behave EXACTLY as today.
      If brand_kit is provided (kit id like "acme"), the kit is COPIED into the project (brand/kit.json) and the
      project records "brand_kit": id.  The format and the kit are validated BEFORE the folder is made: an
      unknown id raises ValueError and leaves no project behind.
  load_json(pdir: Path, filename: str) -> dict        reads pdir/filename as UTF-8 JSON (Tamil must round-trip).
  save_json(pdir: Path, filename: str, data) -> None  writes UTF-8 JSON, indent=2, ensure_ascii=False.
  validate_shots(data: dict) -> list[str]
      Returns a list of human-readable error strings ([] = valid).  Rules: data["shots"] is a list; every shot has a
      unique non-empty string "id", a "model" string, an int "seconds" > 0, a non-empty "prompt" string;
      "audio" (if present) is bool; "resolution" (if present) is one of "480p","720p","1080p".
  validate_images(data: dict) -> list[str]
      Rules: data["images"] is a list; every entry has unique "id", "kind" in ("character","background","frame"),
      "out" (string ending .png or .jpg), "prompt" non-empty, "refs" a list of strings with at most 4 items and every
      ref equal to an existing entry id in the same file.
"""
from pathlib import Path
import json
import shutil

# Import here to avoid circular imports
from aistudio.formats import get_format


def create_project(root, name, format=None, brand_kit=None, kit_root=None):
    if not name or '/' in name or '\\' in name or '..' in name:
        raise ValueError("invalid project name")
    project_path = Path(root) / name
    if project_path.exists():
        raise FileExistsError(f"Project {name} already exists")

    # The format and the brand kit are checked BEFORE the folder exists: an unknown id must not leave a
    # half-made project behind (a 400 from the API, an empty folder in the workspace).
    fmt = get_format(format) if format is not None else None
    kit_source = None
    if brand_kit is not None:
        from aistudio import brand_kits
        kit_source = Path(kit_root) if kit_root is not None else Path(root).parent / "brand_kits"
        brand_kits.get_kit(kit_source, brand_kit)          # ValueError: unknown kit

    created = False
    try:
        project_path.mkdir(parents=True)
        created = True
        (project_path / "clips").mkdir()
        (project_path / "stills").mkdir()
        return _write_project(project_path, name, fmt, brand_kit, kit_source)
    except Exception:
        if created:
            shutil.rmtree(project_path, ignore_errors=True)    # never leave half a project behind
        raise


def _write_project(project_path, name, fmt, brand_kit, kit_source):
    # Default values (blank project behavior)
    aspect_ratio = "9:16"
    audio = False
    shots_count = 0
    brief_length = ""
    brief_purpose = ""
    format_id = None
    caption_defaults = None

    if fmt is not None:
        format_id = fmt["id"]
        aspect_ratio = fmt["aspect_ratio"]
        audio = fmt["audio"]
        shots_count = fmt["shots"]
        brief_length = fmt["brief"]["length"]
        brief_purpose = fmt["brief"]["purpose"]
        caption_defaults = fmt["caption"]

    # Write brief.md with format info if provided
    if fmt is not None and brief_length and brief_purpose:
        brief_content = f"""# Brief for {name}
- Length: {brief_length}
- Purpose: {brief_purpose}
"""
    else:
        brief_content = f"# Brief for {name}\n"
    (project_path / "brief.md").write_text(brief_content, encoding="utf-8")
    
    # Write Story.md with shot skeleton if format provided
    if fmt is not None and shots_count > 0:
        story_content = _build_story_skeleton(name, shots_count, aspect_ratio)
    else:
        story_content = f"# Story for {name}\n"
    (project_path / "Story.md").write_text(story_content, encoding="utf-8")
    
    (project_path / "TODO.md").write_text(f"# TODO for {name}\n", encoding="utf-8")
    
    # Write shots.json with format info
    shots_data = {"schema_version": 2, "aspect_ratio": aspect_ratio, "audio": audio, "shots": []}
    if format_id:
        shots_data["format"] = format_id
    (project_path / "shots.json").write_text(
        json.dumps(shots_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    (project_path / "images.json").write_text(
        json.dumps({"schema_version": 2, "style": "", "images": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    # Write edit.json with aspect + caption defaults if format provided
    if fmt is not None and caption_defaults:
        edit_data = {
            "version": 1,
            "aspect": aspect_ratio,
            "fps": 24,
            "tracks": {
                "video": [],
                "text": [],
                "audio": [],
                "elements": [],
                "subtitles": {
                    "cues": [],
                    "style": "classic",
                    "font": caption_defaults.get("font", "Poppins"),
                    "size": caption_defaults.get("size", 46),
                    "color": "#ffffff",
                    "bg": caption_defaults.get("bg", "#000000AA"),
                    "y": caption_defaults.get("y", 0.86)
                }
            }
        }
        (project_path / "edit.json").write_text(
            json.dumps(edit_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    if brand_kit is not None:
        from aistudio.brand_kits import attach_kit
        attach_kit(project_path, kit_source, brand_kit)
    return project_path


def _build_story_skeleton(name, shots_count, aspect_ratio):
    """Build a Story.md skeleton with N empty shot sections."""
    lines = [
        f"# {name}: AI VIDEO STORYBOARD",
        "",
        "## Concept",
        f"**Title:** {name}",
        f"**Format:** {aspect_ratio}",
        f"**Target Duration:** ~{shots_count * 4} seconds",
        "**Language:**",
        "**Characters:**",
        "**Brand:**",
        "**Core Flow:**",
        "",
        "---",
        "",
        "## Character Direction",
        "### <Name>",
        "- Role / look / age / clothes / expressions",
        "> **Consistency rule:** same face, hairstyle, clothing and setting in every clip. Every character and place has a master image.",
        "",
        "---",
        "",
        "# SHOT-BY-SHOT STORYBOARD",
        ""
    ]
    
    for i in range(1, shots_count + 1):
        shot_num = f"{i:02d}"
        lines.extend([
            f"## Shot {shot_num}",
            f"### Purpose:",
            "",
            "**Visual**",
            "",
            "**Camera**",
            "",
            "**Action**",
            "",
            "**Voice** (who speaks: ON-CAMERA dialogue with lip-sync, or OFF-CAMERA narrator voice-over)",
            "> ",
            "",
            "**English**",
            "> ",
            "",
            "**On-screen text** (added in the editor, never generated)",
            "> ",
            "",
            "**Image**: frame id from images.json (characters + background)",
            "",
            "**AI Video Prompt**",
            "> SUBJECT / ACTION (one) / CAMERA (one move) / LIGHTING / STYLE",
            "",
            "---",
            ""
        ])
    
    lines.extend([
        "# FULL VOICEOVER SCRIPT",
        "",
        "# AI VIDEO PRODUCTION NOTES",
        "- One shot per clip. Do not generate the whole video in one clip.",
        "- Claims: show results visually, no guaranteed sales/reach."
    ])
    
    return "\n".join(lines)


def load_json(pdir, filename):
    path = Path(pdir) / filename
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(pdir, filename, data):
    path = Path(pdir) / filename
    content = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    tracked = filename in {"shots.json", "images.json", "edit.json", "brief.json", "todos.json", "Story.md", "comments.json"}
    if not tracked:
        path.write_bytes(content)
        return
    previous = path.read_bytes() if tracked and path.is_file() else None
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    if previous is not None and previous != content:
        from aistudio.history import record_previous
        record_previous(pdir, filename, previous, content)


def save_text(pdir, filename, text):
    """Atomically save a tracked UTF-8 text document with prior-version history."""
    if filename != "Story.md":
        raise ValueError(f"unsupported text document: {filename}")
    path = Path(pdir) / filename
    content = str(text).encode("utf-8")
    previous = path.read_bytes() if path.is_file() else None
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    if previous is not None and previous != content:
        from aistudio.history import record_previous
        record_previous(pdir, filename, previous, content)


def validate_shots(data):
    errors = []
    shots = data.get("shots")
    if not isinstance(shots, list):
        errors.append("shots must be a list")
        return errors
    
    seen_ids = set()
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shot {i} must be an object")
            continue
        
        shot_id = shot.get("id")
        if not isinstance(shot_id, str) or not shot_id:
            errors.append(f"shot {i}: id must be a non-empty string")
        elif shot_id in seen_ids:
            errors.append(f"shot {i}: duplicate id '{shot_id}'")
        else:
            seen_ids.add(shot_id)
        
        model = shot.get("model")
        if not isinstance(model, str):
            errors.append(f"shot {i}: model must be a string")
        
        seconds = shot.get("seconds")
        if not isinstance(seconds, int) or seconds <= 0:
            errors.append(f"shot {i}: seconds must be an int > 0")
        
        prompt = shot.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            errors.append(f"shot {i}: prompt must be a non-empty string")
        
        if "audio" in shot:
            audio = shot["audio"]
            if not isinstance(audio, bool):
                errors.append(f"shot {i}: audio must be a bool")
        
        if "resolution" in shot:
            resolution = shot["resolution"]
            if resolution not in ("480p", "720p", "1080p"):
                errors.append(f"shot {i}: resolution must be one of 480p, 720p, 1080p")
    
    return errors


VIEWS = ("front", "three-quarter", "profile", "full-body", "expression")


def validate_images(data, max_refs=4):
    errors = []
    images = data.get("images")
    if not isinstance(images, list):
        errors.append("images must be a list")
        return errors
    
    seen_ids = set()
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            errors.append(f"image {i} must be an object")
            continue
        
        img_id = img.get("id")
        if not isinstance(img_id, str) or not img_id:
            errors.append(f"image {i}: id must be a non-empty string")
        elif img_id in seen_ids:
            errors.append(f"image {i}: duplicate id '{img_id}'")
        else:
            seen_ids.add(img_id)
        
        kind = img.get("kind")
        if kind not in ("character", "background", "frame", "other"):
            errors.append(f"image {i}: kind must be character, background, or frame")
        
        for v in img.get("views") or []:
            if not (isinstance(v, dict) and v.get("view") in VIEWS and isinstance(v.get("id"), str) and isinstance(v.get("file"), str)):
                errors.append(f"image {i}: each view needs id, file and view one of {', '.join(VIEWS)}")
        if img.get("role") not in (None, "style", "product"):
            errors.append(f"image {i}: role must be style or product")

        out = img.get("out")
        if not isinstance(out, str) or not (out.endswith(".png") or out.endswith(".jpg")):
            errors.append(f"image {i}: out must be a string ending with .png or .jpg")
        
        prompt = img.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            errors.append(f"image {i}: prompt must be a non-empty string")
        
        refs = img.get("refs")
        if not isinstance(refs, list):
            errors.append(f"image {i}: refs must be a list")
        else:
            if len(refs) > max_refs:
                errors.append(f"image {i}: refs must have at most {max_refs} items")
            for ref in refs:
                if not isinstance(ref, str):
                    errors.append(f"image {i}: ref must be a string")
    
    if not errors:
        for i, img in enumerate(images):
            refs = img.get("refs", [])
            for ref in refs:
                if ref not in seen_ids:
                    errors.append(f"image {i}: ref '{ref}' does not exist")
    
    return errors
