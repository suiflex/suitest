"""DocumentRepo tests."""

from __future__ import annotations

import pytest
from factories import make_document, make_workspace
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.documents import DocumentRepo
from suitest_shared.domain.enums import DocumentKind


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = DocumentRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_document(session, workspace=ws)

    first, cursor = await repo.list_by_workspace(ws.id, limit=2)
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_by_workspace(ws.id, cursor=cursor, limit=2)
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_filter_kind(session: AsyncSession) -> None:
    repo = DocumentRepo(session)
    ws = await make_workspace(session)
    prd = await make_document(session, workspace=ws, kind=DocumentKind.PRD)
    await make_document(session, workspace=ws, kind=DocumentKind.OPENAPI)

    rows, _ = await repo.list_by_workspace(ws.id, kind=DocumentKind.PRD)
    assert {d.id for d in rows} == {prd.id}
