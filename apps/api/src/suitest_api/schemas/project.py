"""Project + suite response DTOs (docs/API.md §3.2, §3.4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectPublic(BaseModel):
    """A project, workspace-scoped (docs/API.md §3.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    slug: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class SuitePublic(BaseModel):
    """A suite with its non-deleted ``case_count`` (set by the service)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None = None
    order: int
    case_count: int
    created_at: datetime
    updated_at: datetime
