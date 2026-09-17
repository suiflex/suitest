"""Tool executor for the agent conversation panel (M3-12 extension).

The chat panel's model can request tools by replying with
``{"tool": "<name>", "arguments": {...}}``. This module provides the registry
of tools the CONVERSATION panel may call, wired to real services:

Read-only (auto-executed):
    ``case.get``          — case metadata + steps, addressed by public id.
    ``cases.search``      — find cases by public id or title substring.

Mutating (surfaced to the user as a confirm card; executed only after an
explicit confirm round-trip carries ``execute: true``):
    ``case.update_meta``  — title / description / priority.
    ``case.set_steps``    — full ordered replace of the case's steps.

Mutations re-use :class:`TestCaseService`, so tenant scoping, role checks,
LLM readiness, validation, and audit logging all apply unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import Priority

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.deps.scope import TenantContext
    from suitest_api.services.test_case_service import TestCaseService


class ToolDeniedError(Exception):
    """Raised when a mutation tool is invoked without a prior user confirm."""


class ToolInputError(Exception):
    """Raised when tool arguments fail validation; message is model-facing."""


class CaseGetArgs(BaseModel):
    case_id: str = Field(min_length=1, description="Public test case id, e.g. TC-1100")


class CasesSearchArgs(BaseModel):
    query: str = Field(min_length=1, description="Public id or title substring")


class CaseUpdateMetaArgs(BaseModel):
    case_id: str = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None


class StepDraft(BaseModel):
    """One step the agent wants to write. ``action`` may be empty (a draft the
    user will fill in), mirroring ``StepAppend``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", populate_by_name=True)

    action: str = ""
    expected: str = ""
    code: str | None = None
    mcp_provider: str = Field(default="playwright-mcp", alias="mcpProvider")
    target_kind: str = Field(default="FE_WEB", alias="targetKind")
    order: int | None = Field(default=None, ge=0)


class CaseSetStepsArgs(BaseModel):
    case_id: str = Field(min_length=1)
    steps: list[StepDraft] = Field(min_length=1, max_length=100)


READ_TOOLS: dict[str, type[BaseModel]] = {
    "case.get": CaseGetArgs,
    "cases.search": CasesSearchArgs,
}
WRITE_TOOLS: dict[str, type[BaseModel]] = {
    "case.update_meta": CaseUpdateMetaArgs,
    "case.set_steps": CaseSetStepsArgs,
}

# Compact description injected into the system prompt so the model knows what
# it can request and in which shape.
TOOLS_PROMPT = """
## Tools

Reply with prose, or with a single JSON object (and nothing else) to call a tool:
{"tool": "<name>", "arguments": {...}}

Read-only tools (executed immediately, result returned to you):
- case.get {"case_id": "TC-1100"} - case metadata + ordered steps.
- cases.search {"query": "login"} - match on public id or title.

Mutating tools (the user sees a confirm card; your JSON alone does nothing):
- case.update_meta {"case_id": "TC-1100", "title"?: str, "description"?: str,
  "priority"?: "P0"|"P1"|"P2"|"P3"}
- case.set_steps {"case_id": "TC-1100", "steps": [{"action": str, "expected": str,
  "code"?: str|null, "mcpProvider"?: str, "targetKind"?: str, "order"?: int}, ...]}

For step edits: call case.get first, then propose case.set_steps with the FULL
new step list (it replaces atomically). Keep every step's action non-empty.
"""


def _case_brief(detail: Any) -> dict[str, object]:
    """Compact, model-friendly projection of a TestCaseDetailOut-like object."""
    return {
        "public_id": detail.public_id,
        "title": detail.title,
        "description": detail.description,
        "priority": detail.priority,
        "status": detail.status,
        "steps": [
            {"order": s.order, "action": s.action, "expected": s.expected}
            for s in (detail.steps or [])
        ],
    }


