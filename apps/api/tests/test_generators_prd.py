"""Tests for ``POST /api/v1/generators/prd`` (M3-6, LLM-driven).

Exercises the endpoint contract against a real DB with the deterministic
``mock`` provider as the workspace's active LLM: the tier gate (409 when no LLM
configured), suite scope (404), the SSE lifecycle (``progress`` → ``complete``),
and the reproducibility side effects — a persisted ``GeneratorRun`` (source=prd)
and an ``AgentSession`` (kind GENERATION, provider mock).

The draft *mapping* logic is unit-tested deterministically in
``packages/agent/tests/test_prd_generator.py``; here the plain ``mock`` echo
returns non-JSON, so a successful run yields zero cases but still proves the full
session + run + SSE wiring.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.agent import AgentSession
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import AgentSessionKind

if TYPE_CHECKING:
    import httpx
    from api_harness import ApiDb


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "prd-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _activate_mock_llm(api_db: ApiDb, ws_id: str) -> None:
    """Make ``mock`` the active LLM so the workspace resolves to CLOUD tier."""
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
        assert lines[0].startswith("event: "), f"bad event line: {lines[0]!r}"
        assert lines[1].startswith("data: "), f"bad data line: {lines[1]!r}"
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


async def _post(
    client: httpx.AsyncClient, ws_id: str, payload: dict[str, object]
) -> httpx.Response:
    return await client.post(
        "/api/v1/generators/prd", headers={"X-Workspace-Id": ws_id}, json=payload
    )


@pytest.mark.asyncio
async def test_prd_requires_active_llm(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prd-nollm@example.com")
    ws = await api_db.member_workspace(user, slug="prd-nollm-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"target_suite_id": suite.id, "prd_text": "Users log in"})
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_prd_unknown_suite_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prd-404@example.com")
    ws = await api_db.member_workspace(user, slug="prd-404-ws")
    await _activate_mock_llm(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"target_suite_id": "nope", "prd_text": "x"})
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_prd_streams_and_persists_session(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prd-ok@example.com")
    ws = await api_db.member_workspace(user, slug="prd-ok-ws")
    suite = await _project_suite(api_db, ws.id)
    await _activate_mock_llm(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/prd",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite.id, "prd_text": "Users can checkout", "seed": 7},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.text)

    kinds = [k for k, _ in events]
    assert kinds[0] == "progress"
    assert kinds[-1] == "complete"
    complete = events[-1][1]
    assert "agent_session_id" in complete
    assert "generator_run_id" in complete

    # A GeneratorRun (source=prd) and an AgentSession (GENERATION/mock) persisted.
    async with api_db.maker() as session:
        run = await session.scalar(
            select(GeneratorRun).where(
                GeneratorRun.workspace_id == ws.id, GeneratorRun.source == "prd"
            )
        )
        sess = await session.scalar(select(AgentSession).where(AgentSession.workspace_id == ws.id))
    assert run is not None
    assert sess is not None
    assert sess.kind is AgentSessionKind.GENERATION
    assert sess.provider == "mock"
    assert sess.seed == 7
    assert sess.prompt_version_id is not None
    assert sess.status == "completed"


@pytest.mark.asyncio
async def test_prd_unauthenticated_401(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prd-auth@example.com")
    ws = await api_db.member_workspace(user, slug="prd-auth-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(None) as c:  # no user → unauthenticated
        resp = await _post(c, ws.id, {"target_suite_id": suite.id, "prd_text": "x"})
    assert resp.status_code == 401, resp.text
