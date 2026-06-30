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
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag
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
    # Phase 2 (lifecycle ingest): automation source + denormalized last-run.
    automation_file_path: str | None = None
    automation_code: str | None = None  # full generated source — drives the web Code tab
    last_run_result: str | None = None
    last_run_at: datetime | None = None
    last_duration_ms: int | None = None


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


# ---------------------------------------------------------------------------
# M1d-7 bulk update DTOs
# ---------------------------------------------------------------------------
#
# ``POST /test-cases/bulk-update`` accepts a discriminated union over ``action``.
# Each variant validates its own ``payload`` so unknown / wrong-shape payloads
# turn into a Pydantic 422 BEFORE the service opens a transaction. The 100-id
# cap lives on ``ids`` so an oversize body short-circuits at parse time too —
# the router still surfaces it as the canonical ``BULK_LIMIT_EXCEEDED`` 400
# (see ``BULK_LIMIT`` constant) by wrapping the ValidationError.


class BulkAction(StrEnum):
    """Discriminator values for :class:`BulkUpdateRequest`."""

    DELETE = "delete"
    MOVE_TO_SUITE = "move_to_suite"
    SET_PRIORITY = "set_priority"
    ADD_TAGS = "add_tags"
    REMOVE_TAGS = "remove_tags"


# Hard cap from docs/API.md §3.3. Single source of truth — the router
# materialises it in the ``BULK_LIMIT_EXCEEDED`` error envelope.
BULK_LIMIT: int = 100


class _BulkDeletePayload(BaseModel):
    """``delete`` action — empty payload. Accept `{}` and absent keys both."""

    model_config = _WRITE_CONFIG


class _BulkMoveToSuitePayload(BaseModel):
    """``move_to_suite`` action — target suite id (must be same workspace)."""

    model_config = _WRITE_CONFIG

    target_suite_id: Annotated[str, Field(min_length=1, alias="suiteId")]


class _BulkSetPriorityPayload(BaseModel):
    """``set_priority`` action — wire format uses the :class:`Priority` enum."""

    model_config = _WRITE_CONFIG

    priority: Priority


class _BulkTagsPayload(BaseModel):
    """``add_tags`` / ``remove_tags`` shared payload — ``tags: list[str]``."""

    model_config = _WRITE_CONFIG

    tags: list[Annotated[str, Field(min_length=1, max_length=64)]]


class BulkDeleteRequest(BaseModel):
    """``action = "delete"`` variant."""

    model_config = _WRITE_CONFIG

    action: Literal[BulkAction.DELETE]
    ids: list[str]
    payload: _BulkDeletePayload = Field(default_factory=_BulkDeletePayload)


class BulkMoveToSuiteRequest(BaseModel):
    """``action = "move_to_suite"`` variant."""

    model_config = _WRITE_CONFIG

    action: Literal[BulkAction.MOVE_TO_SUITE]
    ids: list[str]
    payload: _BulkMoveToSuitePayload


class BulkSetPriorityRequest(BaseModel):
    """``action = "set_priority"`` variant."""

    model_config = _WRITE_CONFIG

    action: Literal[BulkAction.SET_PRIORITY]
    ids: list[str]
    payload: _BulkSetPriorityPayload


class BulkAddTagsRequest(BaseModel):
    """``action = "add_tags"`` variant."""

    model_config = _WRITE_CONFIG

    action: Literal[BulkAction.ADD_TAGS]
    ids: list[str]
    payload: _BulkTagsPayload


class BulkRemoveTagsRequest(BaseModel):
    """``action = "remove_tags"`` variant."""

    model_config = _WRITE_CONFIG

    action: Literal[BulkAction.REMOVE_TAGS]
    ids: list[str]
    payload: _BulkTagsPayload


def _bulk_discriminator(value: object) -> str | None:
    """Return the ``action`` field so Pydantic can pick the right variant.

    Accept both a parsed model (during model_validate(obj)) and a raw dict
    (during JSON parse). Returning ``None`` surfaces as a Pydantic
    discriminator error → 422.
    """
    if isinstance(value, dict):
        action = value.get("action")
        return str(action) if action is not None else None
    return getattr(value, "action", None)


BulkUpdateRequest = Annotated[
    Annotated[BulkDeleteRequest, Tag(BulkAction.DELETE.value)]
    | Annotated[BulkMoveToSuiteRequest, Tag(BulkAction.MOVE_TO_SUITE.value)]
    | Annotated[BulkSetPriorityRequest, Tag(BulkAction.SET_PRIORITY.value)]
    | Annotated[BulkAddTagsRequest, Tag(BulkAction.ADD_TAGS.value)]
    | Annotated[BulkRemoveTagsRequest, Tag(BulkAction.REMOVE_TAGS.value)],
    Discriminator(_bulk_discriminator),
]


class BulkUpdateResponse(BaseModel):
    """``POST /test-cases/bulk-update`` 200 body (docs/API.md §3.3)."""

    model_config = ConfigDict(populate_by_name=True)

    updated: int
    audit_ids: list[str] = Field(alias="auditIds", default_factory=list)


class AdHocRunResponse(BaseModel):
    """Response shape for ``POST /test-cases/:id/run`` (docs/API.md §3.3).

    A thin descriptor the FE uses to deep-link the newly queued run + open the
    matching live-events room. ``statusUrl`` is path-relative to the API root so
    the client can reuse its existing ``apiClient`` base URL; ``wsRoom`` follows
    the canonical ``run:<id>`` channel name shared with the live-events gateway.
    """

    __test__ = False  # not a pytest test class

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    public_id: str = Field(serialization_alias="publicId")
    status_url: str = Field(serialization_alias="statusUrl")
    ws_room: str = Field(serialization_alias="wsRoom")


class TestCaseSearchHit(BaseModel):
    """One semantic/lexical search result (M4-2)."""

    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(serialization_alias="caseId")
    name: str
    score: float
