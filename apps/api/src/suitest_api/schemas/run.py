"""Run / run-step / log / artifact response DTOs (docs/API.md §3.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import (
    ArtifactKind,
    RunStatus,
    RunTrigger,
    StepOutcome,
    Tier,
)


class RunListItem(BaseModel):
    """List row for ``GET /runs`` (docs/API.md §3.5)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    public_id: str
    project_id: str
    name: str
    branch: str | None = None
    commit_sha: str | None = None
    env: str
    trigger: RunTrigger
    status: RunStatus
    tier_at_runtime: Tier
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class RunSummary(BaseModel):
    """Aggregate step outcomes for a run."""

    total_steps: int
    passed_steps: int
    failed_steps: int
    duration_ms: int | None = None


class RunDetail(RunListItem):
    """Detail for ``GET /runs/:id`` — adds the computed summary."""

    summary: RunSummary


class RunStepPublic(BaseModel):
    """One run step with its outcome + linked case public id (docs/API.md §3.5)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    case_id: str
    case_public_id: str
    step_order: int
    outcome: StepOutcome
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None


class RunLogPage(BaseModel):
    """A cursor-paginated slice of a run's concatenated stdout/stderr text."""

    model_config = ConfigDict(populate_by_name=True)

    lines: list[str] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class ArtifactPublic(BaseModel):
    """One artifact in ``GET /runs/:id/artifacts`` (docs/API.md §3.5)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_step_id: str
    kind: ArtifactKind
    size_bytes: int
    mime_type: str
    created_at: datetime


class ArtifactSignedUrl(BaseModel):
    """``GET /runs/:id/artifacts/:artifactId`` — presigned download URL."""

    model_config = ConfigDict(populate_by_name=True)

    artifact_id: str
    url: str
    kind: ArtifactKind
    scheme: str  # "s3" | "file"
    expires_at: datetime = Field(alias="expiresAt")
