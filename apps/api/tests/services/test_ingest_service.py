"""DB-backed ingest service tests — retest hardening.

Covers: project binding validate/repair/never-recreate, TestCase reuse on
retest (no duplicates), STALE marking + reactivation, per-retest TestRun
creation, and failureKind persistence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from suitest_api.schemas.ingest import (
    BulkImportBody,
    IngestCase,
    IngestResult,
    IngestStep,
    ResolveProjectBody,
    RunIngestBody,
)
from suitest_api.services.ingest_service import (
    ProjectNotFoundError,
    bulk_import_cases,
    ingest_run,
    resolve_project,
)
from suitest_db.models.case import TestCase
from suitest_db.models.run import RunStep
from suitest_shared.domain.enums import CaseStatus

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_harness import ApiDb


def _case(slug: str) -> IngestCase:
    return IngestCase(
        source_ref=f"POST /api/{slug}",
        name=slug,
        slug=slug,
        title=slug.replace("_", " ").capitalize(),
        source="MCP",
        steps=[IngestStep(order=1, action="call", expected="201")],
    )


def _import_body(project_id: str = "") -> BulkImportBody:
    return BulkImportBody(
        project_id=project_id,
        project_slug="demo-app" if not project_id else "",
        project_name="Demo App" if not project_id else "",
        suite_name="Demo suite",
        mode="backend",
        cases=[_case("create_product"), _case("list_products")],
    )


@pytest.mark.asyncio
async def test_ingest_retest_matrix(api_db: ApiDb) -> None:
    ws = await api_db.seed_workspace(slug="ws-ingest", name="WS Ingest")

    async with api_db.maker() as session:
        # -- first setup: no projectId → find-or-create by slug ------------- #
        first = await bulk_import_cases(session, workspace_id=ws.id, body=_import_body())
        await session.commit()
        assert first.project_id
        assert [c.created for c in first.imported] == [True, True]
        project_id = first.project_id

        # -- retest, no change: cases reused, ZERO duplicates ---------------- #
        again = await bulk_import_cases(
            session, workspace_id=ws.id, body=_import_body(project_id=project_id)
        )
        await session.commit()
        assert [c.created for c in again.imported] == [False, False]
        rows = (await session.scalars(select(TestCase))).all()
        assert len(rows) == 2

        # -- bogus explicit projectId: 404 semantics, NEVER recreates -------- #
        with pytest.raises(ProjectNotFoundError):
            await bulk_import_cases(
                session, workspace_id=ws.id, body=_import_body(project_id="proj_nope")
            )
        await session.rollback()

        # -- binding resolve: valid / repaired / missing --------------------- #
        valid = await resolve_project(
            session, workspace_id=ws.id, body=ResolveProjectBody(projectId=project_id)
        )
        assert (valid.status, valid.matched_by) == ("valid", "id")
        repaired = await resolve_project(
            session,
            workspace_id=ws.id,
            body=ResolveProjectBody(
                project_id="proj_nope", project_slug="demo-app", project_name="Demo App"
            ),
        )
        assert (repaired.status, repaired.project_id) == ("repaired", project_id)
        missing = await resolve_project(
            session,
            workspace_id=ws.id,
            body=ResolveProjectBody(project_id="proj_nope", project_slug="other-app"),
        )
        assert missing.status == "missing" and not missing.candidates

        # -- app changed: one scenario disappears → markStale ---------------- #
        changed = BulkImportBody(
            project_id=project_id,
            suite_name="Demo suite",
            mode="backend",
            cases=[_case("create_product")],
            mark_stale=True,
        )
        stale_res = await bulk_import_cases(session, workspace_id=ws.id, body=changed)
        await session.commit()
        assert len(stale_res.stale) == 1
        stale_case = (
            await session.scalars(select(TestCase).where(TestCase.slug == "list_products"))
        ).one()
        assert stale_case.status is CaseStatus.STALE

        # -- scenario returns: STALE flips back to ACTIVE --------------------- #
        back = await bulk_import_cases(
            session, workspace_id=ws.id, body=_import_body(project_id=project_id)
        )
        await session.commit()
        assert [c.created for c in back.imported] == [False, False]  # still no dupes
        reactivated = (
            await session.scalars(select(TestCase).where(TestCase.slug == "list_products"))
        ).one()
        assert reactivated.status is CaseStatus.ACTIVE

        # -- every retest = new TestRun; failureKind lands in run_steps ------- #
        run_body = RunIngestBody(
            project_id=project_id,
            suite_name="Demo suite",
            name="retest run",
            results=[
                IngestResult(
                    slug="create_product",
                    outcome="FAILED",
                    duration_ms=42,
                    error="AssertionError: expected 201 ... got 400",
                    failure_kind="status_code_changed",
                )
            ],
        )
        run1 = await ingest_run(session, workspace_id=ws.id, body=run_body)
        await session.commit()
        run2 = await ingest_run(session, workspace_id=ws.id, body=run_body)
        await session.commit()
        assert run1.run_id != run2.run_id  # a retest never reuses a TestRun
        assert run1.project_id == project_id
        step = (await session.scalars(select(RunStep).where(RunStep.run_id == run1.run_id))).first()
        assert step is not None
        assert step.state_snapshot == {"failureKind": "status_code_changed"}
        case = (
            await session.scalars(select(TestCase).where(TestCase.slug == "create_product"))
        ).one()
        assert case.last_run_id == run2.run_id  # TestResult points at the newest run


@pytest.mark.asyncio
async def test_ingest_run_writes_log_stream(api_db: ApiDb) -> None:
    """stdout/stderr from the lifecycle land in run_step_logs (Logs tab source)."""
    from suitest_db.models.run_step_log import RunStepLog

    ws = await api_db.seed_workspace(slug="ws-logs", name="WS Logs")
    async with api_db.maker() as session:
        imported = await bulk_import_cases(session, workspace_id=ws.id, body=_import_body())
        await session.commit()
        body = RunIngestBody(
            project_id=imported.project_id,
            suite_name="Demo suite",
            name="log run",
            results=[
                IngestResult(
                    slug="create_product",
                    outcome="PASSED",
                    duration_ms=10,
                    stdout="GET /api/products 401\nassert ok",
                ),
                IngestResult(
                    slug="list_products",
                    outcome="FAILED",
                    duration_ms=20,
                    error="AssertionError: boom",
                    stderr="Traceback ...\nAssertionError: boom",
                ),
            ],
        )
        res = await ingest_run(session, workspace_id=ws.id, body=body)
        await session.commit()

        rows = (
            await session.scalars(
                select(RunStepLog)
                .where(RunStepLog.run_id == res.run_id)
                .order_by(RunStepLog.seq.asc())
            )
        ).all()
        messages = [r.message for r in rows]
        assert any("GET /api/products 401" in m for m in messages)
        assert any("AssertionError: boom" in m for m in messages)
        # per-case header lines + monotonic seq + level mapping
        assert sum(m.startswith("===") for m in messages) == 2
        assert [r.seq for r in rows] == list(range(1, len(rows) + 1))
        assert {r.level for r in rows} == {"info", "error"}
        # every row is attached to a run_step of this run
        assert all(r.run_step_id for r in rows)
