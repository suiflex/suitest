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
from suitest_db.repositories.run_step_logs import RunStepLogRepo
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
    CaseStatus,
    Priority,
    RunStatus,
    RunTrigger,
    StepOutcome,
    TargetKind,
    Tier,
)
from suitest_shared.text import derive_slug, derive_title

from suitest_api.schemas.ingest import (
    BulkImportBody,
    BulkImportResult,
    ImportedCase,
    IngestStep,
    ProjectCandidate,
    ResolveProjectBody,
    ResolveProjectResult,
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


def _source(value: str | None) -> CaseSource:
    """Map a publisher-declared source onto the enum. Lifecycle/MCP publishers
    send "MCP"; generic imports omit it. Unknown values degrade to IMPORT."""
    if value is None:
        return CaseSource.IMPORT
    try:
        return CaseSource(value)
    except ValueError:
        return CaseSource.IMPORT


def _now() -> datetime:
    return datetime.now(tz=UTC)


class ProjectNotFoundError(Exception):
    """Explicit projectId does not exist in the caller's workspace.

    The router maps this to 404 (never 403) so a caller cannot probe which
    project ids exist in other workspaces.
    """

    def __init__(self, project_id: str) -> None:
        super().__init__(f"project not found in workspace: {project_id}")
        self.project_id = project_id


async def _ensure_project(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_id: str,
    project_slug: str,
    project_name: str,
) -> str:
    """Resolve the target project: explicit id wins; else find-or-create by slug.

    Publisher-facing (API-key) path — mirrors ``_ensure_suite``'s idempotent
    find-or-create so a blackbox/lifecycle run can publish into a fresh
    workspace without a human pre-creating the project. Audited on create.
    """
    from suitest_db.audit import write_audit
    from suitest_db.models.project import Project

    if project_id:
        stmt = select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        if (await session.scalars(stmt)).first() is None:
            raise ProjectNotFoundError(project_id)
        return project_id
    if not project_slug:
        raise ValueError("either projectId or projectSlug is required")
    stmt = select(Project).where(
        Project.workspace_id == workspace_id,
        Project.slug == project_slug,
        Project.deleted_at.is_(None),
    )
    existing = (await session.scalars(stmt)).first()
    if existing is not None:
        return existing.id
    row = Project(
        workspace_id=workspace_id,
        slug=project_slug[:64],
        name=(project_name or project_slug)[:120],
    )
    session.add(row)
    await session.flush()
    await write_audit(
        session,
        workspace_id=workspace_id,
        user_id=None,
        action="project.created",
        resource_type="project",
        resource_id=row.id,
        metadata={"slug": row.slug, "via": "ingest"},
    )
    return row.id


async def resolve_project(
    session: AsyncSession, *, workspace_id: str, body: ResolveProjectBody
) -> ResolveProjectResult:
    """Publisher-facing binding check + repair (never creates anything).

    - explicit id exists in the workspace → ``valid``
    - id missing/stale but exactly one active project matches the slug or the
      (case-insensitive) name → ``repaired`` with the surviving id
    - anything else → ``missing`` (ambiguous matches are listed as candidates;
      the client must fail loudly or recreate only on an explicit flag)
    """
    from sqlalchemy import func
    from suitest_db.models.project import Project

    if body.project_id:
        stmt = select(Project).where(
            Project.id == body.project_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
        if (await session.scalars(stmt)).first() is not None:
            return ResolveProjectResult(status="valid", project_id=body.project_id, matched_by="id")

    for matched_by, cond in (
        ("slug", Project.slug == body.project_slug if body.project_slug else None),
        (
            "name",
            func.lower(Project.name) == body.project_name.lower() if body.project_name else None,
        ),
    ):
        if cond is None:
            continue
        stmt = select(Project).where(
            Project.workspace_id == workspace_id, Project.deleted_at.is_(None), cond
        )
        rows = list((await session.scalars(stmt)).all())
        if len(rows) == 1:
            return ResolveProjectResult(
                status="repaired", project_id=rows[0].id, matched_by=matched_by
            )
        if rows:
            return ResolveProjectResult(
                status="missing",
                candidates=[ProjectCandidate(id=r.id, slug=r.slug, name=r.name) for r in rows],
            )
    return ResolveProjectResult(status="missing")


async def _ensure_suite(session: AsyncSession, project_id: str, name: str) -> str:
    repo = SuiteRepo(session)
    for suite in await repo.list_by_project(project_id):
        if suite.name == name:
            return suite.id
    created = await repo.create(SuiteCreate(project_id=project_id, name=name))
    return created.id


async def _find_case(
    session: AsyncSession, suite_id: str, *, slug: str | None, name: str
) -> TestCase | None:
    """Idempotency key = (suite, slug) with a (suite, name) fallback.

    A ``source_ref`` is NOT unique — two cases can target the same endpoint
    (login-valid vs login-invalid), so matching on it would collapse distinct
    cases. Slugs/names are unique within a generated plan. The name fallback
    covers rows created before the title/slug split (migration 0044) and
    publishers that predate the ``slug`` field.
    """
    if slug:
        stmt = select(TestCase).where(
            TestCase.suite_id == suite_id,
            TestCase.slug == slug,
            TestCase.deleted_at.is_(None),
        )
        found = (await session.scalars(stmt)).first()
        if found is not None:
            return found
    if not name:
        return None
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
    project_id = await _ensure_project(
        session,
        workspace_id=workspace_id,
        project_id=body.project_id,
        project_slug=body.project_slug,
        project_name=body.project_name,
    )
    suite_id = await _ensure_suite(session, project_id, body.suite_name)
    case_repo = TestCaseRepo(session)
    target_kind, mcp_provider = _target(body.mode)
    imported: list[ImportedCase] = []

    for c in body.cases:
        gen_from: dict[str, object] = {
            "source_ref": c.source_ref,
            "category": c.category,
            "tags": list(c.tags),
        }
        # Server-authoritative title/slug: prefer explicit payload fields, fall
        # back to deriving from the legacy ``name`` (docs/DATA_MODEL.md §3.4).
        slug = c.slug or derive_slug(c.name)
        title = c.title or derive_title(c.name)
        existing = await _find_case(session, suite_id, slug=slug, name=c.name)
        if existing is not None:
            await case_repo.update(
                existing.id,
                TestCaseUpdate(
                    name=c.name,
                    title=title,
                    slug=slug,
                    description=c.description,
                    preconditions=c.preconditions,
                    source=_source(c.source),
                    automation_file_path=c.automation_file_path,
                    automation_code=c.automation_code,
                    # A re-generated case is alive again; only STALE flips back —
                    # human decisions (DEPRECATED/ARCHIVED) are never overridden.
                    status=(CaseStatus.ACTIVE if existing.status is CaseStatus.STALE else None),
                ),
            )
            await case_repo.delete_steps(existing.id)
            await case_repo.add_steps(
                existing.id, _steps(existing.id, c.steps, mcp_provider, target_kind)
            )
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
                title=title,
                slug=slug,
                source=_source(c.source),
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

    stale: list[str] = []
    if body.mark_stale:
        imported_ids = {i.case_id for i in imported}
        stmt = select(TestCase).where(
            TestCase.suite_id == suite_id,
            TestCase.deleted_at.is_(None),
            TestCase.source == CaseSource.MCP,
            TestCase.status.in_((CaseStatus.ACTIVE, CaseStatus.DRAFT)),
            TestCase.id.notin_(imported_ids),
        )
        for missing in (await session.scalars(stmt)).all():
            await case_repo.update(missing.id, TestCaseUpdate(status=CaseStatus.STALE))
            stale.append(missing.public_id)

    return BulkImportResult(
        suite_id=suite_id, project_id=project_id, imported=imported, stale=stale
    )


def _steps(
    case_id: str, steps: list[IngestStep], mcp_provider: str, target_kind: TargetKind
) -> list[TestStep]:
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
    project_id = await _ensure_project(
        session,
        workspace_id=workspace_id,
        project_id=body.project_id,
        project_slug=body.project_slug,
        project_name=body.project_name,
    )
    suite_id = await _ensure_suite(session, project_id, body.suite_name)
    run_repo = RunRepo(session)
    step_repo = RunStepRepo(session)
    artifact_repo = ArtifactRepo(session)
    case_repo = TestCaseRepo(session)
    log_repo = RunStepLogRepo(session)
    log_seq = 0  # single-shot ingest — a local counter is monotonic enough

    run = await run_repo.create(
        RunCreate(
            project_id=project_id,
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
        case = await _find_case(session, suite_id, slug=r.slug or None, name=r.name or "")
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
                    state_snapshot={
                        "type": s.type,
                        "description": s.description,
                        **(
                            {"failureKind": r.failure_kind}
                            if r.failure_kind and s.outcome in ("FAILED", "ERROR")
                            else {}
                        ),
                    },
                )
                # Per-step screenshot → SCREENSHOT artifact on THIS run_step, so
                # the web can show "Preview: Step N" when the step row is clicked.
                if s.screenshot:
                    await artifact_repo.create_artifact(
                        run_step_id=rs.id,
                        kind="SCREENSHOT",
                        url=s.screenshot,
                        size_bytes=0,
                        mime_type="image/png",
                        metadata=None,
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
                state_snapshot={"failureKind": r.failure_kind} if r.failure_kind else None,
            )
            first_run_step_id = rs.id

        # Persist captured output as the run's log stream (feeds the Logs tab —
        # GET /runs/:id/logs reads run_step_logs, which only the ARQ orchestrator
        # wrote before; ingested runs were always "No logs recorded").
        log_lines: list[tuple[str, str]] = [
            *[("info", line) for line in (r.stdout or "").splitlines() if line.strip()],
            *[("error", line) for line in (r.stderr or "").splitlines() if line.strip()],
        ]
        if r.error and not r.stderr:
            log_lines.extend(("error", line) for line in r.error.splitlines() if line.strip())
        if log_lines:
            log_seq += 1
            await log_repo.append(
                run_id=run.id,
                run_step_id=first_run_step_id,
                level="info",
                message=f"=== {case.public_id} {r.slug or r.name} ({r.outcome}) ===",
                seq=log_seq,
            )
            for level, message in log_lines:
                log_seq += 1
                await log_repo.append(
                    run_id=run.id,
                    run_step_id=first_run_step_id,
                    level=level,
                    message=message,
                    seq=log_seq,
                )

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
        run_id=run.id,
        project_id=project_id,
        status=final.value,
        total=passed + failed,
        passed=passed,
        failed=failed,
    )
