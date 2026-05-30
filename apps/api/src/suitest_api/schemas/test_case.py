"""Test case + step request / response DTOs (docs/API.md §3.3).

``TestStepPublic.executable`` is a plain field — NOT a Pydantic computed property —
set at construction time from the workspace's effective capability tier (the
domain rule ``suitest_shared.domain.case.TestStep.executable(tier)``). The router
resolves the tier once per request and stamps every step.

The M1d-2 write DTOs (:class:`TestCaseCreate`, :class:`TestCaseUpdate`,
:class:`StepCreate`, :class:`StepReplace`, :class:`StepAppend`,
:class:`StepReorderRequest`) honour ``extra="forbid"`` so the API rejects
unknown fields rather than silently dropping them — caller-side typos turn into
loud 422s instead of swallowed writes. JSON wire field names use the
camelCase aliases documented in ``docs/API.md §3.3`` while Python attributes
stay snake_case.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind


class TestStepPublic(BaseModel):
    __test__ = False  # not a pytest test class

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    order: int
    action: str
    expected: str
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: str
    target_kind: TargetKind
    executable: bool


class TestCaseListItem(BaseModel):
    """List row — metadata only, no steps (docs/API.md §3.3)."""

    __test__ = False  # not a pytest test class

    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_id: str
    public_id: str
    name: str
    description: str | None = None
    source: CaseSource
    status: CaseStatus
    priority: Priority
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class TestCaseDetail(TestCaseListItem):
    """Detail — adds steps (with ``executable``) + tags."""

    __test__ = False  # not a pytest test class

    preconditions: str | None = None
    steps: list[TestStepPublic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# M1d-2 write DTOs
# ---------------------------------------------------------------------------
#
# Request payloads use camelCase JSON aliases per docs/API.md §3.3. They keep
# ``extra="forbid"`` so unknown fields raise 422 instead of being silently
# swallowed. Each write DTO is strictly minimal — the service layer fills
# server-owned fields (``public_id``, ``order_in_suite`` placement, audit
# attribution).


_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class StepCreate(BaseModel):
    """One step inside a :class:`TestCaseCreate` / :class:`StepReplace` payload.

    ``order`` is honoured if provided; otherwise the service assigns sequential
    1-based positions in array order. ``code`` MAY be omitted in CLOUD / LOCAL
    tiers (or when ``workspace.strict_zero_validation=false``); ZERO tier with
    strict validation rejects via ``STEPS_REQUIRE_CODE_IN_ZERO_LLM``.
    """

    __test__ = False  # not a pytest test class

    model_config = _WRITE_CONFIG

    action: Annotated[str, Field(min_length=1)]
    expected: str = ""
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: Annotated[str, Field(min_length=1, alias="mcpProvider")]
    target_kind: TargetKind = Field(default=TargetKind.FE_WEB, alias="targetKind")
    order: int | None = Field(default=None, ge=0)


class StepAppend(StepCreate):
    """Body shape for ``POST /test-cases/:id/steps`` — ``order`` always ignored."""

    __test__ = False  # not a pytest test class


class TestCaseCreate(BaseModel):
    """Body for ``POST /test-cases`` (docs/API.md §3.3 — sample request)."""

    __test__ = False  # not a pytest test class

    model_config = _WRITE_CONFIG

    suite_id: Annotated[str, Field(min_length=1, alias="suiteId")]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    preconditions: str | None = None
    priority: Priority = Priority.P2
    status: CaseStatus = CaseStatus.ACTIVE
    source: CaseSource = CaseSource.MANUAL
    steps: list[StepCreate] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class TestCaseUpdate(BaseModel):
    """Body for ``PATCH /test-cases/:id`` — metadata + tag replace.

    All fields optional; only ``model_dump(exclude_unset=True)`` keys are
    applied. Tags, if provided, replace the existing set in full.
    """

    __test__ = False  # not a pytest test class

    model_config = _WRITE_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    description: str | None = None
    preconditions: str | None = None
    status: CaseStatus | None = None
    priority: Priority | None = None
    tags: list[str] | None = None


class StepReplace(BaseModel):
    """Body for ``PATCH /test-cases/:id/steps`` — atomic replace."""

    __test__ = False  # not a pytest test class

    model_config = _WRITE_CONFIG

    steps: list[StepCreate] = Field(default_factory=list)


class StepReorderRequest(BaseModel):
    """Body for ``PATCH /test-cases/:id/steps/reorder`` (docs/API.md §3.3)."""

    __test__ = False  # not a pytest test class

    model_config = _WRITE_CONFIG

    step_ids_in_order: list[str] = Field(alias="stepIdsInOrder", default_factory=list)
