"""Typed Pydantic schemas for AI Studio domain contracts."""
from copy import deepcopy
from .migrations import CURRENT, migrate
from .todos import TodoItem, AutoTodoItem, TodosDoc
from .storyboard import (
    Shot,
    ShotsDoc,
    ImageAsset,
    ImagesDoc,
    VClipTransition,
    VClip,
    TextShadow,
    TText,
    AClip,
    TracksDoc,
    EditDoc,
)
from .project import BriefField, BriefData, ProjectSummary, ProjectOverview
from .pipeline import (
    ProposalSummary,
    Proposal,
    BudgetShot,
    BudgetDoc,
    ProgressGroup,
    NextAction,
    QueueItem,
    ProductionProgress,
)

__all__ = [
    "TodoItem",
    "AutoTodoItem",
    "TodosDoc",
    "Shot",
    "ShotsDoc",
    "ImageAsset",
    "ImagesDoc",
    "VClipTransition",
    "VClip",
    "TextShadow",
    "TText",
    "AClip",
    "TracksDoc",
    "EditDoc",
    "BriefField",
    "BriefData",
    "ProjectSummary",
    "ProjectOverview",
    "ProposalSummary",
    "Proposal",
    "BudgetShot",
    "BudgetDoc",
    "ProgressGroup",
    "NextAction",
    "QueueItem",
    "ProductionProgress",
]


_DOCUMENT_MODELS = {
    "shots": ShotsDoc,
    "images": ImagesDoc,
    "edit": EditDoc,
    "brief": BriefData,
    "todos": TodosDoc,
}


def load_doc(kind, data) -> dict:
    """Migrate and validate a document while retaining every input key."""
    if kind not in _DOCUMENT_MODELS:
        raise ValueError(f"unknown document kind: {kind}")
    original = deepcopy(data)
    migrated = migrate(kind, data)
    validated = _DOCUMENT_MODELS[kind].model_validate(migrated)
    # The original is the authority for unset and unknown content; validated
    # data overlays normalized known fields and the migration version stamp.
    merged = original
    merged.update(validated.model_dump(by_alias=True, exclude_unset=True))
    return merged
