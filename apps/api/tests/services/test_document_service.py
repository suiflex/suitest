"""DocumentService tests — direct workspace_id scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.document_service import DocumentService
from suitest_db.models.document import Document
from suitest_shared.domain.enums import DocumentKind, Role

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.QA
    )


def _doc(ws: str) -> Document:
    d = Document(
        id="doc_1",
        workspace_id=ws,
        kind=DocumentKind.PRD,
        source="s3://x",
        title="PRD",
        content_hash="abc",
    )
    d.created_at = _NOW
    d.updated_at = _NOW
    d.indexed_at = None
    return d


@pytest.mark.asyncio
async def test_document_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_workspace.return_value = ([_doc("ws_1")], None)
    svc = DocumentService(_ctx("ws_1"), repo)

    out = await svc.list()

    assert repo.list_by_workspace.await_args.args[0] == "ws_1"
    assert [d.id for d in out] == ["doc_1"]


@pytest.mark.asyncio
async def test_document_get_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    repo.get_by_id.return_value = _doc("ws_OTHER")
    svc = DocumentService(_ctx("ws_1"), repo)

    assert await svc.get_by_id("doc_1") is None
