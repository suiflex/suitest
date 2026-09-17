"""RunService + RunArtifactSignedUrlService — scoped via project -> workspace.

``RunArtifactSignedUrlService`` produces a presigned download URL for an artifact
object. The MinIO/S3 presign is stubbed behind ``_presign`` (a plain callable)
so tests can monkeypatch it without an aioboto3 dependency; M3 swaps the stub for
a real ``aioboto3`` ``generate_presigned_url`` call.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from suitest_db.audit import write_audit
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Suite
from suitest_db.models.run import Run as RunRow
from suitest_db.models.run import RunStep
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.domain.enums import RunStatus, RunTrigger, StepOutcome
from suitest_shared.schemas.responses import ArtifactOut, RunOut, SignedUrlOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_llm_ready
from suitest_api.services.project_scope import project_belongs_to_workspace
from suitest_api.services.test_case_validator import BUNDLED_MCP_PROVIDERS

# Bundled MCP provider names always accepted by ``create_run`` even when the
# workspace has not registered them in ``mcp_providers``. Kept here (vs.
# importing from suitest_mcp) so the api service doesn't pull the runner-only
# MCP package onto its import graph.
# Single source of truth — see the note on ``BUNDLED_MCP_PROVIDERS``.
_BUNDLED_MCP_PROVIDERS = BUNDLED_MCP_PROVIDERS

# Default presigned-URL lifetime in seconds.
DEFAULT_SIGNED_URL_TTL = 900


class RunService:
    def __init__(self, ctx: TenantContext, repo: RunRepo, project_repo: ProjectRepo) -> None:
        self._ctx, self._repo = ctx, repo
        self._project_repo, self._session = project_repo, repo.session

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def list(
        self,
        project_id: str,
        *,
        status: RunStatus | None = None,
        branch: str | None = None,
        env: str | None = None,
        limit: int = 20,
    ) -> list[RunOut] | None:
        if not await self._project_in_scope(project_id):
            return None
        rows, _ = await self._repo.list_by_project(
            project_id, status=status, branch=branch, env=env, limit=limit
        )
        return [RunOut.model_validate(r) for r in rows]

    async def get_by_id(self, run_id: str) -> RunOut | None:
        pair = await self._repo.get_with_summary(run_id)
        if pair is None:
            return None
        run, summary = pair
        if not await self._project_in_scope(run.project_id):
            return None
        # RunOut consumes the recomputed counters from the summary dataclass
        # rather than the (now untouched) ORM denorm columns so in-flight runs
        # still reflect the live step outcomes.
        return RunOut.model_validate(run).model_copy(
            update={
                "total_steps": summary.total_steps,
                "passed_steps": summary.passed_steps,
                "failed_steps": summary.failed_steps,
            },
        )

    # -- M1c Task 15 mutations ---------------------------------------------

    async def get(self, run_id: str) -> RunRow | None:
        """Return the raw :class:`Run` row when in scope, else ``None``.

        Used by the cancel / rerun endpoints which read the metadata blob
        (``arq_job_id``) — a ``RunOut`` projection would drop those columns.
        """
        run = await self._repo.get_by_id(run_id)
        if run is None or not await self._project_in_scope(run.project_id):
            return None
        return run

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> RunRow | None:
        """Thin pass-through to :meth:`RunRepo.update_status` keeping scope safe."""
        run = await self._repo.get_by_id(run_id)
        if run is None or not await self._project_in_scope(run.project_id):
            return None
        return await self._repo.update_status(
            run_id,
            status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )

    @require_llm_ready
    async def create_run(
        self,
        *,
        project_id: str,
        name: str,
        selection: Sequence[dict[str, object]],
        branch: str | None,
        commit_sha: str | None,
        env: str,
        trigger: RunTrigger,
        user_id: str | None,
        mcp_routing_override: dict[str, str] | None,
        triggered_by: str | None = None,
        playwright_config: dict[str, Any] | None = None,
    ) -> RunRow:
        """Validate, insert one ``runs`` row, and append an audit log.

        Validation in order:

        1. Project must exist AND belong to the request's workspace (cross-ws
           project ids raise ``ValueError("project not found")`` which the
           router maps to a 400 — this is intentional: cross-workspace creates
           must look identical to "doesn't exist" to avoid an enumeration
           oracle).
        2. ``selection`` non-empty.
        3. Every ``case_id`` resolves to a TestCase whose suite lives under
           ``project_id``.
        4. Every step's ``mcp_provider`` is either a bundled builtin OR a
           workspace-registered ``mcp_providers`` row.
        On success: inserts a :class:`Run` row with status ``QUEUED``, the
        JSON metadata blob carrying the selection +
        routing override (so the orchestrator can rehydrate them later); then
        appends a ``run.create`` audit row. The session is NOT committed
        here — the router commits after attaching the ARQ job id so the run
        row + job id land atomically.

        ``triggered_by`` overrides the per-row ``triggered_by`` string when set
        (e.g. webhook receivers passing ``"webhook:gitlab"``); otherwise the
        UUID ``user_id`` value is used. ``user_id`` may be ``None`` for
        attributionless webhook-driven runs — the audit row's ``user_id`` is
        omitted in that case (the audit table allows NULL user_id, matching
        background-job semantics).
        """
        project = await self._project_repo.get_by_id(project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            raise ValueError("project not found")
        if not selection:
            raise ValueError("selection cannot be empty")

        registered = {
            p.name
            for p in await McpProviderRepo(self._session).list_by_workspace(project.workspace_id)
        }
        registered |= set(_BUNDLED_MCP_PROVIDERS)

        case_ids: list[str] = []
        for item in selection:
            case_id_raw = item.get("case_id")
            if not isinstance(case_id_raw, str):
                raise ValueError("selection item missing caseId")
            case_ids.append(case_id_raw)

        case_rows = await self._session.execute(
            select(TestCase.id, Suite.project_id)
            .join(Suite, Suite.id == TestCase.suite_id)
            .where(TestCase.id.in_(case_ids))
        )
        case_projects: dict[str, str] = {
            case_id: row_project_id for case_id, row_project_id in case_rows
        }
        for case_id in case_ids:
            if case_projects.get(case_id) != project_id:
                raise ValueError(f"case {case_id} not in project")

        step_rows = await self._session.execute(
            select(TestStep.id, TestStep.mcp_provider)
            .where(TestStep.case_id.in_(case_ids))
            .order_by(TestStep.case_id, TestStep.order)
        )
        for step_id, provider_name in step_rows:
            if provider_name and provider_name not in registered:
                raise ValueError(f"step {step_id} references unregistered MCP {provider_name}")

        # Snapshot planned cases at run creation so historical runs are immutable
        tc_info_rows = (
            await self._session.execute(
                select(
                    TestCase.id,
                    TestCase.public_id,
                    TestCase.title,
                    func.count(TestStep.id),
                )
                .outerjoin(TestStep, TestStep.case_id == TestCase.id)
                .where(TestCase.id.in_(case_ids))
                .group_by(TestCase.id, TestCase.public_id, TestCase.title)
            )
        ).all()
        tc_info_map = {row[0]: (row[1], row[2], int(row[3] or 0)) for row in tc_info_rows}
        planned_cases_snapshot: list[dict[str, Any]] = []
        for item in selection:
            cid = item.get("case_id")
            if isinstance(cid, str) and cid in tc_info_map:
                pid, title, count = tc_info_map[cid]
                sel_steps = item.get("selected_step_ids")
                total_s = len(sel_steps) if isinstance(sel_steps, list) else count
                planned_cases_snapshot.append(
                    {
                        "case_id": cid,
                        "case_public_id": pid,
                        "case_title": title,
                        "total_steps": total_s,
                    }
                )

        # ``metadata_json`` payload is JSON-serialisable: every selection dict
        # came from Pydantic ``model_dump`` upstream, and routing override is
        # ``dict[str, str] | None``. Typed against ``dict[str, Any]`` so the
        # JSONB column tolerates the mixed shape without us inventing a typed
        # alias for ad-hoc metadata.
        metadata: dict[str, Any] = {
            "selection": selection,
            "planned_cases": planned_cases_snapshot,
            "mcp_routing_override": mcp_routing_override,
            **({"playwright_config": playwright_config} if playwright_config is not None else {}),
        }
        run = RunRow(
            project_id=project_id,
            name=name,
            branch=branch,
            commit_sha=commit_sha,
            env=env,
            trigger=trigger,
            triggered_by=triggered_by if triggered_by is not None else user_id,
            status=RunStatus.QUEUED,
            metadata_json=metadata,
        )
        # ``before_insert`` listener fills ``public_id`` once it sees the
        # transient workspace-id attr below — see suitest_db.public_id.
        set_workspace_id(run, project.workspace_id)
        self._session.add(run)
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=project.workspace_id,
            user_id=user_id,
            action="run.create",
            resource_type="run",
            resource_id=run.id,
            metadata={"trigger": trigger.value, "selection_size": len(selection)},
        )
        return run

    async def create_run_for_suite(
        self,
        *,
        suite_id: str,
        name: str | None,
        branch: str | None,
        commit_sha: str | None,
        env: str,
        trigger: RunTrigger,
        user_id: str | None,
        mcp_routing_override: dict[str, str] | None,
        playwright_config: dict[str, Any] | None = None,
    ) -> RunRow:
        """Run every active case in a suite as ONE bundle run (QA suite-run entry).

        Resolves the suite within scope, derives the selection from its active
        cases in suite order (``SuiteRepo.active_case_ids_in_order``), then delegates
        to :meth:`create_run` so all the existing validation (MCP provider check,
        LLM readiness gate and audit) applies unchanged. ``name`` defaults to the suite
        name. Raises ``ValueError("suite not found")`` for a missing/cross-workspace
        suite and ``ValueError("suite has no active cases")`` for an empty suite —
        the router maps both to 400/404.
        """
        suite_repo = SuiteRepo(self._session)
        suite = await suite_repo.get_active_by_id(suite_id)
        if suite is None or not await self._project_in_scope(suite.project_id):
            raise ValueError("suite not found")
        case_ids = await suite_repo.active_case_ids_in_order(suite_id)
        if not case_ids:
            raise ValueError("suite has no active cases")
        selection: list[dict[str, object]] = [{"case_id": cid} for cid in case_ids]
        return await self.create_run(
            project_id=suite.project_id,
            name=name or suite.name,
            selection=selection,
            branch=branch,
            commit_sha=commit_sha,
            env=env,
            trigger=trigger,
            user_id=user_id,
            mcp_routing_override=mcp_routing_override,
            playwright_config=playwright_config,
        )

    async def attach_arq_job_id(self, run_id: str, job_id: str) -> None:
        """Stamp the ARQ job id onto ``runs.metadata.arq_job_id``.

        Called by the router right after ``enqueue_job`` so cancel can later
        reach into ARQ to abort the running job. Updates the JSONB column in
        place — the SQLAlchemy session picks the change up on the next flush.
        """
        run = await self._repo.get_by_id(run_id)
        if run is None:
            return
        existing = dict(run.metadata_json) if run.metadata_json else {}
        existing["arq_job_id"] = job_id
        run.metadata_json = existing
        await self._session.flush()

    @require_llm_ready
    async def clone_for_rerun(
        self,
        src: RunRow,
        *,
        user_id: str,
        failed_only: bool = False,
        case_ids: Sequence[str] | None = None,
        playwright_config: dict[str, Any] | None = None,
    ) -> RunRow:
        """Insert a fresh QUEUED run row cloning ``src``'s selection.

        When ``case_ids`` is provided, the new run only executes those specific
        cases (in order). When ``failed_only`` is True, it filters to cases that
        had FAIL or ERROR step outcomes in ``src``. ``selected_step_ids`` is
        reset to ``None`` so any edits made in the test case editor run fresh.
        Workspace LLM readiness is checked before cloning.
        """
        project = await self._project_repo.get_by_id(src.project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            raise ValueError("project not found")
        src_metadata: dict[str, Any] = dict(src.metadata_json) if src.metadata_json else {}
        # Strip per-run bookkeeping that does not belong on the new run.
        src_metadata.pop("arq_job_id", None)
        original_selection: list[dict[str, Any]] = (
            [dict(item) for item in src_metadata.get("selection", []) if isinstance(item, dict)]
            if isinstance(src_metadata.get("selection"), list)
            else []
        )

        target_case_ids: list[str] | None = None
        rerun_mode = "full"

        if case_ids is not None:
            target_case_ids = [cid for cid in case_ids if isinstance(cid, str)]
            rerun_mode = "selective"
        elif failed_only:
            stmt = (
                select(RunStep.case_id)
                .where(
                    RunStep.run_id == src.id,
                    RunStep.outcome.in_([StepOutcome.FAIL, StepOutcome.ERROR]),
                )
                .distinct()
            )
            failed_set = set((await self._session.scalars(stmt)).all())
            if not failed_set:
                raise ValueError("No failed test cases to re-run.")

            if original_selection:
                target_case_ids = [
                    item["case_id"]
                    for item in original_selection
                    if item.get("case_id") in failed_set
                ]
            else:
                target_case_ids = list(failed_set)
            rerun_mode = "failed_only"

        new_selection: list[dict[str, Any]]
        if target_case_ids is not None:
            # Scope to project to prevent cross-project/cross-workspace injection
            case_project_stmt = (
                select(TestCase.id, TestCase.deleted_at)
                .join(Suite, Suite.id == TestCase.suite_id)
                .where(
                    TestCase.id.in_(target_case_ids),
                    Suite.project_id == src.project_id,
                )
            )
            case_rows = (await self._session.execute(case_project_stmt)).all()
            case_project_map = {row[0]: row[1] for row in case_rows}
            for cid in target_case_ids:
                if cid not in case_project_map:
                    raise ValueError(f"case {cid} not in project")

            # Filter out soft-deleted cases so rerun doesn't fail on deleted cases
            valid_target_ids = [cid for cid in target_case_ids if case_project_map[cid] is None]
            if not valid_target_ids:
                raise ValueError("No active test cases to re-run (cases may have been deleted).")

            # Reset selected_step_ids to None so edited/fixed steps execute fresh
            new_selection = [
                {"case_id": cid, "selected_step_ids": None} for cid in valid_target_ids
            ]

            if len(valid_target_ids) == 1:
                tc = await self._session.scalar(
                    select(TestCase).where(TestCase.id == valid_target_ids[0])
                )
                raw_title = (
                    (tc.title or tc.name or tc.public_id or "1 selected case")
                    if tc is not None
                    else "1 selected case"
                )
                clean_title = raw_title.removeprefix("Ad-hoc: ").strip()
                run_name = f"Ad-hoc: {clean_title}"[:250]
            else:
                run_name = f"Ad-hoc: {len(valid_target_ids)} selected cases"[:250]
        else:
            # Full rerun: reset selected_step_ids to None so edited steps execute fresh
            new_selection = [{**item, "selected_step_ids": None} for item in original_selection]
            run_name = src.name[:250]

        # Snapshot planned cases at rerun creation
        rerun_case_ids = [
            item["case_id"]
            for item in new_selection
            if isinstance(item, dict) and isinstance(item.get("case_id"), str)
        ]
        rerun_tc_rows = (
            await self._session.execute(
                select(
                    TestCase.id,
                    TestCase.public_id,
                    TestCase.title,
                    func.count(TestStep.id),
                )
                .outerjoin(TestStep, TestStep.case_id == TestCase.id)
                .where(TestCase.id.in_(rerun_case_ids))
                .group_by(TestCase.id, TestCase.public_id, TestCase.title)
            )
        ).all()
        rerun_tc_map = {row[0]: (row[1], row[2], int(row[3] or 0)) for row in rerun_tc_rows}
        rerun_planned_snapshot: list[dict[str, Any]] = []
        for item in new_selection:
            case_id_val = item.get("case_id")
            if isinstance(case_id_val, str) and case_id_val in rerun_tc_map:
                pid, title, count = rerun_tc_map[case_id_val]
                sel_steps = item.get("selected_step_ids")
                total_s = len(sel_steps) if isinstance(sel_steps, list) else count
                rerun_planned_snapshot.append(
                    {
                        "case_id": case_id_val,
                        "case_public_id": pid,
                        "case_title": title,
                        "total_steps": total_s,
                    }
                )

        effective_pw_config = (
            playwright_config
            if playwright_config is not None
            else src_metadata.get("playwright_config")
        )

        metadata: dict[str, Any] = {
            "selection": new_selection,
            "planned_cases": rerun_planned_snapshot,
            "mcp_routing_override": src_metadata.get("mcp_routing_override"),
            "rerun_of": src.id,
            "rerun_mode": rerun_mode,
            **(
                {"playwright_config": effective_pw_config}
                if effective_pw_config is not None
                else {}
            ),
        }

        run = RunRow(
            project_id=src.project_id,
            name=run_name,
            branch=src.branch,
            commit_sha=src.commit_sha,
            env=src.env,
            trigger=RunTrigger.MANUAL,
            triggered_by=user_id,
            status=RunStatus.QUEUED,
            metadata_json=metadata,
        )
        set_workspace_id(run, project.workspace_id)
        self._session.add(run)
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=project.workspace_id,
            user_id=user_id,
            action="run.rerun",
            resource_type="run",
            resource_id=run.id,
            metadata={"rerun_of": src.id, "rerun_mode": rerun_mode},
        )
        return run


def _presign(object_url: str, *, expires_in: int) -> str:
    """Stub presigner. Replaced by aioboto3 ``generate_presigned_url`` in M3.

    Tests monkeypatch this module-level function. The M1a stub just appends a
    query string so the shape is realistic.
    """
    return f"{object_url}?X-Amz-Expires={expires_in}&X-Amz-Signature=stub"


class RunArtifactSignedUrlService:
    def __init__(self, ctx: TenantContext, repo: RunRepo, project_repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    async def _run_in_scope(self, run_id: str) -> bool:
        run = await self._repo.get_by_id(run_id)
        return run is not None and await project_belongs_to_workspace(
            self._project_repo, run.project_id, self._ctx.workspace_id
        )

    async def list_artifacts(self, run_id: str) -> list[ArtifactOut] | None:
        if not await self._run_in_scope(run_id):
            return None
        rows = await self._repo.get_artifacts(run_id)
        return [ArtifactOut.model_validate(r) for r in rows]

    async def signed_url(
        self, run_id: str, artifact_id: str, *, expires_in: int = DEFAULT_SIGNED_URL_TTL
    ) -> SignedUrlOut | None:
        if not await self._run_in_scope(run_id):
            return None
        artifacts = await self._repo.get_artifacts(run_id)
        artifact = next((a for a in artifacts if a.id == artifact_id), None)
        if artifact is None:
            return None
        url = _presign(artifact.url, expires_in=expires_in)
        return SignedUrlOut(artifact_id=artifact_id, url=url, expires_in=expires_in)
