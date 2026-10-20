"""Pydantic schemas for todos and task checklist items."""
from typing import List, Optional
from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    id: str
    title: str
    done: bool = False


class AutoTodoItem(BaseModel):
    id: str
    title: str
    done: bool
    progress: str = ""
    tab: str = ""


class TodosDoc(BaseModel):
    auto: List[AutoTodoItem] = Field(default_factory=list)
    manual: List[TodoItem] = Field(default_factory=list)
