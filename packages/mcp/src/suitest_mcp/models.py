"""Pydantic v2 models for the MCP layer (docs/MCP_PLUGINS.md).

These types are the wire shape between the runner / agent and the MCP client
layer. ``McpProviderConfig`` is the in-memory representation a session is opened
against; ``McpToolResult`` is the normalized return value from one tool call;
``McpHealthStatus`` is the snapshot persisted by the background health monitor.

``McpTransport`` extends the on-disk transport enum (``stdio``/``sse``/``ws``,
which lives in :mod:`suitest_shared.domain.enums` and is persisted to Postgres
as the ``mcp_transport`` Postgres ENUM) with an in-process variant. ``IN_PROCESS``
is in-memory only: it never round-trips through the database — bundled providers
(api-http-mcp, postgres-mcp) spawn over a pair of memory streams, no subprocess.
We therefore keep the wire-side enum (DB column) free of the bundling-only value
and define a richer client-side enum here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpTransport(StrEnum):
    """Transport modes the generic client understands.

    Mirrors :class:`suitest_shared.domain.enums.McpTransport` + an extra
    ``IN_PROCESS`` value used only by bundled in-memory providers.
    """

    STDIO = "stdio"
    SSE = "sse"
    WS = "ws"
    IN_PROCESS = "in_process"


class McpHealthState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class McpToolSchema(BaseModel):
    """Single tool entry as advertised by ``tools/list``."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: Annotated[str, Field(min_length=1)]
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpProviderConfig(BaseModel):
    """Provider connection spec consumed by the generic client.

    Carries both the persisted columns (``id``, ``workspace_id``, ``name``, ...)
    and pool-tuning knobs (``max_sessions``, ``idle_ttl_seconds``, ...). Bundled
    builtins use a synthetic ``builtin:*`` id and the sentinel workspace
    ``_builtin_`` — they're not stored in Postgres.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    id: Annotated[str, Field(min_length=1)]
    workspace_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    kind: Annotated[str, Field(min_length=1)]
    transport: McpTransport
    endpoint: str = ""
    command: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    config_json: dict[str, Any] = Field(default_factory=dict)
    secrets_ref: str | None = None
    is_default_for_target: dict[str, bool] = Field(default_factory=dict)
    max_sessions: int = 4
    idle_ttl_seconds: int = 60
    spawn_timeout_seconds: float = 10.0
    call_timeout_seconds: float = 30.0


class McpArtifact(BaseModel):
    """One artifact emitted by a tool call (screenshot, HAR, DOM dump, ...)."""

    kind: Literal[
        "SCREENSHOT",
        "HAR",
        "DOM_SNAPSHOT",
        "CONSOLE_LOG",
        "VIDEO",
        "TRACE",
        "CUSTOM",
    ]
    filename: str
    content_type: str
    bytes_: bytes | None = Field(default=None, alias="bytes", repr=False)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpToolCall(BaseModel):
    """Caller-side description of one tool invocation."""

    provider: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    step_id: str | None = None
    workspace_id: str | None = None


class McpToolResult(BaseModel):
    """Normalized outcome of a tool call.

    ``ok=False`` means the tool returned ``isError=true`` or raised before the
    timeout fired; the client raises :class:`McpToolTimeout` instead of returning
    a ``McpToolResult`` for hard timeouts.
    """

    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    artifacts: list[McpArtifact] = Field(default_factory=list)
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None


class McpHealthStatus(BaseModel):
    """One probe snapshot — emitted by the health monitor per provider per tick."""

    provider_id: str
    name: str
    state: McpHealthState
    latency_ms: int | None = None
    error: str | None = None
    checked_at: datetime
