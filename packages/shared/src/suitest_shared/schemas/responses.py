"""Response DTOs returned by the API service layer.

These are deliberately separate from the SQLAlchemy ORM models: services map an
ORM row -> a DTO so the HTTP boundary never leaks ORM internals (lazy-load
triggers, encrypted columns, relationship objects). ``from_attributes=True`` (via
:class:`~suitest_shared.domain.base.DomainModel`) lets a DTO be built straight
from an ORM row with ``Dto.model_validate(row)``.

Security note: :class:`IntegrationOut` intentionally OMITS ``secrets_encrypted``
— the field simply does not exist on the DTO, so it can never be serialised over
the wire. See ``IntegrationService``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from suitest_shared.domain.base import DomainModel
from suitest_shared.domain.enums import (
    ArtifactKind,
    CaseSource,
    CaseStatus,
    DefectStatus,
    DiagnosisKind,
    DocumentKind,
    IntegrationKind,
    Priority,
    RunStatus,
    RunTrigger,
    Severity,
    StepOutcome,
    TargetKind,
    Tier,
)


class WorkspaceOut(DomainModel):
    id: str
    slug: str
    name: str
    region: str
    created_at: datetime
    updated_at: datetime


class ProjectOut(DomainModel):
    id: str
    workspace_id: str
    slug: str
    name: str
    description: str | None = None
    gating_suite_id: str | None = None
    default_mcp_routing: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SuiteOut(DomainModel):
    id: str
    project_id: str
    name: str
    description: str | None = None
    order: int
    created_at: datetime
    updated_at: datetime


class TestStepOut(DomainModel):
    __test__ = False  # not a pytest test class

    id: str
    case_id: str
    order: int
    action: str
    expected: str
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: str
    target_kind: TargetKind


class TestCaseOut(DomainModel):
    __test__ = False  # not a pytest test class

    id: str
    suite_id: str
    public_id: str
    # ``name`` = legacy technical field; UI renders ``title``; ``slug`` is the
    # technical key (docs/DATA_MODEL.md §3.4).
    name: str
    title: str
    slug: str | None = None
    description: str | None = None
    preconditions: str | None = None
    source: CaseSource
    status: CaseStatus
    priority: Priority
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class TestCaseDetailOut(TestCaseOut):
    __test__ = False  # not a pytest test class

    steps: list[TestStepOut] = Field(default_factory=list)


class RequirementOut(DomainModel):
    id: str
    project_id: str
    public_id: str
    title: str
    description: str | None = None
    source: str | None = None
    external_url: str | None = None
    created_at: datetime
    updated_at: datetime


class TraceabilityRow(DomainModel):
    """One requirement row in the traceability matrix with its linked case ids."""

    requirement_id: str
    public_id: str
    title: str
    case_ids: list[str] = Field(default_factory=list)
    covered: bool


class TraceabilityMatrixOut(DomainModel):
    project_id: str
    rows: list[TraceabilityRow] = Field(default_factory=list)


class RunOut(DomainModel):
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
    total_steps: int
    passed_steps: int
    failed_steps: int
    created_at: datetime
    updated_at: datetime


class ArtifactOut(DomainModel):
    id: str
    run_step_id: str
    kind: ArtifactKind
    url: str
    size_bytes: int
    mime_type: str
    created_at: datetime


class SignedUrlOut(DomainModel):
    """Presigned download URL for an artifact object."""

    artifact_id: str
    url: str
    expires_in: int


class DefectOut(DomainModel):
    id: str
    public_id: str
    workspace_id: str
    title: str
    description: str | None = None
    severity: Severity
    status: DefectStatus
    component: str | None = None
    assignee_id: uuid.UUID | None = None
    test_case_id: str | None = None
    run_id: str | None = None
    requirement_id: str | None = None
    agent_diagnosis_kind: DiagnosisKind
    created_at: datetime
    updated_at: datetime


class IntegrationOut(DomainModel):
    """Integration view with secrets REDACTED.

    ``secrets_encrypted`` is intentionally absent — it is never serialised. A
    boolean ``has_secrets`` flag tells the UI whether a secret is configured
    without exposing it.
    """

    id: str
    workspace_id: str
    kind: IntegrationKind
    name: str
    config: dict[str, Any]
    status: str
    has_secrets: bool
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentOut(DomainModel):
    id: str
    workspace_id: str
    kind: DocumentKind
    source: str
    title: str
    content_hash: str
    indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# -- analytics ------------------------------------------------------------


class KpiOut(DomainModel):
    project_id: str
    period: str
    total_runs: int
    pass_rate: float
    total_cases: int
    open_defects: int


class PassRateOut(DomainModel):
    project_id: str
    period: str
    pass_rate: float
    sample_size: int


class CoverageOut(DomainModel):
    project_id: str
    total_requirements: int
    covered_requirements: int
    coverage_rate: float


class FlakyCaseOut(DomainModel):
    __test__ = False  # not a pytest test class

    case_id: str = Field(alias="caseId")
    public_id: str = Field(alias="publicId")
    flake_rate: float = Field(alias="flakeRate")
    sample_size: int = Field(alias="sampleSize")


class HeatmapCellOut(DomainModel):
    case_id: str
    public_id: str
    outcomes: list[StepOutcome] = Field(default_factory=list)


class HeatmapOut(DomainModel):
    project_id: str
    period: str
    cells: list[HeatmapCellOut] = Field(default_factory=list)


class ReadinessOut(DomainModel):
    project_id: str
    score: float
    pass_rate: float
    coverage_rate: float
    open_critical_defects: int
    ready: bool


# -- capability -----------------------------------------------------------


class WorkspaceCapabilityOut(DomainModel):
    """Resolved deployment capabilities with the optional per-workspace overlay."""

    workspace_id: str
    tier: Tier
    features: dict[str, bool]
    overlay_applied: bool
