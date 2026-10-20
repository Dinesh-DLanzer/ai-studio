"""Pydantic schemas for project metadata, brief and overview."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BriefField(BaseModel):
    key: str
    label: str
    question: str
    required: bool
    value: str = ""


class BriefData(BaseModel):
    fields: List[BriefField] = Field(default_factory=list)
    complete: bool = False
    missing: List[str] = Field(default_factory=list)
    required_done: int = 0
    required_total: int = 0


class ProjectSummary(BaseModel):
    name: str
    shots: int
    spent: float
    estimate: Optional[float] = None
    approved: bool = False
    test: bool = False
    assets: int = 0
    favorite: bool = False


class ProjectOverview(BaseModel):
    name: str
    mode: str
    test_pipeline: bool
    is_test: bool
    shots: Dict[str, Any]
    images: Dict[str, Any]
    budget: Dict[str, Any]
    costs: Dict[str, Any]
    rates: Dict[str, Any]
    discarded: List[Dict[str, Any]] = Field(default_factory=list)
    proposals: List[Dict[str, Any]] = Field(default_factory=list)
    files: Dict[str, List[str]]
    reviews: Dict[str, Any] = Field(default_factory=dict)
