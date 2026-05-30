"""Defect request + response DTOs (docs/API.md §3.6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

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
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


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


# ---------------------------------------------------------------------------
# M1d-9 write DTOs (manual defect filing + status flow)
# ---------------------------------------------------------------------------
#
# Camel-case wire aliases per docs/API.md §3.6. ``extra="forbid"`` so typos
# raise 422 rather than being silently dropped. The service layer fills
# ``public_id`` (via the ``SUIT`` sequence) + ``created_by`` (``"user:<uuid>"``)
# + ``agent_diagnosis_kind`` (defaults to ``MANUAL_TRIAGE``).


_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class DefectCreate(BaseModel):
    """Body for ``POST /defects`` — manual file (docs/API.md §3.6)."""

    model_config = _WRITE_CONFIG

    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    severity: Severity
    component: str | None = Field(default=None, max_length=120)
    test_case_id: str | None = Field(default=None, alias="testCaseId")
    run_id: str | None = Field(default=None, alias="runId")
    requirement_id: str | None = Field(default=None, alias="requirementId")
    assignee_id: uuid.UUID | None = Field(default=None, alias="assigneeId")


class DefectUpdate(BaseModel):
    """Body for ``PATCH /defects/:id`` — status / severity / assignee / description.

    ``force`` (default ``False``) lets QA+ override the linear status flow for
    workflow corrections (e.g. CLOSED → OPEN reopen after a real regression).
    Without ``force`` a non-allowed transition returns 400
    ``INVALID_STATUS_TRANSITION``.
    """

    model_config = _WRITE_CONFIG

    status: DefectStatus | None = None
    severity: Severity | None = None
    assignee_id: uuid.UUID | None = Field(default=None, alias="assigneeId")
    description: str | None = None
    component: str | None = Field(default=None, max_length=120)
    title: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    force: bool = False


class DefectSyncResponse(BaseModel):
    """Response shape for ``POST /defects/:id/sync-external``.

    M1d-9 ships the endpoint surface but the real adapter dispatch lands in
    later M1d tasks (M1d-11..15). For now any call returns
    ``501 ADAPTER_NOT_REGISTERED`` via the canonical error envelope — this DTO
    is the success shape the later tasks will fill in.
    """

    defect_id: str
    provider: str
    external_id: str
    external_url: str
    synced_at: datetime