async def execute_tool(
    tool: str,
    args: dict[str, object],
    *,
    session: AsyncSession,
    ctx: TenantContext,
    case_service: TestCaseService,
    confirmed: bool = False,
) -> dict[str, object]:
    """Execute an agent tool request.

    Read tools run immediately. Mutating tools raise :class:`ToolDeniedError`
    unless ``confirmed`` is true — the caller (SSE/WS layer) is responsible for
    surfacing the confirm card and re-invoking with the user's decision.
    """
    spec = READ_TOOLS.get(tool) or WRITE_TOOLS.get(tool)
    if spec is None:
        raise ToolInputError(f"unknown tool: {tool}")
    try:
        parsed: Any = spec.model_validate(args)
    except ValidationError as exc:
        raise ToolInputError(exc.json(indent=None)) from exc

    if tool == "case.get":
        return await _case_get(parsed, session=session, ctx=ctx)
    if tool == "cases.search":
        return await _cases_search(parsed, session=session, ctx=ctx)
    if tool == "case.update_meta":
        if not confirmed:
            raise ToolDeniedError(tool)
        return await _case_update_meta(parsed, session=session, ctx=ctx, case_service=case_service)
    if tool == "case.set_steps":
        if not confirmed:
            raise ToolDeniedError(tool)
        return await _case_set_steps(parsed, session=session, ctx=ctx, case_service=case_service)
    raise ToolInputError(f"unhandled tool: {tool}")


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


async def _resolve_case(session: AsyncSession, ctx: TenantContext, case_id: str) -> tuple[Any, Any]:
    """Resolve a public or internal case id to (row, detail) or raise."""
    repo = TestCaseRepo(session)
    row = await repo.get_by_id(case_id) or await repo.get_by_public_id(case_id, ctx.workspace_id)
    if row is None:
        raise ToolInputError(f"case not found: {case_id}")
    suite = await SuiteRepo(session).get_by_id(row.suite_id)
    if suite is None:
        raise ToolInputError(f"case not found: {case_id}")
    project = await ProjectRepo(session).get_by_id(suite.project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise ToolInputError(f"case not found: {case_id}")
    return row, suite


async def _case_get(
    args: CaseGetArgs, *, session: AsyncSession, ctx: TenantContext
) -> dict[str, object]:
    row, _suite = await _resolve_case(session, ctx, args.case_id)
    steps = await TestCaseRepo(session).get_steps(row.id)
    # Project the row onto plain dicts BEFORE touching lazy ORM attributes —
    # `row.steps` would lazy-load outside greenlet context and crash.
    brief: dict[str, object] = {
        "public_id": row.public_id,
        "title": row.title,
        "description": row.description,
        "priority": row.priority,
        "status": row.status,
        "steps": [{"order": s.order, "action": s.action, "expected": s.expected} for s in steps],
    }
    return {"found": True, "case": brief}


async def _cases_search(
    args: CasesSearchArgs, *, session: AsyncSession, ctx: TenantContext
) -> dict[str, object]:
    q = args.query.strip().lower()
    rows = await TestCaseRepo(session).list_by_workspace(ctx.workspace_id)
    items = [
        {"public_id": row.public_id, "title": row.title}
        for row in rows
        if q in row.public_id.lower() or q in (row.title or "").lower()
    ]
    return {"items": items[:25]}


# ---------------------------------------------------------------------------
# Mutating tools
# ---------------------------------------------------------------------------


async def _case_update_meta(
    args: CaseUpdateMetaArgs,
    *,
    session: AsyncSession,
    ctx: TenantContext,
    case_service: TestCaseService,
) -> dict[str, object]:
    from suitest_api.schemas.test_case import TestCaseUpdate

    row, _suite = await _resolve_case(session, ctx, args.case_id)
    # Only the keys the caller actually sent — building TestCaseUpdate with every
    # field would mark omitted ones as explicitly set and clear NOT-NULL columns
    # (title/priority) on a partial edit.
    body = TestCaseUpdate.model_validate(args.model_dump(exclude={"case_id"}, exclude_unset=True))
    outcome = await case_service.update(row.id, body, if_unmodified_since=None)
    if outcome is None:
        raise ToolInputError(f"case not found: {args.case_id}")
    return {"ok": True, "public_id": outcome.detail.public_id}


async def _case_set_steps(
    args: CaseSetStepsArgs,
    *,
    session: AsyncSession,
    ctx: TenantContext,
    case_service: TestCaseService,
) -> dict[str, object]:
    from suitest_api.schemas.test_case import StepAppend

    # replace_steps keys off the INTERNAL id — resolve the public id first.
    row, _suite = await _resolve_case(session, ctx, args.case_id)
    steps = [StepAppend.model_validate(s.model_dump(by_alias=True)) for s in args.steps]
    outcome = await case_service.replace_steps(row.id, steps, if_unmodified_since=None)
    if outcome is None:
        raise ToolInputError(f"case not found: {args.case_id}")
    return {"ok": True, "public_id": outcome.detail.public_id, "step_count": len(steps)}
