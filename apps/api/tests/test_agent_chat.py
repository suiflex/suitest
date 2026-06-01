"""Tests for ``POST /api/v1/agent/chat`` (M3-12 / M3-13)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.agent import AgentMessage, AgentSession
from suitest_db.models.llm_config import LLMConfig
from suitest_shared.domain.enums import AgentSessionKind

if TYPE_CHECKING:
    from api_harness import ApiDb


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


@pytest.mark.asyncio
async def test_chat_requires_active_llm(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="chat-nollm@example.com")
    ws = await api_db.member_workspace(user, slug="chat-nollm-ws")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/agent/chat",
            headers={"X-Workspace-Id": ws.id},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_chat_streams_tokens_and_persists_session(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="chat-ok@example.com")
    ws = await api_db.member_workspace(user, slug="chat-ok-ws")
    await _activate_mock_llm(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/agent/chat",
            headers={"X-Workspace-Id": ws.id},
            json={"messages": [{"role": "user", "content": "what is failing?"}]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.text)

    kinds = [k for k, _ in events]
    assert kinds[0] == "progress"
    assert "token" in kinds
    assert kinds[-1] == "done"
    done = events[-1][1]
    assert "agent_session_id" in done
    assert isinstance(done["content"], str) and done["content"]

    # CONVERSATION session + user/agent messages persisted for replay.
    async with api_db.maker() as session:
        sess = await session.scalar(select(AgentSession).where(AgentSession.workspace_id == ws.id))
        assert sess is not None
        assert sess.kind is AgentSessionKind.CONVERSATION
        msgs = (
            await session.scalars(select(AgentMessage).where(AgentMessage.session_id == sess.id))
        ).all()
        assert len(msgs) == 2  # user + agent
        assert sess.status == "completed"
