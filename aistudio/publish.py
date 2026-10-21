"""Human-directed publishing metadata and local-only delivery exports."""
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from aistudio import delivery, editor
from aistudio.schemas.base import SchemaModel

# Conservative working limits; verify against platform docs before release.
PLATFORM_LIMITS = {
    "youtube": {"title": 100, "description": 5000},
    "youtube-shorts": {"title": 100, "description": 5000},
    "tiktok": {"title": 150, "description": 2200},
    "instagram-reel": {"title": 100, "description": 2200},
    "linkedin": {"title": 200, "description": 3000},
    "x": {"title": 70, "description": 280},
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MARKUP = re.compile(r"<[^>]*>")
_TAG = re.compile(r"^#[\w]{1,64}$", re.UNICODE)


class PublishData(SchemaModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = 1
    platform: str
    title: str
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"
    chapters: list[dict] = Field(default_factory=list)
    thumbnail: str = ""
    caption_mode: str = "none"
    preset_id: str = ""
    status: str = "draft"


def validate(doc):
    """Validate and normalize metadata, raising ValueError for user-facing failures."""
    allowed = set(PublishData.model_fields)
    if not isinstance(doc, dict) or set(doc) - allowed:
        raise ValueError("publish metadata contains unknown fields")
    try:
        data = PublishData.model_validate(doc).model_dump()
    except ValidationError as exc:
        raise ValueError(str(exc)) from None
    if data["version"] != 1:
        raise ValueError("publish version must be 1")
    platform = data["platform"]
    limits = PLATFORM_LIMITS.get(platform)
    if limits is None:
        raise ValueError(f"unsupported platform: {platform}")
    if data["status"] not in ("draft", "exported"):
        raise ValueError("status must be draft or exported")
    if data["caption_mode"] not in ("sidecar_srt", "burn_in", "none"):
        raise ValueError("invalid caption mode")
    for field in ("title", "description"):
        value = _MARKUP.sub("", _CONTROL.sub("", data[field])).strip()
        if len(value) > limits[field]:
            raise ValueError(f"{field} exceeds the conservative {limits[field]} character limit for {platform}")
        data[field] = value
    if len(data["hashtags"]) > 30:
        raise ValueError("hashtags must contain at most 30 entries")
    tags = []
    for tag in data["hashtags"]:
        if not isinstance(tag, str):
            raise ValueError("hashtags must be strings")
        tag = _CONTROL.sub("", tag).strip()
        if not tag:
            continue
        tag = "#" + tag.lstrip("#").replace(" ", "")
        if not _TAG.fullmatch(tag):
            raise ValueError(f"invalid hashtag: {tag}")
        if tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    data["hashtags"] = tags
    clean_tags = []
    source_tags = data["tags"] or [t.lstrip("#") for t in tags]
    if len(source_tags) > 30 or any(not isinstance(tag, str) for tag in source_tags):
        raise ValueError("tags must contain at most 30 strings")
    for tag in source_tags:
        tag = _CONTROL.sub("", tag).strip()
        if not tag or len(tag) > 100:
            raise ValueError("each YouTube tag must contain 1 to 100 characters")
        if tag.casefold() not in {t.casefold() for t in clean_tags}:
            clean_tags.append(tag)
    data["tags"] = clean_tags
    category = str(data["category_id"]).strip()
    if not category.isdigit() or len(category) > 3:
        raise ValueError("category_id must be a YouTube category id")
    data["category_id"] = category
    if not isinstance(data["chapters"], list) or len(data["chapters"]) > 100:
        raise ValueError("chapters must be a list of at most 100 entries")
    for item in data["chapters"]:
        if not isinstance(item, dict) or set(item) - {"time", "title"} or not isinstance(item.get("time"), (int, float)) or isinstance(item.get("time"), bool) or item["time"] < 0:
            raise ValueError("each chapter needs a non-negative time and title")
        if not isinstance(item.get("title"), str) or len(item["title"]) > 120:
            raise ValueError("chapter title must be a string of at most 120 characters")
        item["title"] = _MARKUP.sub("", _CONTROL.sub("", item["title"])).strip()
    thumb = data["thumbnail"]
    if thumb:
        p = Path(thumb)
        if p.is_absolute() or ".." in p.parts or "\\" in thumb or not thumb.startswith("exports/thumbnails/"):
            raise ValueError("thumbnail must be a project-relative exports/thumbnails path")
    return data


def _atomic_save(path, payload):
    path = Path(path)
    old = path.read_bytes() if path.is_file() else None
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if old is not None and old != raw:
        folder = path.parent / ".history" / "publish.json"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = folder / f"{stamp}.json"
        archive.write_bytes(old)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return payload


def get(ws, project):
    p = ws.pdir(project) / "publish.json"
    if not p.is_file():
        return validate({"version": 1, "platform": "youtube", "title": "", "status": "draft"})
    try:
        return validate(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read publish.json: {exc}") from None


def save(ws, project, doc):
    return _atomic_save(ws.pdir(project) / "publish.json", validate(doc))


def draft_metadata(ws, project, platform):
    if platform not in PLATFORM_LIMITS:
        raise ValueError(f"unsupported platform: {platform}")
    brief = ws._read(ws.pdir(project), "brief.json", {})
    story = ws._read(ws.pdir(project), "shots.json", {})
    messages = [{"role": "system", "content": "Draft accurate, concise video publishing metadata. Return only JSON with keys platform,title,description,hashtags,chapters,thumbnail,caption_mode,preset_id,status. Do not invent facts."},
                {"role": "user", "content": json.dumps({"platform": platform, "brief": brief, "storyboard": story}, ensure_ascii=False)}]
    result = ws._ai_call(project, "chat", messages)
    if isinstance(result, dict):
        result = result.get("text", result.get("content", result))
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            raise ValueError("chat did not return valid publish metadata JSON") from None
    if not isinstance(result, dict):
        raise ValueError("chat did not return a metadata object")
    result.setdefault("version", 1)
    result.setdefault("platform", platform)
    result.setdefault("status", "draft")
    return validate(result)


def export_for(ws, project, preset_id):
    pdir = ws.pdir(project)
    preset = delivery.get_preset(preset_id)
    edit = editor.clean(ws._read(pdir, "edit.json", {}))
    rendered = pdir / editor.render(pdir, edit)
    outdir = pdir / "exports" / preset_id
    outdir.mkdir(parents=True, exist_ok=True)
    video = outdir / f"{pdir.name}.mp4"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is not installed")
    proc = subprocess.run([ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", *delivery.ffmpeg_args(preset, rendered, video)], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError("preset transcode failed: " + (proc.stderr or "ffmpeg error")[-500:])
    probe = editor.probe(video)
    issues = delivery.preflight(preset, probe or {}, edit)
    metadata = get(ws, project)
    metadata.update(platform=preset_id if preset_id in PLATFORM_LIMITS else metadata["platform"], preset_id=preset_id, caption_mode=preset["caption_mode"])
    platform_dir = outdir / "platform"
    platform_dir.mkdir(exist_ok=True)
    shutil.copy2(video, platform_dir / video.name)
    if preset["caption_mode"] == "sidecar_srt":
        cues = edit.get("tracks", {}).get("subtitles", {}).get("cues", [])
        (platform_dir / "captions.srt").write_text(editor.export_srt(cues), encoding="utf-8")
    for filename, content in (("title.txt", metadata["title"]), ("description.txt", metadata["description"]), ("hashtags.txt", " ".join(metadata["hashtags"]))):
        (platform_dir / filename).write_text(content + "\n", encoding="utf-8")
    errors = [issue for issue in issues if issue["level"] == "error"]
    metadata["status"] = "draft" if errors else "exported"
    save(ws, project, metadata)
    return {"video": str(video.relative_to(pdir).as_posix()), "folder": str(platform_dir.relative_to(pdir).as_posix()), "findings": issues, "status": metadata["status"]}


def choose_thumbnail(ws, project, source, at_seconds=0):
    pdir = ws.pdir(project)
    src = Path(source)
    if src.is_absolute() or ".." in src.parts or "\\" in source or len(src.parts) != 2:
        raise ValueError("source must be a project-relative media path")
    source_path = pdir / src
    if not source_path.is_file():
        raise ValueError("thumbnail source does not exist")
    try:
        at_seconds = float(at_seconds)
    except (TypeError, ValueError):
        raise ValueError("thumbnail time must be non-negative") from None
    if at_seconds < 0:
        raise ValueError("thumbnail time must be non-negative")
    folder = pdir / "exports" / "thumbnails"
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex[:12] + ".png"
    proc = subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-nostdin", "-ss", str(at_seconds), "-i", str(source_path), "-frames:v", "1", str(folder / name)], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError("thumbnail extraction failed: " + (proc.stderr or "ffmpeg error")[-300:])
    return f"exports/thumbnails/{name}"
