"""Eval harness endpoints (M4-8) — ``POST /eval/runs`` + ``GET /eval/runs/:id``.

Runs the deterministic ZERO-tier eval over the bundled golden fixtures
(``eval/fixtures``, M4-8a) and persists an :class:`EvalRun` row. ADMIN+ gated.
The fixture directory is resolved from ``SUITEST_EVAL_FIXTURES_DIR`` (default
``eval/fixtures`` relative to the process cwd).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from suitest_db.models.eval_run import EvalRun
from suitest_db.repositories.eval_runs import EvalRunRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.eval import (
    EvalFixtureResult,
    EvalFixturesEnvelope,
    EvalRunListEnvelope,
    EvalRunListItem,
    EvalRunPublic,
    EvalRunRequest,
    EvalSuiteInfo,
)
from suitest_api.services.eval_service import list_suites, run_eval

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1", tags=["eval"])

_EVAL_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}
_ZERO_MODEL_ID = "deterministic-zero"


def _fixtures_dir() -> Path:
    """Resolve the golden eval fixtures dir independent of the process cwd.

    The packaged deployment runs uvicorn with an arbitrary cwd, so the old
    cwd-relative ``eval/fixtures`` default 400'd ("fixtures dir not found").
    Resolve in order: explicit env override → cwd-relative → bundled package
    data → repo checkout (walking up from this file). Falls back to the
    cwd-relative default so the 400 message stays actionable.
    """
    env = os.environ.get("SUITEST_EVAL_FIXTURES_DIR")
    if env:
        return Path(env)

    candidates = [Path("eval/fixtures").resolve()]
    # Bundled as package data — real deployments ship fixtures inside the wheel.
    try:
        from importlib.resources import files

        candidates.append(Path(str(files("suitest_api"))) / "eval_fixtures")
    except (ModuleNotFoundError, TypeError, OSError):
        pass
    # Dev checkout: walk up from this module to a repo root holding eval/fixtures.
    candidates.extend(parent / "eval" / "fixtures" for parent in Path(__file__).resolve().parents)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path("eval/fixtures")


def _to_public(row: EvalRun) -> EvalRunPublic:
    raw = row.results_json.get("results", []) if isinstance(row.results_json, dict) else []
    results = [EvalFixtureResult.model_validate(r) for r in raw if isinstance(r, dict)]
    return EvalRunPublic(
        id=row.id,
        suite_name=row.eval_suite_name,
        fixtures_count=row.fixtures_count,
        passed=row.passed,
        failed=row.failed,
        model_id=row.model_id,
        run_at=row.run_at,
        results=results,
    )


@router.post(
    "/eval/runs",
    response_model=EvalRunPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(_EVAL_ROLES))],
)
async def create_eval_run(
    body: EvalRunRequest,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> EvalRunPublic:
    """Run the deterministic eval suite over bundled fixtures + persist the result."""
    fixtures_dir = _fixtures_dir()
    if not fixtures_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"eval fixtures dir not found: {fixtures_dir}",
        )
    result = run_eval(fixtures_dir, suite_name=body.suite_name)
    row = EvalRun(
        workspace_id=ctx.workspace_id,
        eval_suite_name=result.suite_name,
        fixtures_count=result.fixtures_count,
        passed=result.passed,
        failed=result.failed,
        model_id=_ZERO_MODEL_ID,
        results_json={
            "results": [
                {"suite": r.suite, "fixture": r.fixture, "passed": r.passed, "detail": r.detail}
                for r in result.results
            ]
        },
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_public(row)


def _score_pct(passed: int, total: int) -> float:
    return round(100.0 * passed / total, 1) if total else 0.0


@router.get(
    "/eval/runs",
    response_model=EvalRunListEnvelope,
    dependencies=[Depends(require_role(_EVAL_ROLES))],
)
async def list_eval_runs(
    suite: str | None = None,
    limit: int = 50,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> EvalRunListEnvelope:
    """Newest-first eval run history for the score-regression dashboard (M5-2)."""
    rows = await EvalRunRepo(session).list_by_workspace(
        ctx.workspace_id, suite_name=suite, limit=min(max(limit, 1), 100)
    )
    return EvalRunListEnvelope(
        items=[
            EvalRunListItem(
                id=r.id,
                suite_name=r.eval_suite_name,
                fixtures_count=r.fixtures_count,
                passed=r.passed,
                failed=r.failed,
                score_pct=_score_pct(r.passed, r.fixtures_count),
                model_id=r.model_id,
                run_at=r.run_at,
            )
            for r in rows
        ]
    )


@router.get(
    "/eval/fixtures",
    response_model=EvalFixturesEnvelope,
    dependencies=[Depends(require_role(_EVAL_ROLES))],
)
async def list_eval_fixtures(
    _ctx: TenantContext = Depends(require_workspace_membership),
) -> EvalFixturesEnvelope:
    """List the bundled golden datasets + fixture counts the weekly CI scores (M5-2)."""
    fixtures_dir = _fixtures_dir()
    if not fixtures_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"eval fixtures dir not found: {fixtures_dir}",
        )
    return EvalFixturesEnvelope(
        items=[EvalSuiteInfo(suite=s.suite, fixtures=s.fixtures) for s in list_suites(fixtures_dir)]
    )


@router.get(
    "/eval/runs/{eval_run_id}",
    response_model=EvalRunPublic,
    dependencies=[Depends(require_role(_EVAL_ROLES))],
)
async def get_eval_run(
    eval_run_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> EvalRunPublic:
    """Fetch one eval run; 404 if missing or owned by another workspace."""
    row = await session.get(EvalRun, eval_run_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval run not found")
    return _to_public(row)
