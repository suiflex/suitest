"""Agent conversation (chat) I/O schemas (M3-12 / M3-13).

``POST /agent/chat`` accepts a message history and streams the assistant reply as
SSE token frames (``event: token``), emitting a ``tool`` frame (mirrored on the
WS gateway) when the model requests a tool call, and a terminal ``done`` frame
with the full content + usage. CLOUD/LOCAL only.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageInput(BaseModel):
    """One prior turn in the conversation history."""

    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["user", "assistant", "system", "tool"]
    content: Annotated[str, Field(min_length=1, max_length=100_000)]


class ChatRequest(BaseModel):
    """``POST /agent/chat`` body — the running history + optional session id."""

    model_config = ConfigDict(str_strip_whitespace=True)

    messages: Annotated[list[ChatMessageInput], Field(min_length=1, max_length=100)]
    session_id: str | None = None
    seed: int | None = None


class ChatSseEvent(BaseModel):
    """One SSE frame. ``kind`` is the SSE ``event:`` field."""

    kind: Literal["progress", "token", "tool", "done", "error"]
    data: dict[str, object]
