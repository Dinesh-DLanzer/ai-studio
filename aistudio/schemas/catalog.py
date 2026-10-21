"""Pydantic schema for a model capability profile (plan 13)."""
from typing import List, Optional
from pydantic import Field, ValidationError
from .base import SchemaModel

TASKS = ("text_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend", "video_to_video", "upscale", "reframe",
         "motion_transfer", "tts", "voice_clone", "music", "sfx", "lipsync", "transcribe")
SOURCES = ("user", "provider_api", "builtin", "default")


class Frames(SchemaModel):
    start: bool = True
    end: bool = False
    keyframes: int = 0


class References(SchemaModel):
    max: int = 0
    roles: List[str] = Field(default_factory=list)


class Camera(SchemaModel):
    mode: str = "prompt"
    native: List[str] = Field(default_factory=list)
    param: Optional[str] = None


class CapabilityProfile(SchemaModel):
    tasks: List[str] = Field(default_factory=list)
    durations: List[int] = Field(default_factory=list)
    resolutions: List[str] = Field(default_factory=list)
    aspect_ratios: List[str] = Field(default_factory=list)
    audio: str = "none"
    frames: Frames = Field(default_factory=Frames)
    references: References = Field(default_factory=References)
    camera: Camera = Field(default_factory=Camera)
    seed: bool = False
    negative_prompt: bool = False
    tools: str = "json"
    source: str = "default"
    verified_at: Optional[str] = None
    note: Optional[str] = None


def validate_profile(data):
    """Returns a list of problems ([] = valid)."""
    if not isinstance(data, dict):
        return ["profile must be an object"]
    try:
        p = CapabilityProfile.model_validate(data)
    except ValidationError as e:
        return [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
    out = [f"unknown task {t!r}" for t in p.tasks if t not in TASKS]
    if p.audio not in ("none", "optional", "always"):
        out.append("audio must be none, optional or always")
    if p.camera.mode not in ("native", "prompt", "none"):
        out.append("camera.mode must be native, prompt or none")
    if p.camera.mode == "native" and not p.camera.param:
        out.append("native camera needs camera.param")
    if p.tools not in ("native", "json"):
        out.append("tools must be native or json")
    if p.source not in SOURCES:
        out.append(f"source must be one of {', '.join(SOURCES)}")
    if p.references.max < 0 or p.frames.keyframes < 0 or any(d <= 0 for d in p.durations):
        out.append("counts and durations must be positive")
    return out
