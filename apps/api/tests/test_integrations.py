"""Task 7g — integration read endpoint tests with redacted secrets (docs/API.md §3.9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import IntegrationKind

if TYPE_CHECKING:
    from api_harness import ApiDb

_REAL_SECRET = "sk-realkey-abcd1234"


@pytest.mark.asyncio
async def test_list_integrations_filter_kind_jira(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="int-list@example.com")
    ws = await api_db.member_workspace(user, slug="int-list-ws")
    await api_db.add_all(
        [
            Integration(workspace_id=ws.id, kind=IntegrationKind.JIRA, name="Jira", config={}),
            Integration(workspace_id=ws.id, kind=IntegrationKind.GITHUB, name="GH", config={}),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get("/api/v1/integrations?kind=JIRA", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    items = resp.json()
    assert {i["kind"] for i in items} == {"JIRA"}


@pytest.mark.asyncio
async def test_get_integration_secrets_always_redacted(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="int-secret@example.com")
    ws = await api_db.member_workspace(user, slug="int-secret-ws")
    integration = Integration(
        workspace_id=ws.id,
        kind=IntegrationKind.JIRA,
        name="Jira",
        config={"baseUrl": "https://jira.example"},
        secrets_encrypted=_REAL_SECRET,
    )
    await api_db.add_all([integration])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/integrations/{integration.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    raw_body = resp.text
    # The full secret must never appear anywhere in the response.
    assert _REAL_SECRET not in raw_body
    assert "sk-realkey-" not in raw_body
    data = resp.json()
    assert data["has_secrets"] is True
    assert data["secrets"]["redacted"] is True
    assert data["secrets"]["hint"].endswith("1234")  # last 4 only
    assert data["config"] == {"baseUrl": "https://jira.example"}


@pytest.mark.asyncio
async def test_get_integration_no_secrets_returns_null(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="int-nosecret@example.com")
    ws = await api_db.member_workspace(user, slug="int-nosecret-ws")
    integration = Integration(
        workspace_id=ws.id, kind=IntegrationKind.SLACK, name="Slack", config={}
    )
    await api_db.add_all([integration])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/integrations/{integration.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_secrets"] is False
    assert data["secrets"] is None


@pytest.mark.asyncio
async def test_get_integration_404_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="int-x@example.com")
    ws = await api_db.member_workspace(user, slug="int-x-ws")
    other = await api_db.seed_workspace(slug="int-x-other", name="Other")
    integration = Integration(
        workspace_id=other.id, kind=IntegrationKind.JIRA, name="Jira", config={}
    )
    await api_db.add_all([integration])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/integrations/{integration.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 404
