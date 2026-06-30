"""``POST /runs`` request + response DTOs (docs/API.md §3.5).

Separate module from :mod:`suitest_api.schemas.run` (read DTOs) so the create
contract has its own focused surface and the alias-heavy write body doesn't
mix with the from-attributes read DTOs. ``RunSelectionItem`` matches the
``{caseId, selectedStepIds?}`` payload the M1c frontend will send when wiring
up the "Run now" modal — selection is a list because the runner orchestrator
already supports multi-case runs (Task 12).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import RunStatus, RunTrigger, Tier


class RunSelectionItem(BaseModel):
    """One ``{caseId, selectedStepIds?}`` entry in the create-run selection.

    ``selected_step_ids`` is optional — when ``None`` the runner picks every
    active step on the case. M1c keeps this opt-in flag in the request envelope
    so a future "rerun only failed steps" UI can wire through unchanged.
    """

    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(alias="caseId")
    selected_step_ids: list[str] | None = Field(default=None, alias="selectedStepIds")


class CreateRunBody(BaseModel):
    """``POST /runs`` body. Mixed snake / camel aliases for FE convenience."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    project_id: str = Field(alias="projectId")
    name: str = Field(min_length=1, max_length=255)
    selection: list[RunSelectionItem]
    branch: str | None = None
    commit_sha: str | None = Field(default=None, alias="commitSha")
    env: str = "staging"
    trigger: RunTrigger = RunTrigger.MANUAL
    mcp_routing_override: dict[str, str] | None = Field(default=None, alias="mcpRoutingOverride")


class CreateSuiteRunBody(BaseModel):
    """``POST /suites/{id}/run`` body — run every active case in a suite as a bundle.

    All fields optional: the selection is derived server-side from the suite's
    active cases (in suite order), so the caller only supplies run metadata. ``name``
    defaults to the suite name when omitted. This is the QA "run smoke/regression
    suite" entry point — one Run row fanning out over N cases.
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    branch: str | None = None
    commit_sha: str | None = Field(default=None, alias="commitSha")
    env: str = "staging"
    trigger: RunTrigger = RunTrigger.MANUAL
    mcp_routing_override: dict[str, str] | None = Field(default=None, alias="mcpRoutingOverride")


class RunPublic(BaseModel):
    """``POST /runs`` + ``cancel`` + ``rerun`` response shape.

    Sized for the runs list/detail FE rows so cancel/rerun results render in
    place without a follow-up GET. Aliased to camelCase on serialization to
    match the M1b client.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    public_id: str = Field(serialization_alias="publicId")
    project_id: str = Field(serialization_alias="projectId")
    name: str
    branch: str | None
    commit_sha: str | None = Field(serialization_alias="commitSha")
    env: str
    trigger: RunTrigger
    status: RunStatus
    tier_at_runtime: Tier = Field(serialization_alias="tierAtRuntime")
    started_at: datetime | None = Field(serialization_alias="startedAt")
    completed_at: datetime | None = Field(serialization_alias="completedAt")
    duration_ms: int | None = Field(serialization_alias="durationMs")
    total_steps: int = Field(serialization_alias="totalSteps")
    passed_steps: int = Field(serialization_alias="passedSteps")
    failed_steps: int = Field(serialization_alias="failedSteps")
    created_at: datetime = Field(serialization_alias="createdAt")
