"""Tests for ``POST /api/v1/generators/mcp-discovery`` (M3-9, LLM-driven).

Covers the tier gate (409 without an active LLM), provider scope (404),
empty-catalog handling, and the SSE lifecycle + ``AgentSession`` persistence with
the deterministic ``mock`` provider. Draft mapping is unit-tested in
``packages/agent/tests/test_mcp_discovery_generator.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.agent import AgentSession
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import McpTransport

if TYPE_CHECKING:
    import httpx
    from api_harness import ApiDb


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "mcpd-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _activate_mock_llm(api_db: ApiDb, ws_id: str) -> None:
    await api_db.add_all(
        [
            LLMConfig(
                workspace_id=ws_id,
                provider="mock",
                model="mock-1",
                api_key_encrypted=None,
                config_json={},
                is_active=True,
            )
        ]
    )


async def _provider(
    api_db: ApiDb, ws_id: str, *, name: str = "orders-mcp", tools: list[dict[str, object]] | None
) -> McpProvider:
    row = McpProvider(
        workspace_id=ws_id,
        name=name,
        kind="custom",
        endpoint="http://localhost:9999",
        transport=McpTransport.SSE,
        config_json={"tools": tools or []},
        is_default_for_target={"BE_REST": True},
        enabled=True,
    )
    await api_db.add_all([row])
    return row


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for raw_block in body.split("\n\n"):
        block = raw_block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


async def _post(
    client: httpx.AsyncClient, ws_id: str, payload: dict[str, object]
) -> httpx.Response:
    return await client.post(
        "/api/v1/generators/mcp-discovery", headers={"X-Workspace-Id": ws_id}, json=payload
    )


@pytest.mark.asyncio
async def test_requires_active_llm(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcpd-nollm@example.com")
    ws = await api_db.member_workspace(user, slug="mcpd-nollm-ws")
    suite = await _project_suite(api_db, ws.id)
    prov = await _provider(api_db, ws.id, tools=[{"name": "t", "description": "d"}])
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"target_suite_id": suite.id, "mcp_provider_id": prov.id})
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_unknown_provider_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcpd-404@example.com")
    ws = await api_db.member_workspace(user, slug="mcpd-404-ws")
    suite = await _project_suite(api_db, ws.id)
    await _activate_mock_llm(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"target_suite_id": suite.id, "mcp_provider_id": "nope"})
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_empty_catalog_error_frame(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcpd-empty@example.com")
    ws = await api_db.member_workspace(user, slug="mcpd-empty-ws")
    suite = await _project_suite(api_db, ws.id)
    await _activate_mock_llm(api_db, ws.id)
    prov = await _provider(api_db, ws.id, tools=[])
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"target_suite_id": suite.id, "mcp_provider_id": prov.id})
        assert resp.status_code == 200, resp.text
        events = _parse_sse(resp.text)
    kinds = [k for k, _ in events]
    assert "error" in kinds
    err = next(d for k, d in events if k == "error")
    assert err["code"] == "EMPTY_CATALOG"


@pytest.mark.asyncio
async def test_streams_and_persists_session(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="mcpd-ok@example.com")
    ws = await api_db.member_workspace(user, slug="mcpd-ok-ws")
    suite = await _project_suite(api_db, ws.id)
    await _activate_mock_llm(api_db, ws.id)
    prov = await _provider(
        api_db,
        ws.id,
        tools=[{"name": "create_order", "description": "Create an order"}],
    )
    async with api_db.client(user) as c:
        resp = await _post(
            c, ws.id, {"target_suite_id": suite.id, "mcp_provider_id": prov.id, "seed": 3}
        )
        assert resp.status_code == 200, resp.text
        events = _parse_sse(resp.text)

    phases = [d.get("phase") for k, d in events if k == "progress"]
    assert "exploring" in phases
    assert events[-1][0] == "complete"

    async with api_db.maker() as session:
        sess = await session.scalar(select(AgentSession).where(AgentSession.workspace_id == ws.id))
    assert sess is not None
    assert sess.provider == "mock"
    assert sess.seed == 3
