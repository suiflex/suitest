"""Agent conversation endpoint (M3-12 / M3-13).

``POST /agent/chat`` streams the assistant reply as SSE token frames and mirrors
tool-call requests on the WS gateway. CLOUD/LOCAL only — a workspace with no
active ``LLMConfig`` is rejected with ``409`` before the stream opens.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import TierFlag
from suitest_db.models.llm_config import LLMConfig
from suitest_db.repositories.agent_sessions import AgentSessionRepo
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_shared.domain.enums import MessageRole
from suitest_shared.schemas.agent_chat import ChatRequest, ChatSseEvent

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.deps.tier import require_tier
from suitest_api.services.agent_chat_service import AgentChatService
from suitest_api.services.llm_credentials import resolve_for_config
from suitest_api.services.model_catalog import MODEL_CATALOG

router = APIRouter(prefix="/api/v1", tags=["agent"])


def _format_sse(event: ChatSseEvent) -> str:
    return f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"


def _model_for(payload: ChatRequest, config: LLMConfig) -> str:
    """The model this turn asks for: the panel's pick, or the workspace default.

    The pick is checked against the provider's catalog rather than passed
    through, so a request cannot name an arbitrary model on the workspace's
    credential. The configured model always passes — a workspace may well be set
    to something the curated table has not caught up with.
    """
    wanted = (payload.model or "").strip()
    if not wanted or wanted == config.model:
        return config.model
    catalog = MODEL_CATALOG.get(config.provider.strip().lower(), [])
    if wanted not in {str(entry["id"]) for entry in catalog}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"model {wanted!r} is not one this provider offers",
        )
    return wanted


@router.post("/agent/chat")
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def agent_chat(
    payload: ChatRequest,
    request: Request,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Stream a conversation-mode reply (SSE tokens + WS tool events)."""
    config = await LLMConfigRepo(session).get_active(ctx.workspace_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active LLM configured for this workspace",
        )

    model = _model_for(payload, config)
    credential = await resolve_for_config(session, config)
    ws_redis = getattr(request.app.state, "ws_redis", None)

    async def publish(envelope: dict[str, object]) -> None:
        if ws_redis is not None:
            await ws_redis.publish(f"workspace:{ctx.workspace_id}", json.dumps(envelope))

    svc = AgentChatService(session, ctx=ctx)

    async def stream() -> AsyncIterator[bytes]:
        async for event in svc.stream(
            payload,
            credential=credential,
            model=model,
            publish=publish,
        ):
            yield _format_sse(event).encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agent/chat/{session_id}/history")
async def agent_chat_history(
    session_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[dict[str, str]]:
    """Replay a stored conversation so the panel survives a page reload.

    USER turns map to ``user``; AGENT turns to ``assistant``. 404 when the
    session does not exist or belongs to another workspace (no scoping leak).
    """
    repo = AgentSessionRepo(session)
    agent_session = await repo.get_by_id(session_id)
    if agent_session is None or agent_session.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    messages = await repo.list_messages(session_id)
    return [
        {
            "role": "assistant" if m.role == MessageRole.AGENT else "user",
            "content": m.content,
        }
        for m in messages
        if m.role in (MessageRole.USER, MessageRole.AGENT)
    ]
