"""Pydantic schemas for todos and task checklist items."""
from typing import List, Optional
from pydantic import Field
from .base import SchemaModel


class TodoItem(SchemaModel):
    id: str
    title: str
    done: bool = False


class AutoTodoItem(SchemaModel):
    id: str
    title: str
    done: bool
    progress: str = ""
    tab: str = ""


class TodosDoc(SchemaModel):
    auto: List[AutoTodoItem] = Field(default_factory=list)
    manual: List[TodoItem] = Field(default_factory=list)
