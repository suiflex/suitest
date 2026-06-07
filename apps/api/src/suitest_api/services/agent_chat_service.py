"""Agent conversation (chat) service (M3-12 / M3-13).

Streams the assistant reply token-by-token over SSE (``provider.stream_complete``)
and persists the turn as an ``AgentSession`` (kind CONVERSATION) + its user/agent
messages for replay. When the model emits a tool-request JSON instead of prose, a
``tool`` SSE frame is yielded AND mirrored on the WS gateway
(``agent.tool.call``) so the UI can surface a confirm (mutations always require an
explicit confirm — AUTONOMY.md §3 hard rail).

CLOUD/LOCAL only; the router rejects ZERO / no-LLM with 409 before streaming.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from suitest_agent.graphs._util import parse_json_object
from suitest_agent.providers.base import ChatMessage, ModelCall
from suitest_agent.providers.litellm_router import get_provider
from suitest_db.repositories.agent_sessions import AgentSessionCreate, AgentSessionRepo
from suitest_shared.domain.enums import AgentSessionKind, MessageRole
from suitest_shared.schemas.agent_chat import ChatRequest, ChatSseEvent

from suitest_api.services.prompt_resolver import resolve_and_pin

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

# Publishes a ``{"event", "data"}`` envelope to the workspace WS channel.
WsPublish = Callable[[dict[str, object]], Awaitable[None]]


class AgentChatService:
    def __init__(self, session: AsyncSession, *, workspace_id: str, user_id: str | None) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._user_id = user_id

    @staticmethod
    def _as_uuid(user_id: str | None) -> uuid.UUID | None:
        import uuid as _uuid

        try:
            return _uuid.UUID(user_id) if user_id else None
        except (ValueError, AttributeError):
            return None

    async def stream(
        self,
        request: ChatRequest,
        *,
        provider_name: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
        publish: WsPublish | None = None,
    ) -> AsyncIterator[ChatSseEvent]:
        """Stream the assistant reply; persist the session + messages."""
        # M5-3: honour an active per-workspace prompt fork; falls back to the
        # file default when none exists. ``resolve_and_pin`` also records the
        # reproducibility row, replacing the direct read_prompt + ensure pair.
        prompt_content, prompt_row = await resolve_and_pin(
            self._session, workspace_id=self._workspace_id, prompt_name="converse"
        )
        repo = AgentSessionRepo(self._session)
        agent_session = await repo.create(
            AgentSessionCreate(
                workspace_id=self._workspace_id,
                kind=AgentSessionKind.CONVERSATION,
                model_id=model,
                provider=provider_name,
                user_id=self._as_uuid(self._user_id),
                prompt_version_id=prompt_row.id,
                seed=request.seed,
                temperature=0.3,
            )
        )

        # Persist the latest user turn (the rest is prior context already stored).
        last_user = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user is not None:
            await repo.add_message(
                agent_session.id, role=MessageRole.USER, content=last_user.content
            )

        yield ChatSseEvent(kind="progress", data={"agent_session_id": agent_session.id})

        messages = [ChatMessage(role="system", content=prompt_content)]
        messages.extend(ChatMessage(role=m.role, content=m.content) for m in request.messages)
        call = ModelCall(model=model, messages=messages, seed=request.seed, temperature=0.3)

        provider = get_provider(provider_name, api_key=api_key, base_url=base_url)
        accumulated = ""
        tokens_out = 0
        async for chunk in provider.stream_complete(call):
            if chunk.delta:
                accumulated += chunk.delta
                yield ChatSseEvent(kind="token", data={"delta": chunk.delta})
            if chunk.done:
                tokens_out = chunk.tokens_out

        # Tool request? (a bare JSON envelope with a "tool" key). Emit a tool
        # frame + WS mirror so the UI can render a confirm card.
        tool_obj = parse_json_object(accumulated) if accumulated.strip().startswith("{") else {}
        tool = tool_obj.get("tool")
        if isinstance(tool, str) and tool.strip():
            arguments = tool_obj.get("arguments", {})
            tool_data: dict[str, object] = {
                "tool": tool,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "agent_session_id": agent_session.id,
            }
            if publish is not None:
                await publish({"event": "agent.tool.call", "data": tool_data})
            yield ChatSseEvent(kind="tool", data=tool_data)

        await repo.add_message(agent_session.id, role=MessageRole.AGENT, content=accumulated)
        await repo.complete(agent_session.id, tokens_out=tokens_out)
        await self._session.commit()

        yield ChatSseEvent(
            kind="done",
            data={
                "agent_session_id": agent_session.id,
                "content": accumulated,
                "tokens_out": tokens_out,
            },
        )
