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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Suite
from suitest_db.models.run import Run as RunRow
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import RunStatus, RunTrigger, Tier
from suitest_shared.schemas.responses import ArtifactOut, RunOut, SignedUrlOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

# Bundled MCP provider names always accepted by ``create_run`` even when the
# workspace has not registered them in ``mcp_providers``. Kept here (vs.
# importing from suitest_mcp) so the api service doesn't pull the runner-only
# MCP package onto its import graph.
_BUNDLED_MCP_PROVIDERS: frozenset[str] = frozenset(
    {"api-http-mcp", "playwright-mcp", "postgres-mcp"}
)

# Default presigned-URL lifetime in seconds.
DEFAULT_SIGNED_URL_TTL = 900


class RunService:
    def __init__(self, ctx: TenantContext, repo: RunRepo, project_repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    @require_tier(TierFlag.ANY)
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

    @require_tier(TierFlag.ANY)
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

    @property
    def _session(self) -> AsyncSession:
        """Session shared with the repos — exposed so ``create_run`` can flush."""
        return self._repo.session

    @require_tier(TierFlag.ANY)
    async def get(self, run_id: str) -> RunRow | None:
        """Return the raw :class:`Run` row when in scope, else ``None``.

        Used by the cancel / rerun endpoints which read the metadata blob
        (``arq_job_id``) — a ``RunOut`` projection would drop those columns.
        """
        run = await self._repo.get_by_id(run_id)
        if run is None or not await self._project_in_scope(run.project_id):
            return None
        return run

    @require_tier(TierFlag.ANY)
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

    @require_tier(TierFlag.ANY)
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
        user_id: str,
        mcp_routing_override: dict[str, str] | None,
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
        5. Resolve the workspace tier from ``WorkspaceCapability`` (defaults
           to :attr:`Tier.ZERO`).

        On success: inserts a :class:`Run` row with status ``QUEUED``, the
        resolved tier, and a JSON metadata blob carrying the selection +
        routing override (so the orchestrator can rehydrate them later); then
        appends a ``run.create`` audit row. The session is NOT committed
        here — the router commits after attaching the ARQ job id so the run
        row + job id land atomically.
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

        for item in selection:
            case_id_raw = item.get("case_id")
            if not isinstance(case_id_raw, str):
                raise ValueError("selection item missing caseId")
            case = await self._session.get(TestCase, case_id_raw)
            if case is None:
                raise ValueError(f"case {case_id_raw} not in project")
            suite = await self._session.get(Suite, case.suite_id)
            if suite is None or suite.project_id != project_id:
                raise ValueError(f"case {case_id_raw} not in project")
            # Load steps via an explicit query — ``case.steps`` is a lazy
            # relationship which triggers a sync IO callback under asyncpg
            # and explodes with ``MissingGreenlet``.
            steps = (
                await self._session.scalars(select(TestStep).where(TestStep.case_id == case.id))
            ).all()
            for step in steps:
                if step.mcp_provider and step.mcp_provider not in registered:
                    raise ValueError(
                        f"step {step.id} references unregistered MCP {step.mcp_provider}"
                    )

        capability = await WorkspaceCapabilityRepo(self._session).get(project.workspace_id)
        tier = Tier(capability.tier) if capability is not None else Tier.ZERO

        # ``metadata_json`` payload is JSON-serialisable: every selection dict
        # came from Pydantic ``model_dump`` upstream, and routing override is
        # ``dict[str, str] | None``. Typed against ``dict[str, Any]`` so the
        # JSONB column tolerates the mixed shape without us inventing a typed
        # alias for ad-hoc metadata.
        metadata: dict[str, Any] = {
            "selection": selection,
            "mcp_routing_override": mcp_routing_override,
        }
        run = RunRow(
            project_id=project_id,
            name=name,
            branch=branch,
            commit_sha=commit_sha,
            env=env,
            trigger=trigger,
            triggered_by=user_id,
            status=RunStatus.QUEUED,
            tier_at_runtime=tier,
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

    @require_tier(TierFlag.ANY)
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

    @require_tier(TierFlag.ANY)
    async def clone_for_rerun(self, src: RunRow, *, user_id: str) -> RunRow:
        """Insert a fresh QUEUED run row cloning ``src``'s selection.

        Selection + routing override are copied verbatim from the source run's
        metadata — same fan-out, same MCP routing — so a rerun is bit-for-bit
        equivalent to the original at the orchestrator boundary. Tier is
        re-resolved from the workspace capability rather than reused, because
        a workspace's tier may have changed between the two runs and we want
        the rerun to reflect the *current* tier.
        """
        project = await self._project_repo.get_by_id(src.project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            raise ValueError("project not found")
        capability = await WorkspaceCapabilityRepo(self._session).get(project.workspace_id)
        tier = Tier(capability.tier) if capability is not None else Tier.ZERO

        src_metadata: dict[str, Any] = dict(src.metadata_json) if src.metadata_json else {}
        # Strip per-run bookkeeping that does not belong on the new run.
        src_metadata.pop("arq_job_id", None)
        metadata: dict[str, Any] = {
            "selection": src_metadata.get("selection", []),
            "mcp_routing_override": src_metadata.get("mcp_routing_override"),
            "rerun_of": src.id,
        }

        run = RunRow(
            project_id=src.project_id,
            name=src.name,
            branch=src.branch,
            commit_sha=src.commit_sha,
            env=src.env,
            trigger=RunTrigger.MANUAL,
            triggered_by=user_id,
            status=RunStatus.QUEUED,
            tier_at_runtime=tier,
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
            metadata={"rerun_of": src.id},
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
        if run is None:
            return False
        project = await self._project_repo.get_by_id(run.project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    @require_tier(TierFlag.ANY)
    async def list_artifacts(self, run_id: str) -> list[ArtifactOut] | None:
        if not await self._run_in_scope(run_id):
            return None
        rows = await self._repo.get_artifacts(run_id)
        return [ArtifactOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
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
