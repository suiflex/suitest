"""Ingest service — persists lifecycle-published cases + completed runs.

Approach A (REST ingest): the ``suitest test`` lifecycle already executed the
tests; this service writes the results into the TCM so the web app renders them.
It never enqueues ARQ. Idempotent by ``source_ref`` (stored in
``TestCase.generated_from['source_ref']``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import TestCase, TestStep
from suitest_db.repositories.runs import (
    ArtifactRepo,
    RunCreate,
    RunRepo,
    RunStepRepo,
    RunUpdate,
)
from suitest_db.repositories.suites import SuiteCreate, SuiteRepo
from suitest_db.repositories.test_cases import TestCaseCreate, TestCaseRepo, TestCaseUpdate
from suitest_shared.domain.enums import (
    CaseSource,
    Priority,
    RunStatus,
    RunTrigger,
    StepOutcome,
    TargetKind,
    Tier,
)

from suitest_api.schemas.ingest import (
    BulkImportBody,
    BulkImportResult,
    ImportedCase,
    RunIngestBody,
    RunIngestResult,
)

_OUTCOME = {
    "PASSED": StepOutcome.PASS,
    "FAILED": StepOutcome.FAIL,
    "SKIPPED": StepOutcome.SKIP,
    "ERROR": StepOutcome.ERROR,
}


def _priority(value: str) -> Priority:
    try:
        return Priority(value)
    except ValueError:
        return Priority.P2


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def _ensure_suite(session: AsyncSession, project_id: str, name: str) -> str:
    repo = SuiteRepo(session)
    for suite in await repo.list_by_project(project_id):
        if suite.name == name:
            return suite.id
    created = await repo.create(SuiteCreate(project_id=project_id, name=name))
    return created.id


async def _find_by_name(session: AsyncSession, suite_id: str, name: str) -> TestCase | None:
    """Idempotency key = (suite, name). A ``source_ref`` is NOT unique — two cases
    can target the same endpoint (login-valid vs login-invalid), so matching on it
    would collapse distinct cases. Case names are unique within a generated plan."""
    stmt = select(TestCase).where(
        TestCase.suite_id == suite_id,
        TestCase.name == name,
        TestCase.deleted_at.is_(None),
    )
    return (await session.scalars(stmt)).first()


def _target(mode: str) -> tuple[TargetKind, str]:
    if mode == "frontend":
        return TargetKind.FE_WEB, "playwright-mcp"
    return TargetKind.BE_REST, "api-http-mcp"


async def bulk_import_cases(
    session: AsyncSession, *, workspace_id: str, body: BulkImportBody
) -> BulkImportResult:
    suite_id = await _ensure_suite(session, body.project_id, body.suite_name)
    case_repo = TestCaseRepo(session)
    target_kind, mcp_provider = _target(body.mode)
    imported: list[ImportedCase] = []

    for c in body.cases:
        gen_from: dict[str, object] = {
            "source_ref": c.source_ref,
            "category": c.category,
            "tags": list(c.tags),
        }
        existing = await _find_by_name(session, suite_id, c.name)
        if existing is not None:
            await case_repo.update(
                existing.id,
                TestCaseUpdate(
                    name=c.name,
                    description=c.description,
                    preconditions=c.preconditions,
                    automation_file_path=c.automation_file_path,
                    automation_code=c.automation_code,
                ),
            )
            await case_repo.delete_steps(existing.id)
            await case_repo.add_steps(existing.id, _steps(existing.id, c.steps, mcp_provider, target_kind))
            imported.append(
                ImportedCase(
                    source_ref=c.source_ref,
                    case_id=existing.id,
                    public_id=existing.public_id,
                    created=False,
                )
            )
            continue

        case = await case_repo.create(
            TestCaseCreate(
                suite_id=suite_id,
                name=c.name,
                source=CaseSource.IMPORT,
                priority=_priority(c.priority),
                description=c.description,
                preconditions=c.preconditions,
                generated_by=c.generated_by or "suitest-lifecycle",
                generated_from=gen_from,
                automation_file_path=c.automation_file_path,
                automation_code=c.automation_code,
            ),
            workspace_id=workspace_id,
        )
        await case_repo.add_steps(case.id, _steps(case.id, c.steps, mcp_provider, target_kind))
        imported.append(
            ImportedCase(
                source_ref=c.source_ref, case_id=case.id, public_id=case.public_id, created=True
            )
        )

    return BulkImportResult(suite_id=suite_id, imported=imported)


def _steps(case_id: str, steps: list, mcp_provider: str, target_kind: TargetKind) -> list[TestStep]:
    return [
        TestStep(
            case_id=case_id,
            order=s.order,
            action=s.action,
            expected=s.expected,
            code=s.code,
            mcp_provider=mcp_provider,
            target_kind=target_kind,
        )
        for s in steps
    ]


async def ingest_run(
    session: AsyncSession, *, workspace_id: str, body: RunIngestBody
) -> RunIngestResult:
    suite_id = await _ensure_suite(session, body.project_id, body.suite_name)
    run_repo = RunRepo(session)
    step_repo = RunStepRepo(session)
    artifact_repo = ArtifactRepo(session)
    case_repo = TestCaseRepo(session)

    run = await run_repo.create(
        RunCreate(
            project_id=body.project_id,
            name=body.name,
            trigger=RunTrigger.AGENT,
            tier_at_runtime=Tier.ZERO,
            env=body.env,
            branch=body.branch,
            commit_sha=body.commit_sha,
            status=RunStatus.RUNNING,
        ),
        workspace_id=workspace_id,
    )

    now = _now()
    passed = failed = 0
    total_ms = 0
    step_seq = 0  # global step ordering across the whole run (StepTable reads this)

    for r in body.results:
        case = await _find_by_name(session, suite_id, r.name or "")
        if case is None:
            continue
        case_outcome = _OUTCOME.get(r.outcome, StepOutcome.ERROR)
        total_ms += r.duration_ms

        # One run_step PER recorded step so the web Steps panel is granular
        # ("Step 1 … PASS, Step 2 … PASS"), not a single row per case.
        recorded = r.steps or []
        first_run_step_id: str | None = None
        if recorded:
            for s in recorded:
                step_seq += 1
                rs = await step_repo.create_step(
                    run_id=run.id,
                    case_id=case.id,
                    step_order=step_seq,
                    outcome=_OUTCOME.get(s.outcome, StepOutcome.ERROR),
                    started_at=None,
                    completed_at=now,
                    duration_ms=s.duration_ms,
                    stdout=None,
                    stderr=None,
                    error_message=r.error or None if s.outcome in ("FAILED", "ERROR") else None,
                    state_snapshot={"type": s.type, "description": s.description},
                )
                if first_run_step_id is None:
                    first_run_step_id = rs.id
        else:
            step_seq += 1
            rs = await step_repo.create_step(
                run_id=run.id,
                case_id=case.id,
                step_order=step_seq,
                outcome=case_outcome,
                started_at=None,
                completed_at=now,
                duration_ms=r.duration_ms,
                stdout=r.stdout or None,
                stderr=r.stderr or None,
                error_message=r.error or None,
                state_snapshot=None,
            )
            first_run_step_id = rs.id

        # Attach the case's video/screenshot to its first run step.
        for a in r.artifacts:
            if first_run_step_id is not None:
                await artifact_repo.create_artifact(
                    run_step_id=first_run_step_id,
                    kind=a.kind,
                    url=a.url,
                    size_bytes=a.size_bytes,
                    mime_type=a.mime_type,
                    metadata=None,
                )

        await case_repo.update(
            case.id,
            TestCaseUpdate(
                last_run_id=run.id,
                last_run_result=r.outcome,
                last_run_at=now,
                last_failure_reason=r.error or None,
                last_duration_ms=r.duration_ms,
            ),
        )
        if case_outcome is StepOutcome.PASS:
            passed += 1
        else:
            failed += 1

    final = RunStatus.PASS if failed == 0 else RunStatus.FAIL
    await run_repo.update(
        run.id,
        RunUpdate(
            status=final,
            completed_at=now,
            duration_ms=total_ms,
            total_steps=passed + failed,
            passed_steps=passed,
            failed_steps=failed,
        ),
    )
    return RunIngestResult(
        run_id=run.id, status=final.value, total=passed + failed, passed=passed, failed=failed
    )
