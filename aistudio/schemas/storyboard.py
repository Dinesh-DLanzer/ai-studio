"""Pydantic schemas for storyboard shots, images and timeline assets."""
from typing import Any, Dict, List, Optional
from pydantic import Field
from .base import SchemaModel


class Shot(SchemaModel):
    id: str
    prompt: str = ""
    seconds: int = 4
    model: Optional[str] = None
    resolution: Optional[str] = None
    audio: bool = False
    first_frame: Optional[str] = None
    final_ok: Optional[bool] = None
    final_clip: Optional[str] = None
    note: Optional[str] = None
    camera: Optional[str] = None
    direction: Optional[Dict[str, Any]] = None
    end_frame: Optional[str] = None
    keyframes: Optional[List[Dict[str, Any]]] = None
    action: Optional[str] = None
    voice_mode: Optional[str] = None
    voice_line: Optional[str] = None
    english: Optional[str] = None
    on_screen_text: Optional[List[str]] = None
    refs: Optional[List[str]] = None
    aspect_ratio: Optional[str] = None
    uses: Optional[List[str]] = None
    purpose: Optional[str] = None
    visual: Optional[str] = None
    image: Optional[str] = None
    number: Optional[int] = None
    time: Optional[str] = None


class ShotsDoc(SchemaModel):
    shots: List[Shot] = Field(default_factory=list)
    language: Optional[str] = None
    final_resolution: str = "720p"
    aspect_ratio: str = "9:16"


class ImageAsset(SchemaModel):
    id: str
    kind: str = "character"
    out: str = ""
    prompt: str = ""
    refs: List[str] = Field(default_factory=list)
    aspect_ratio: str = "3:2"
    uses: Optional[List[str]] = None
    purpose: Optional[str] = None


class ImagesDoc(SchemaModel):
    style: str = ""
    images: List[ImageAsset] = Field(default_factory=list)


class VClipTransition(SchemaModel):
    type: str = "cut"
    dur: float = 0.5


class VClip(SchemaModel):
    id: str
    src: str
    in_: float = Field(0.0, alias="in")
    out: float
    volume: float = 1.0
    transition: VClipTransition = Field(default_factory=VClipTransition)


class TextShadow(SchemaModel):
    on: bool = True
    color: str = "#000000"
    blur: float = 4.0


class TText(SchemaModel):
    id: str
    text: str
    start: float
    end: float
    x: float = 0.5
    y: float = 0.8
    font: str = "Inter"
    weight: int = 400
    size: float = 32.0
    color: str = "#FFFFFF"
    bg: Optional[str] = None
    align: str = "center"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    caps: bool = False
    opacity: float = 1.0
    shadow: TextShadow = Field(default_factory=TextShadow)


class AClip(SchemaModel):
    id: str
    src: str
    start: float = 0.0
    in_: float = Field(0.0, alias="in")
    out: float
    volume: float = 1.0
    fadeIn: float = 0.0
    fadeOut: float = 0.0
    name: Optional[str] = None


class TracksDoc(SchemaModel):
    video: List[VClip] = Field(default_factory=list)
    text: List[TText] = Field(default_factory=list)
    audio: List[AClip] = Field(default_factory=list)


class EditDoc(SchemaModel):
    version: int = 1
    aspect: str = "9:16"
    fps: int = 24
    tracks: TracksDoc = Field(default_factory=TracksDoc)
