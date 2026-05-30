"""Integration repository.

M1d-19 adds the write surface (``create`` / ``update`` / ``delete`` plus the
"first-connect flip" helper :meth:`enable_bundled_mcp_for_kind`). The
``secrets_encrypted`` column is an ``EncryptedBytes`` SQLAlchemy type that
transparently AES-GCM encrypts on bind and decrypts on load — repository
callers always hand it plain ``str`` (already JSON-serialised secret blob).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select, update
from suitest_db.models.integration import Integration
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Sequence

# Map of issue-tracker / notifier IntegrationKind → bundled MCP provider name.
# The first successful create per kind in a workspace flips that bundled
# ``mcp_providers`` row's ``enabled`` from false to true (see
# ``packages/db/alembic/versions/20260530_0023_m1d_08_seed_bundled_jirac_and_github_mcp.py``).
# Other kinds (Slack, Linear, ...) have no bundled MCP and pass through unchanged.
BUNDLED_MCP_NAME_FOR_KIND: dict[IntegrationKind, str] = {
    IntegrationKind.JIRA: "jirac-mcp",
    IntegrationKind.GITHUB: "github-mcp",
}


class IntegrationCreate(BaseModel):
    workspace_id: str
    kind: IntegrationKind
    name: str
    config: dict[str, object]
    secrets_encrypted: str | None = None
    status: str = "active"


class IntegrationUpdate(BaseModel):
    name: str | None = None
    config: dict[str, object] | None = None
    secrets_encrypted: str | None = None
    status: str | None = None


class IntegrationRepo(AsyncRepository[Integration, IntegrationCreate, IntegrationUpdate]):
    model = Integration

    async def list_by_workspace(
        self, workspace_id: str, *, kind: IntegrationKind | None = None
    ) -> Sequence[Integration]:
        stmt = select(Integration).where(Integration.workspace_id == workspace_id)
        if kind is not None:
            stmt = stmt.where(Integration.kind == kind)
        stmt = stmt.order_by(Integration.created_at.desc(), Integration.id.desc())
        return (await self.session.scalars(stmt)).all()

    async def count_by_workspace_kind(self, workspace_id: str, kind: IntegrationKind) -> int:
        """Number of existing integrations of ``kind`` in ``workspace_id``.

        Used by the M1d-19 service to detect the "first connect" case for
        Jira / GitHub — when this returns 0 BEFORE inserting the new row, the
        post-insert hook flips the bundled MCP provider's ``enabled`` to true.
        """
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(Integration)
            .where(
                Integration.workspace_id == workspace_id,
                Integration.kind == kind,
            )
        )
        result: int | None = await self.session.scalar(stmt)
        return result or 0

    async def hard_delete(self, integration_id: str) -> bool:
        """Hard-delete a row by id (no soft-delete column on integrations).

        Per plan-05b M1d-19 the table has no ``deleted_at``, so disconnect is
        permanent. Returns ``True`` iff a row was removed. We deliberately
        round-trip via :meth:`get_by_id` so the SQLAlchemy ``after_flush``
        audit listener observes a ``session.deleted`` object and writes the
        ``integration.deleted`` audit row.
        """
        row = await self.get_by_id(integration_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def set_status(self, integration_id: str, status: str) -> None:
        """Update only ``status`` (used by /sync to flip to ``error`` on adapter failure)."""
        await self.session.execute(
            update(Integration).where(Integration.id == integration_id).values(status=status)
        )

    async def enable_bundled_mcp_for_kind(self, kind: IntegrationKind) -> str | None:
        """Flip the bundled MCP row's ``enabled=true`` for ``kind``.

        Returns the MCP provider name that was flipped (or ``None`` if no
        bundled mapping exists for ``kind`` — Slack, Linear, etc.). Idempotent:
        a row already ``enabled=true`` is a no-op.

        Bundled rows have ``workspace_id IS NULL`` (see
        ``packages/db/alembic/versions/20260530_0023_m1d_08_seed_bundled_jirac_and_github_mcp.py``)
        so the lookup is by name + ``workspace_id IS NULL``.
        """
        bundled_name = BUNDLED_MCP_NAME_FOR_KIND.get(kind)
        if bundled_name is None:
            return None
        await self.session.execute(
            update(McpProvider)
            .where(
                McpProvider.workspace_id.is_(None),
                McpProvider.name == bundled_name,
            )
            .values(enabled=True)
        )
        return bundled_name
