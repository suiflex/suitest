"""Tests for integrations with AES-GCM encrypted secrets (Task 2g)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.integration import Integration
from suitest_db.models.workspace import Workspace
from suitest_shared.domain.enums import IntegrationKind

_MCP_KINDS = [
    IntegrationKind.MCP_API,
    IntegrationKind.MCP_POSTGRES,
    IntegrationKind.MCP_KUBERNETES,
    IntegrationKind.MCP_GRAPHQL,
    IntegrationKind.MCP_GRPC,
    IntegrationKind.MCP_APPIUM,
    IntegrationKind.MCP_MONGO,
    IntegrationKind.MCP_MYSQL,
]


async def _workspace(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


@pytest.mark.asyncio
async def test_integration_kind_jira(session: AsyncSession) -> None:
    ws = await _workspace(session)
    integ = Integration(workspace_id=ws.id, kind=IntegrationKind.JIRA, name="Jira", config={})
    session.add(integ)
    await session.flush()
    fetched = await session.scalar(select(Integration).where(Integration.id == integ.id))
    assert fetched is not None
    assert fetched.kind is IntegrationKind.JIRA
    assert fetched.status == "active"


@pytest.mark.asyncio
async def test_integration_secrets_roundtrip(session: AsyncSession) -> None:
    ws = await _workspace(session)
    integ = Integration(
        workspace_id=ws.id,
        kind=IntegrationKind.GITHUB,
        name="GH",
        config={"org": "nusantara"},
        secrets_encrypted="cred-xyz",
    )
    session.add(integ)
    await session.flush()
    iid = integ.id
    session.expunge_all()

    fetched = await session.scalar(select(Integration).where(Integration.id == iid))
    assert fetched is not None
    assert fetched.secrets_encrypted == "cred-xyz"  # decrypted transparently

    # Raw bytes at rest must NOT contain the plaintext.
    raw = await session.scalar(
        text("SELECT secrets_encrypted FROM integrations WHERE id = :id").bindparams(id=iid)
    )
    assert raw is not None
    assert b"cred-xyz" not in bytes(raw)


@pytest.mark.parametrize("kind", _MCP_KINDS)
@pytest.mark.asyncio
async def test_integration_mcp_kind_values(session: AsyncSession, kind: IntegrationKind) -> None:
    ws = await _workspace(session)
    integ = Integration(
        workspace_id=ws.id, kind=kind, name=f"{kind.value}", config={}, secrets_encrypted="s"
    )
    session.add(integ)
    await session.flush()
    iid = integ.id
    session.expunge_all()
    fetched = await session.scalar(select(Integration).where(Integration.id == iid))
    assert fetched is not None
    assert fetched.kind is kind
    assert fetched.secrets_encrypted == "s"
