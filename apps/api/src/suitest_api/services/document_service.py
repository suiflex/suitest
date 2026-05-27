"""DocumentService — documents carry ``workspace_id`` directly."""

from __future__ import annotations

from suitest_core.capabilities import TierFlag
from suitest_db.repositories.documents import DocumentRepo
from suitest_shared.domain.enums import DocumentKind
from suitest_shared.schemas.responses import DocumentOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier


class DocumentService:
    def __init__(self, ctx: TenantContext, repo: DocumentRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @require_tier(TierFlag.ANY)
    async def list(self, *, kind: DocumentKind | None = None, limit: int = 20) -> list[DocumentOut]:
        rows, _ = await self._repo.list_by_workspace(self._ctx.workspace_id, kind=kind, limit=limit)
        return [DocumentOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, document_id: str) -> DocumentOut | None:
        row = await self._repo.get_by_id(document_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return DocumentOut.model_validate(row)
