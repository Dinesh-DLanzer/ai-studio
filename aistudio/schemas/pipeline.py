"""Pydantic schemas for proposals, budget and batch generation pipeline."""
from typing import Any, Dict, List, Optional
from pydantic import Field
from .base import SchemaModel


class ProposalSummary(SchemaModel):
    provider: Optional[str] = None
    prompt: Optional[str] = None
    seconds: Optional[float] = None
    audio: Optional[bool] = None
    first_frame: Optional[str] = None
    refs: List[str] = Field(default_factory=list)
    file: Optional[str] = None


class Proposal(SchemaModel):
    id: str
    kind: str
    shot: str
    model: str
    price: float
    status: str
    created: str = ""
    code: str = ""
    expires: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)


class BudgetShot(SchemaModel):
    id: str
    seconds: float = 4.0
    cost: float = 0.0


class BudgetDoc(SchemaModel):
    estimate: Optional[float] = None
    stop_loss: Optional[float] = None
    approved: bool = False
    created: Optional[str] = None
    clips: int = 0
    stills: int = 0
    footage_seconds: float = 0.0
    failure_rate: float = 0.0
    per_shot: List[BudgetShot] = Field(default_factory=list)


class ProgressGroup(SchemaModel):
    key: str
    label: str
    done: int
    total: int


class NextAction(SchemaModel):
    kind: str
    label: str
    target: Optional[str] = None


class QueueItem(SchemaModel):
    kind: str
    target: str
    label: str
    price: Optional[float] = None
    model: Optional[str] = None


class ProductionProgress(SchemaModel):
    groups: List[ProgressGroup] = Field(default_factory=list)
    next: Optional[NextAction] = None
    queue: List[QueueItem] = Field(default_factory=list)
