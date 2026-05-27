"""Defect response DTOs (docs/API.md §3.6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Severity


class DefectListItem(BaseModel):
    """List row for ``GET /defects`` (docs/API.md §3.6)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    public_id: str
    workspace_id: str
    title: str
    severity: Severity
    status: DefectStatus
    component: str | None = None
    assignee_id: uuid.UUID | None = None
    agent_diagnosis_kind: DiagnosisKind
    created_at: datetime
    updated_at: datetime


class ExternalIssuePublic(BaseModel):
    """One linked external tracker issue (Jira/Linear/etc)."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    external_id: str
    external_url: str
    synced_at: datetime


class DefectDetail(DefectListItem):
    """Detail — adds linked resource public ids + external issues."""

    description: str | None = None
    test_case_public_id: str | None = None
    run_public_id: str | None = None
    requirement_public_id: str | None = None
    external_issues: list[ExternalIssuePublic] = Field(default_factory=list)


class DefectTimelineEntry(BaseModel):
    """One ordered event in a defect's history (creation + each audit row)."""

    at: datetime
    action: str
    actor_id: uuid.UUID | None = None
