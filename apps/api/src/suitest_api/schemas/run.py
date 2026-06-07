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


class StateChangePublic(BaseModel):
    """One key-level state change at a replay step (M5-1)."""

    model_config = ConfigDict(populate_by_name=True)

    path: str
    op: str = Field(description="added | removed | changed")
    before: str | None = None
    after: str | None = None


class RunReplayStep(BaseModel):
    """One step in the time-travel replay, with its state delta vs. the prior step."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    step_order: int = Field(serialization_alias="stepOrder")
    case_public_id: str = Field(serialization_alias="casePublicId")
    outcome: StepOutcome
    duration_ms: int | None = Field(default=None, serialization_alias="durationMs")
    started_at: datetime | None = Field(default=None, serialization_alias="startedAt")
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")
    state_snapshot: dict[str, object] | None = Field(
        default=None, serialization_alias="stateSnapshot"
    )
    delta: list[StateChangePublic] = Field(default_factory=list)


class RunReplayResponse(BaseModel):
    """``GET /runs/:id/replay`` — ordered steps + per-step state delta (M5-1)."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    steps: list[RunReplayStep] = Field(default_factory=list)


class RunLogItem(BaseModel):
    """One persisted ``run_step_logs`` row in the page (M1c).

    ``message`` is the JSON-encoded event payload the orchestrator published —
    the FE deserialises it on receipt to match the live socket stream.
    """

    model_config = ConfigDict(populate_by_name=True)

    seq: int
    level: str
    message: str
    created_at: datetime = Field(serialization_alias="createdAt")


class RunLogPage(BaseModel):
    """A cursor-paginated slice of a run's persisted log stream (M1c)."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[RunLogItem] = Field(default_factory=list)
    next_cursor: int = Field(serialization_alias="nextCursor")
    has_more: bool = Field(serialization_alias="hasMore")


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
    """``GET /runs/:id/artifacts/:artifactId`` — presigned download URL (M1c).

    The M1a stub returned a placeholder URL alongside the artifact id + scheme;
    M1c replaces it with a real S3 / MinIO presign + the artifact's MIME type
    so the FE can decide how to render the response (inline image vs. download).
    """

    model_config = ConfigDict(populate_by_name=True)

    url: str
    expires_in_seconds: int = Field(serialization_alias="expiresInSeconds")
    kind: ArtifactKind
    mime_type: str = Field(serialization_alias="mimeType")


class RunsSummary(BaseModel):
    """``GET /runs/summary`` — counters for the Runs dashboard summary bar.

    Field aliases are camelCase to match the M1b frontend client.
    ``failed`` folds ``FAIL`` + ``ERROR``; ``avg_duration_ms`` is a workspace-wide
    weighted mean across non-null durations.
    """

    model_config = ConfigDict(populate_by_name=True)

    active: int = Field(description="Runs currently in RUNNING state")
    today: int = Field(description="Runs created since 00:00 UTC")
    passed: int
    failed: int = Field(description="FAIL + ERROR")
    avg_duration_ms: int = Field(alias="avgDurationMs")
    queued: int


class NetworkEvent(BaseModel):
    """One network event captured during a run (HAR-derived, M1c)."""

    model_config = ConfigDict(populate_by_name=True)

    method: str
    path: str
    status: int
    duration_ms: int = Field(alias="durationMs")
    started_at: datetime = Field(alias="startedAt")


class RunNetworkResponse(BaseModel):
    """``GET /runs/:id/network`` — bounded network event list (M1b stub)."""

    items: list[NetworkEvent] = Field(default_factory=list)
