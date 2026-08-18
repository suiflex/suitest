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
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_shared.schemas.agent_chat import ChatRequest, ChatSseEvent

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.deps.tier import require_tier
from suitest_api.services.agent_chat_service import AgentChatService
from suitest_api.services.llm_credentials import resolve_for_config

router = APIRouter(prefix="/api/v1", tags=["agent"])


def _format_sse(event: ChatSseEvent) -> str:
    return f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"


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

    credential = await resolve_for_config(session, config)
    ws_redis = getattr(request.app.state, "ws_redis", None)

    async def publish(envelope: dict[str, object]) -> None:
        if ws_redis is not None:
            await ws_redis.publish(f"workspace:{ctx.workspace_id}", json.dumps(envelope))

    svc = AgentChatService(session, workspace_id=ctx.workspace_id, user_id=ctx.user_id)

    async def stream() -> AsyncIterator[bytes]:
        async for event in svc.stream(
            payload,
            credential=credential,
            model=config.model,
            publish=publish,
        ):
            yield _format_sse(event).encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
