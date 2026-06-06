"""Tests for ``POST /api/v1/generators/url-semantic`` (M3-7, LLM-driven).

Covers the tier gate (409 without an active LLM), suite scope (404), and the SSE
lifecycle + ``AgentSession`` persistence with the deterministic ``mock`` provider.
Draft mapping is unit-tested in
``packages/agent/tests/test_url_semantic_generator.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.agent import AgentSession
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import AgentSessionKind

if TYPE_CHECKING:
    import httpx
    from api_harness import ApiDb


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "us-proj") -> Suite:
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
        "/api/v1/generators/url-semantic", headers={"X-Workspace-Id": ws_id}, json=payload
    )


@pytest.mark.asyncio
async def test_requires_active_llm(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="us-nollm@example.com")
    ws = await api_db.member_workspace(user, slug="us-nollm-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(
            c,
            ws.id,
            {"target_suite_id": suite.id, "url": "https://x.example", "intent": "checkout"},
        )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_unknown_suite_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="us-404@example.com")
    ws = await api_db.member_workspace(user, slug="us-404-ws")
    await _activate_mock_llm(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(
            c, ws.id, {"target_suite_id": "nope", "url": "https://x.example", "intent": "checkout"}
        )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_streams_and_persists_session(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="us-ok@example.com")
    ws = await api_db.member_workspace(user, slug="us-ok-ws")
    suite = await _project_suite(api_db, ws.id)
    await _activate_mock_llm(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(
            c,
            ws.id,
            {
                "target_suite_id": suite.id,
                "url": "https://shop.example",
                "intent": "checkout flow",
                "seed": 9,
            },
        )
        assert resp.status_code == 200, resp.text
        events = _parse_sse(resp.text)

    kinds = [k for k, _ in events]
    assert kinds[0] == "progress"
    assert kinds[-1] == "complete"

    async with api_db.maker() as session:
        sess = await session.scalar(select(AgentSession).where(AgentSession.workspace_id == ws.id))
    assert sess is not None
    assert sess.kind is AgentSessionKind.GENERATION
    assert sess.provider == "mock"
    assert sess.seed == 9
