"""E1: project folders. A project is a folder of plain files. Standard library only.

Contract (implement exactly; tests in tests/test_project.py):
  create_project(root: Path, name: str) -> Path
      Creates root/name with subfolders clips/ and stills/ and files brief.md, Story.md, TODO.md (each a short
      non-empty text containing the project name), shots.json = {"aspect_ratio":"9:16","audio":false,"shots":[]},
      images.json = {"style":"","images":[]}.  Raises FileExistsError if the folder exists.  Rejects names that are
      empty, contain '/', '\\' or '..' with ValueError.  Returns the project path.
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


def create_project(root, name):
    if not name or '/' in name or '\\' in name or '..' in name:
        raise ValueError("invalid project name")
    project_path = Path(root) / name
    if project_path.exists():
        raise FileExistsError(f"Project {name} already exists")
    
    project_path.mkdir(parents=True)
    (project_path / "clips").mkdir()
    (project_path / "stills").mkdir()
    
    for fname, content in [
        ("brief.md", f"# Brief for {name}\n"),
        ("Story.md", f"# Story for {name}\n"),
        ("TODO.md", f"# TODO for {name}\n"),
    ]:
        (project_path / fname).write_text(content, encoding="utf-8")
    
    (project_path / "shots.json").write_text(
        json.dumps({"aspect_ratio": "9:16", "audio": False, "shots": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    (project_path / "images.json").write_text(
        json.dumps({"style": "", "images": []}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    
    return project_path


def load_json(pdir, filename):
    path = Path(pdir) / filename
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(pdir, filename, data):
    path = Path(pdir) / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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


def validate_images(data):
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
            if len(refs) > 4:
                errors.append(f"image {i}: refs must have at most 4 items")
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