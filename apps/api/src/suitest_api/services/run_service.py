"""RunService + RunArtifactSignedUrlService — scoped via project -> workspace.

``RunArtifactSignedUrlService`` produces a presigned download URL for an artifact
object. The MinIO/S3 presign is stubbed behind ``_presign`` (a plain callable)
so tests can monkeypatch it without an aioboto3 dependency; M3 swaps the stub for
a real ``aioboto3`` ``generate_presigned_url`` call.
"""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_shared.domain.enums import RunStatus
from suitest_shared.schemas.responses import ArtifactOut, RunOut, SignedUrlOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

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
