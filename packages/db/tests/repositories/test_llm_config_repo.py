"""LLMConfigRepo tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from factories import make_llm_config, make_workspace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.llm_config import AUTH_METHOD_API_KEY, AUTH_METHOD_OAUTH, StoredOAuthTokens
from suitest_db.repositories.llm_configs import LLMConfigCreate, LLMConfigRepo


@pytest.mark.asyncio
async def test_list_paginated_two_pages(session: AsyncSession) -> None:
    repo = LLMConfigRepo(session)
    ws = await make_workspace(session)
    for _ in range(3):
        await make_llm_config(session, workspace=ws)

    first, cursor = await repo.list_paginated(cursor=None, limit=2, filters={"workspace_id": ws.id})
    assert len(first) == 2
    assert cursor is not None

    second, cursor2 = await repo.list_paginated(
        cursor=cursor, limit=2, filters={"workspace_id": ws.id}
    )
    assert len(second) == 1
    assert cursor2 is None


@pytest.mark.asyncio
async def test_get_active(session: AsyncSession) -> None:
    repo = LLMConfigRepo(session)
    ws = await make_workspace(session)
    await make_llm_config(session, workspace=ws, is_active=False)
    active = await make_llm_config(session, workspace=ws, is_active=True)

    found = await repo.get_active(ws.id)
    assert found is not None
    assert found.id == active.id


@pytest.mark.asyncio
async def test_oauth_tokens_round_trip_and_stay_encrypted(session: AsyncSession) -> None:
    """The token blob decodes back on read, and never lands as plaintext."""
    repo = LLMConfigRepo(session)
    ws = await make_workspace(session)
    tokens = StoredOAuthTokens(
        access_token="at",
        refresh_token="rt",
        id_token="it",
        expires_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        account_id="acc_1",
        email="dev@example.com",
    )

    row = await repo.create(
        LLMConfigCreate(
            workspace_id=ws.id,
            provider="chatgpt",
            model="gpt-5.6",
            auth_method=AUTH_METHOD_OAUTH,
            oauth_tokens_encrypted=tokens.model_dump_json(),
            is_active=True,
        )
    )

    assert row.auth_method == AUTH_METHOD_OAUTH
    assert row.oauth_tokens == tokens

    raw = await session.scalar(
        text("SELECT oauth_tokens_encrypted FROM llm_configs WHERE id = :id"), {"id": row.id}
    )
    assert raw is not None
    assert b"at" not in bytes(raw)


@pytest.mark.asyncio
async def test_api_key_configs_default_to_the_api_key_auth_method(session: AsyncSession) -> None:
    """Existing rows keep working without naming an auth method."""
    ws = await make_workspace(session)
    row = await make_llm_config(session, workspace=ws)
    assert row.auth_method == AUTH_METHOD_API_KEY
    assert row.oauth_tokens is None
