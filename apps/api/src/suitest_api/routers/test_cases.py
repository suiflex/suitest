"""Test case read + write endpoints (docs/API.md §3.3) — scoped via suite -> project -> ws.

Each ``TestStepPublic.executable`` is stamped from the workspace's effective tier:
a step is executable when it has explicit ``code`` (deterministic), or the tier is
LOCAL/CLOUD (action -> code translated at run time). The tier is resolved once per
request via :func:`resolve_workspace_tier`.

Write surface (M1d-2) covers ``POST /test-cases``, ``PATCH /test-cases/:id``,
``PATCH /test-cases/:id/steps``, ``POST /test-cases/:id/steps``,
``PATCH /test-cases/:id/steps/reorder`` and ``POST /test-cases/:id/duplicate``.
All write endpoints are gated by ``Role.QA / ADMIN / OWNER`` per ``docs/API.md
§3.3`` — VIEWER reads but never mutates. Concurrency uses ``If-Unmodified-Since``
(409 ``CONCURRENT_MODIFICATION``). Per-step validation (`STEPS_REQUIRE_CODE_IN_ZERO_LLM`
+ `MCP_PROVIDER_NOT_REGISTERED`) lives in
:mod:`suitest_api.services.test_case_validator` and surfaces here through the
canonical ``{"error": {"code", "message", "details"}}`` envelope.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Annotated, Any

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import TestStep
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, Role, Tier
from suitest_shared.schemas.pagination import Page, PageMeta

from suitest_api.auth.db import get_async_session
from suitest_api.deps.arq import get_arq
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.routers._pagination import decode_cursor_or_400, encode_next
from suitest_api.routers._tier import resolve_workspace_tier
from suitest_api.schemas.test_case import (
    AdHocRunResponse,
    BulkUpdateRequest,
    BulkUpdateResponse,
    StepAppend,
    StepReorderRequest,
    StepReplace,
    TestCaseCreate,
    TestCaseDetail,
    TestCaseListItem,
    TestCaseSearchHit,
    TestCaseUpdate,
    TestStepPublic,
)
from suitest_api.services.run_service import RunService
from suitest_api.services.test_case_service import (
    BulkLimitExceededError,
    ConcurrentModificationError,
    CrossWorkspaceIdsError,
    InvalidBulkTargetSuiteError,
    McpProviderNotRegisteredError,
    StepReorderMismatchError,
    StepsRequireCodeError,
    TestCaseService,
)
from suitest_api.ws.publisher import publish_event

# ARQ queue name shared with :mod:`suitest_api.routers.runs` — must match the
# runner's ``WorkerSettings.queue_name``. Kept inline (instead of an exported
# constant) so the test-cases router never imports from the runs router.
_RUNS_QUEUE = "suitest:runs"

router = APIRouter(prefix="/api/v1", tags=["test-cases"])

# Role gate shared by every mutating endpoint per docs/API.md §3.3.
_WRITER_ROLES: set[Role] = {Role.QA, Role.ADMIN, Role.OWNER}
_writer_dep = require_role(_WRITER_ROLES)

# Surfacing tombstoned rows via ``?includeDeleted=true`` is an admin operation
# per ``docs/API.md §3.3`` — QA cannot enumerate soft-deleted cases.
_ADMIN_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}


def _require_admin_for_include_deleted(ctx: TenantContext, include_deleted: bool) -> None:
    """Raise 403 when a non-ADMIN/OWNER asks for tombstoned rows.

    Kept as a plain function (vs. a dep factory) because ``include_deleted`` is
    a request-level query param — the gate only fires when the caller asks for
    tombstones, so the default code path stays VIEWER-friendly.
    """
    if include_deleted and ctx.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="includeDeleted requires ADMIN or OWNER",
        )


def _parse_if_unmodified_since(raw: str | None) -> datetime | None:
    """Parse an ``If-Unmodified-Since`` HTTP-date header.

    Accepts the canonical RFC 7231 IMF-fixdate form
    (``Sun, 06 Nov 1994 08:49:37 GMT``) plus ISO-8601 (so test fixtures + JS
    clients can stay direct). Returns ``None`` for an absent header. Invalid
    formats raise 400 so a typo never silently degrades to last-write-wins.
    """
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid If-Unmodified-Since header — expected HTTP-date or ISO-8601",
            ) from exc
    return parsed


def _step_executable(step: TestStep, tier: Tier) -> bool:
    """Domain rule: executable iff explicit code, or LOCAL/CLOUD with an action."""
    if step.code:
        return True
    return tier in (Tier.LOCAL, Tier.CLOUD) and bool(step.action)


def _step_public(step: TestStep, tier: Tier) -> TestStepPublic:
    return TestStepPublic(
        id=step.id,
        case_id=step.case_id,
        order=step.order,
        action=step.action,
        expected=step.expected,
        code=step.code,
        data=step.data,
        mcp_provider=step.mcp_provider,
        target_kind=step.target_kind,
        executable=_step_executable(step, tier),
    )


async def _suite_in_scope(session: AsyncSession, suite_id: str, workspace_id: str) -> bool:
    suite = await SuiteRepo(session).get_by_id(suite_id)
    if suite is None:
        return False
    project = await ProjectRepo(session).get_by_id(suite.project_id)
    return project is not None and project.workspace_id == workspace_id


async def _resolve_case_internal_id(
    session: AsyncSession, workspace_id: str, case_id: str
) -> str | None:
    """Map a path id to the internal case id, scoped to ``workspace_id``.

    The detail screen + FE editor address cases by their human-facing public id
    (``TC-1000``), but the service layer keys writes off the internal id via
    ``get_by_id``. Resolve here so every step/write endpoint accepts either form
    (matching ``GET /test-cases/:id``). Returns ``None`` when no live in-scope
    case matches — the caller raises 404.
    """
    repo = TestCaseRepo(session)
    case = await repo.get_by_id(case_id)
    if case is None:
        case = await repo.get_by_public_id(case_id, workspace_id)
    if case is None or not await _suite_in_scope(session, case.suite_id, workspace_id):
        return None
    return case.id


def _build_service(session: AsyncSession, ctx: TenantContext) -> TestCaseService:
    """Compose a :class:`TestCaseService` from a session + tenant context."""
    return TestCaseService(
        ctx,
        TestCaseRepo(session),
        SuiteRepo(session),
        ProjectRepo(session),
    )


async def _refresh_steps_public(
    request: Request,
    session: AsyncSession,
    workspace_id: str,
    case_id: str,
) -> list[TestStepPublic]:
    """Re-load + tier-stamp every step on ``case_id`` after a write."""
    tier = await resolve_workspace_tier(request, session, workspace_id)
    repo = TestCaseRepo(session)
    steps = await repo.get_steps(case_id)
    return [_step_public(s, tier) for s in steps]


async def _detail_with_steps(
    request: Request,
    session: AsyncSession,
    workspace_id: str,
    case_id: str,
) -> TestCaseDetail:
    """Build a :class:`TestCaseDetail` payload re-loaded from the DB.

    Used by the write handlers post-commit so the response reflects the same
    canonical shape as ``GET /test-cases/:id`` — single response model on the
    wire reduces the schema drift surface for the FE editor.
    """
    repo = TestCaseRepo(session)
    case = await repo.get_by_id(case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="case missing"
        )
    steps = await _refresh_steps_public(request, session, workspace_id, case.id)
    tags = await repo.get_tags(case.id)
    return TestCaseDetail(
        id=case.id,
        suite_id=case.suite_id,
        public_id=case.public_id,
        name=case.name,
        description=case.description,
        preconditions=case.preconditions,
        source=case.source,
        status=case.status,
        priority=case.priority,
        owner_id=case.owner_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        steps=steps,
        tags=tags,
        automation_file_path=case.automation_file_path,
        automation_code=case.automation_code,
        last_run_id=case.last_run_id,
        last_run_result=case.last_run_result,
        last_run_at=case.last_run_at,
        last_duration_ms=case.last_duration_ms,
    )


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


@router.get("/test-cases", response_model=Page[TestCaseListItem])
async def list_test_cases(
    suite_id: str | None = Query(default=None, alias="suiteId"),
    project_id: str | None = Query(default=None, alias="projectId"),
    status_: CaseStatus | None = Query(default=None, alias="status"),
    source: CaseSource | None = Query(default=None),
    priority: Priority | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = Query(default=False, alias="includeDeleted"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Page[TestCaseListItem]:
    """List cases by suite (filtered, paginated) or by project (all suites).

    Pass exactly one of ``suiteId`` or ``projectId``. The per-suite path applies
    the full filter/keyset-pagination contract; the per-project path returns
    every non-deleted case across the project's suites (used by the Cases tree
    which groups cases under their suites). Both 404 when the target is
    cross-workspace.

    ``?includeDeleted=true`` surfaces tombstoned rows. Per ``docs/API.md §3.3``
    that capability is ADMIN/OWNER only — QA + VIEWER asking for it get 403.
    Default behaviour (no query param / ``false``) hides every soft-deleted row
    so VIEWER reads remain safe.
    """
    _require_admin_for_include_deleted(ctx, include_deleted)
    if (suite_id is None) == (project_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pass exactly one of suiteId or projectId",
        )

    # Per-project path — flat list across all of the project's suites.
    if project_id is not None:
        project = await ProjectRepo(session).get_by_id(project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        rows = await TestCaseRepo(session).list_by_project(project_id)
        return Page[TestCaseListItem](
            items=[TestCaseListItem.model_validate(r) for r in rows],
            meta=PageMeta(next_cursor=None, limit=len(rows)),
        )

    # Per-suite path — filtered + keyset-paginated.
    assert suite_id is not None  # narrowed by the XOR guard above
    if not await _suite_in_scope(session, suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    decoded = decode_cursor_or_400(cursor)
    rows_page, next_keyset = await TestCaseRepo(session).list_by_suite_filtered(
        suite_id,
        status=status_,
        source=source,
        priority=priority,
        tag=tag,
        q=q,
        cursor=decoded,
        limit=limit,
        include_deleted=include_deleted,
    )
    return Page[TestCaseListItem](
        items=[TestCaseListItem.model_validate(r) for r in rows_page],
        meta=PageMeta(next_cursor=encode_next(next_keyset), limit=limit),
    )


@router.get("/test-cases/search", response_model=list[TestCaseSearchHit])
async def search_test_cases(
    q: str = Query(min_length=1, description="Natural-language query."),
    limit: int = Query(default=10, ge=1, le=50),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[TestCaseSearchHit]:
    """Semantic (or lexical) test-case search within the workspace (M4-2).

    Uses the configured local :class:`Embedder` (``SUITEST_EMBEDDINGS=fastembed``)
    to rank by cosine similarity; falls back to lexical scoring when embeddings
    are disabled so ZERO-tier search still returns results.
    """
    from sqlalchemy import select
    from suitest_core.embeddings import get_embedder
    from suitest_db.models.case import TestCase
    from suitest_db.models.project import Project, Suite

    from suitest_api.services.semantic_search_service import (
        Candidate,
        SemanticSearchService,
    )

    rows = (
        await session.execute(
            select(TestCase.id, TestCase.name, TestCase.title, TestCase.description)
            .join(Suite, Suite.id == TestCase.suite_id)
            .join(Project, Project.id == Suite.project_id)
            .where(Project.workspace_id == ctx.workspace_id, TestCase.deleted_at.is_(None))
        )
    ).all()
    title_by_id = {r[0]: r[2] for r in rows}
    candidates = [
        # Rank over title + name + description so both human phrasing and the
        # technical key match the query.
        Candidate(case_id=r[0], name=r[1], text=f"{r[2]}\n{r[1]}\n{r[3] or ''}".strip())
        for r in rows
    ]
    service = SemanticSearchService(get_embedder())
    hits = service.rank(q, candidates, top_k=limit)
    return [
        TestCaseSearchHit(
            case_id=h.case_id,
            name=h.name,
            title=title_by_id.get(h.case_id, h.name),
            score=round(h.score, 4),
        )
        for h in hits
    ]


@router.get("/test-cases/{case_id}", response_model=TestCaseDetail)
async def get_test_case(
    case_id: str,
    request: Request,
    include_deleted: bool = Query(default=False, alias="includeDeleted"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Return a case with its ordered steps (+ executable) and tags; 404 if cross-ws.

    Tombstoned rows are 404 by default. ADMIN/OWNER can surface them via
    ``?includeDeleted=true`` (matches the LIST contract).
    """
    _require_admin_for_include_deleted(ctx, include_deleted)
    repo = TestCaseRepo(session)
    case = (
        await repo.get_by_id_including_deleted(case_id)
        if include_deleted
        else await repo.get_by_id(case_id)
    )
    # The detail screen addresses cases by their human-facing public id
    # (``TC-1000``), so fall back to a workspace-scoped public-id lookup when the
    # path segment isn't an internal id. ``includeDeleted`` keeps the internal-id
    # path (tombstones are only addressable by internal id).
    if case is None and not include_deleted:
        case = await repo.get_by_public_id(case_id, ctx.workspace_id)
    if case is None or not await _suite_in_scope(session, case.suite_id, ctx.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    if not include_deleted and case.deleted_at is not None:
        # Defensive: ``get_by_id`` already filters tombstones but keeping the
        # explicit check makes the contract obvious if the repo changes.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    tier = await resolve_workspace_tier(request, session, ctx.workspace_id)
    steps = await repo.get_steps(case_id)
    tags = await repo.get_tags(case_id)
    return TestCaseDetail(
        id=case.id,
        suite_id=case.suite_id,
        public_id=case.public_id,
        name=case.name,
        description=case.description,
        preconditions=case.preconditions,
        source=case.source,
        status=case.status,
        priority=case.priority,
        owner_id=case.owner_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
        steps=[_step_public(s, tier) for s in steps],
        tags=tags,
        automation_file_path=case.automation_file_path,
        automation_code=case.automation_code,
        last_run_id=case.last_run_id,
        last_run_result=case.last_run_result,
        last_run_at=case.last_run_at,
        last_duration_ms=case.last_duration_ms,
    )


@router.get("/test-cases/{case_id}/steps", response_model=list[TestStepPublic])
async def get_test_case_steps(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[TestStepPublic]:
    """Return a case's steps only (step editor pre-load); 404 when cross-workspace."""
    repo = TestCaseRepo(session)
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    tier = await resolve_workspace_tier(request, session, ctx.workspace_id)
    steps: Sequence[TestStep] = await repo.get_steps(internal_id)
    return [_step_public(s, tier) for s in steps]


# ---------------------------------------------------------------------------
# M1d-2 write endpoints
# ---------------------------------------------------------------------------


def _raise_step_validation(exc: StepsRequireCodeError | McpProviderNotRegisteredError) -> None:
    """Translate a validator exception into the canonical envelope + status."""
    if isinstance(exc, StepsRequireCodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_envelope(
                "STEPS_REQUIRE_CODE_IN_ZERO_LLM",
                f"Step #{exc.step_index} has no executable code. "
                "ZERO tier cannot translate action -> MCP call at runtime.",
                {"stepIndex": exc.step_index},
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_error_envelope(
            "MCP_PROVIDER_NOT_REGISTERED",
            f"MCP provider '{exc.name}' not registered.",
            {"name": exc.name, "stepIndex": exc.step_index},
        ),
    )


def _raise_concurrent(exc: ConcurrentModificationError) -> None:
    """Translate a concurrency failure into the canonical 409 envelope."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_error_envelope(
            "CONCURRENT_MODIFICATION",
            "Test case was modified by another client.",
            {
                "resourceType": "test_case",
                "id": exc.public_id,
                "serverUpdatedAt": exc.server_updated_at.isoformat(),
            },
        ),
    )


def _raise_reorder_mismatch(exc: StepReorderMismatchError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "INVALID_STEP_REORDER",
            "Reorder body must contain every existing step id exactly once.",
            {
                "duplicate": exc.duplicates,
                "missing": exc.missing,
                "unknown": exc.unknown,
            },
        ),
    )


@router.post(
    "/test-cases",
    response_model=TestCaseDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_case(
    body: TestCaseCreate,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Create a test case + its steps + its tag set atomically."""
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.create(body)
    except StepsRequireCodeError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    except McpProviderNotRegisteredError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="suite not found")
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.patch("/test-cases/{case_id}", response_model=TestCaseDetail)
async def update_test_case(
    case_id: str,
    body: TestCaseUpdate,
    request: Request,
    if_unmodified_since: Annotated[str | None, Header(alias="If-Unmodified-Since")] = None,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Patch metadata + tag set; honours ``If-Unmodified-Since``."""
    parsed_ius = _parse_if_unmodified_since(if_unmodified_since)
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.update(case_id, body, if_unmodified_since=parsed_ius)
    except ConcurrentModificationError as exc:
        await session.rollback()
        _raise_concurrent(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.patch("/test-cases/{case_id}/steps", response_model=TestCaseDetail)
async def replace_test_case_steps(
    case_id: str,
    body: StepReplace,
    request: Request,
    if_unmodified_since: Annotated[str | None, Header(alias="If-Unmodified-Since")] = None,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Atomic replace-all-steps; honours ``If-Unmodified-Since``."""
    parsed_ius = _parse_if_unmodified_since(if_unmodified_since)
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.replace_steps(case_id, list(body.steps), if_unmodified_since=parsed_ius)
    except ConcurrentModificationError as exc:
        await session.rollback()
        _raise_concurrent(exc)
    except StepsRequireCodeError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    except McpProviderNotRegisteredError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.post(
    "/test-cases/{case_id}/steps",
    response_model=TestCaseDetail,
    status_code=status.HTTP_201_CREATED,
)
async def append_test_case_step(
    case_id: str,
    body: StepAppend,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Append one step using a row-locked ``SELECT MAX(order)`` for race safety."""
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.append_step(case_id, body)
    except StepsRequireCodeError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    except McpProviderNotRegisteredError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.patch("/test-cases/{case_id}/steps/reorder", response_model=TestCaseDetail)
async def reorder_test_case_steps(
    case_id: str,
    body: StepReorderRequest,
    request: Request,
    if_unmodified_since: Annotated[str | None, Header(alias="If-Unmodified-Since")] = None,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Atomic step reorder."""
    parsed_ius = _parse_if_unmodified_since(if_unmodified_since)
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    try:
        outcome_pair = await svc.reorder_steps(
            case_id,
            list(body.step_ids_in_order),
            if_unmodified_since=parsed_ius,
        )
    except ConcurrentModificationError as exc:
        await session.rollback()
        _raise_concurrent(exc)
    except StepReorderMismatchError as exc:
        await session.rollback()
        _raise_reorder_mismatch(exc)
    if outcome_pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    outcome, _ = outcome_pair
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


@router.post(
    "/test-cases/{case_id}/run",
    response_model=AdHocRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_test_case_now(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
    arq: ArqRedis = Depends(get_arq),
) -> AdHocRunResponse:
    """Ad-hoc shortcut: validate then delegate to M1c ``RunService.create_run``.

    Pre-flight re-runs :func:`validate_steps` against the CURRENT workspace tier
    + strict-zero setting (a case authored under LOCAL/CLOUD that later flips to
    ZERO+strict must not silently queue an unrunnable run). Validator failures
    surface through the same canonical envelope as ``POST /test-cases`` so the
    FE editor's error rendering doesn't fork. No ``runs`` row is created when
    pre-flight fails — the validator raises BEFORE we enter ``RunService.create_run``.

    On success returns 202 with ``runId`` / ``publicId`` / ``statusUrl`` /
    ``wsRoom`` so the FE can immediately deep-link to ``/runs/<publicId>`` and
    subscribe to the live ``run:<id>`` channel.
    """
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    try:
        run = await svc.trigger_adhoc_run(case_id)
    except StepsRequireCodeError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    except McpProviderNotRegisteredError as exc:
        await session.rollback()
        _raise_step_validation(exc)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")

    job = await arq.enqueue_job("run_test_case", run.id, _queue_name=_RUNS_QUEUE)
    if job is not None:
        run_service = RunService(ctx, RunRepo(session), ProjectRepo(session))
        await run_service.attach_arq_job_id(run.id, job.job_id)
    await session.commit()
    await session.refresh(run)
    return AdHocRunResponse(
        run_id=run.id,
        public_id=run.public_id,
        status_url=f"/runs/{run.public_id}",
        ws_room=f"run:{run.id}",
    )


@router.post(
    "/test-cases/{case_id}/duplicate",
    response_model=TestCaseDetail,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_test_case(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> TestCaseDetail:
    """Clone a case + its steps + tags inside the same suite (new public id)."""
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    outcome = await svc.duplicate(case_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    detail = await _detail_with_steps(request, session, ctx.workspace_id, outcome.detail.id)
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return detail


# ---------------------------------------------------------------------------
# M1d-3 soft delete + restore
# ---------------------------------------------------------------------------


@router.delete(
    "/test-cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_test_case(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Soft-delete a test case (set ``deleted_at=NOW()``).

    Returns 204 on the active -> deleted transition. Returns 404 when the row
    is cross-workspace, never existed, OR is already tombstoned — re-DELETE is
    indistinguishable from "no such row" because the default LIST / GET
    queries hide tombstones (per ``docs/API.md §3.3``).
    """
    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    case_id = internal_id
    svc = _build_service(session, ctx)
    outcome = await svc.soft_delete(case_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )


# ---------------------------------------------------------------------------
# M1d-7 bulk update
# ---------------------------------------------------------------------------


def _raise_bulk_limit(exc: BulkLimitExceededError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "BULK_LIMIT_EXCEEDED",
            f"bulk-update accepts at most {exc.limit} ids per request.",
            {"received": exc.received, "limit": exc.limit},
        ),
    )


def _raise_cross_workspace_ids(exc: CrossWorkspaceIdsError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "CROSS_WORKSPACE_IDS",
            "One or more ids do not belong to the caller's workspace.",
            {"offendingIds": exc.offending_ids},
        ),
    )


def _raise_invalid_target_suite(exc: InvalidBulkTargetSuiteError) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_error_envelope(
            "INVALID_TARGET_SUITE",
            "Target suite is not in the caller's workspace (or does not exist).",
            {"suiteId": exc.suite_id},
        ),
    )


@router.post(
    "/test-cases/bulk-update",
    response_model=BulkUpdateResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_update_test_cases(
    body: BulkUpdateRequest,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> BulkUpdateResponse:
    """Apply ``action`` (delete / move / priority / tag-add / tag-remove) to ≤100 cases.

    Single transaction (no partial apply). The Pydantic discriminator already
    narrowed ``body`` to one variant; the service validates the 100-id cap,
    the cross-workspace constraint, and the move-target before mutating. On
    success returns ``{updated, auditIds}`` and emits one WS event per affected
    case AFTER the commit so subscribers never observe a phantom event.
    """
    svc = _build_service(session, ctx)
    try:
        outcome = await svc.bulk_update(body)
    except BulkLimitExceededError as exc:
        await session.rollback()
        _raise_bulk_limit(exc)
    except CrossWorkspaceIdsError as exc:
        await session.rollback()
        _raise_cross_workspace_ids(exc)
    except InvalidBulkTargetSuiteError as exc:
        await session.rollback()
        _raise_invalid_target_suite(exc)
    await session.commit()
    for audit in outcome.audits:
        await publish_event(
            request,
            topic=f"workspace:{ctx.workspace_id}",
            event=audit.ws_event,
            data=audit.ws_payload,
        )
    return BulkUpdateResponse(
        updated=outcome.affected_count,
        audit_ids=[a.audit_id for a in outcome.audits],
    )


@router.post(
    "/test-cases/{case_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def restore_test_case(
    case_id: str,
    request: Request,
    ctx: TenantContext = Depends(_writer_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Restore a soft-deleted test case (clear ``deleted_at``).

    Idempotent per ``docs/API.md §3.3``: re-POST after restore returns 204.
    Returns 404 when the row is cross-workspace or never existed.
    """
    svc = _build_service(session, ctx)
    outcome = await svc.restore(case_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")
    await session.commit()
    if outcome.transitioned:
        await publish_event(
            request,
            topic=f"workspace:{ctx.workspace_id}",
            event=outcome.ws_event,
            data=outcome.ws_payload,
        )


# ---------------------------------------------------------------------------
# M2-12 — Code export
# ---------------------------------------------------------------------------

_EXPORT_TARGETS: frozenset[str] = frozenset({"playwright", "cypress", "selenium"})


@router.get(
    "/test-cases/{case_id}/export",
    response_class=Response,
    summary="Export test case as runnable code (docs/API.md §3.18)",
)
async def export_test_case_code(
    case_id: str,
    target: str = Query(default="playwright"),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Return test case steps as a runnable script (M2-12).

    Walks ``step.code`` and wraps each step in the target framework scaffold.
    Steps with no ``code`` render as TODO comments — always succeeds at ZERO
    tier without LLM. Writes a ``code_exports`` row for audit traceability.

    Supported ``target`` values: ``playwright`` (default), ``cypress``,
    ``selenium``. An unknown value returns 400 ``INVALID_EXPORT_TARGET``.
    """
    if target not in _EXPORT_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_envelope(
                "INVALID_EXPORT_TARGET",
                f"Unsupported target {target!r}. Choose: playwright, cypress, selenium.",
                {"target": target, "supported": sorted(_EXPORT_TARGETS)},
            ),
        )

    internal_id = await _resolve_case_internal_id(session, ctx.workspace_id, case_id)
    if internal_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")

    repo = TestCaseRepo(session)
    case = await repo.get_by_id(internal_id)
    if (
        case is None
        or case.deleted_at is not None
        or not await _suite_in_scope(session, case.suite_id, ctx.workspace_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="test case not found")

    steps: list[Any] = list(await repo.get_steps(internal_id))

    from suitest_api.services.code_export_service import export_filename, generate_export

    export_row = generate_export(
        case,
        steps,
        target,
        user_id=uuid.UUID(ctx.user_id),
    )
    session.add(export_row)
    await session.commit()

    filename = export_filename(case, target)
    return Response(
        content=export_row.exported_code_text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
