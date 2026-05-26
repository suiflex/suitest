# M1c — ZERO Runner + MCP Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `packages/mcp` (client + registry + pool + routing) with 3 bundled MCP providers (playwright-mcp, api-http-mcp built-in, postgres-mcp), `apps/runner` ARQ worker that pulls run jobs from Redis, dispatches each `test_step` to the correct MCP provider, streams stdout/stderr/screenshots via Redis pub/sub → FastAPI WebSocket → UI, uploads artifacts to MinIO. End-to-end: trigger run via API → MCP executes → live logs in UI → artifacts viewable. Deterministic only (no LLM in M1c — covered in M3).

**Architecture:** `packages/mcp` is the universal MCP client layer with connection pool, health monitoring, and routing table. Each bundled provider has a config module under `packages/mcp/src/suitest_mcp/providers/`. `apps/runner` uses ARQ (Redis-backed) for job queue; one worker process handles many jobs concurrently (asyncio-native). Per run job: open MCP sessions per provider needed by steps, execute each step against its `mcp_provider`, capture output to Redis pub/sub channel `run:<id>`, FastAPI WS gateway forwards to subscribed clients. Artifacts (screenshots, HAR, console logs) upload to MinIO using aioboto3.

**Tech Stack:** Python 3.12, ARQ 0.26+, Redis 7, aioredis, mcp (Python SDK), httpx, asyncpg, psycopg (for postgres-mcp passthrough), playwright (for playwright-mcp), aioboto3 (MinIO/S3), websockets, structlog, OpenTelemetry, pytest-asyncio, testcontainers (Postgres + Redis + MinIO + Playwright).

---

## Cross-cutting conventions

- Async everywhere (`asyncio`). No sync blocking calls inside coroutines.
- mypy strict (`disallow_untyped_defs=true`). No `Any` — use `TypedDict` / `Protocol` / generics.
- Pydantic v2 with `ConfigDict(from_attributes=True, str_strip_whitespace=True)`.
- Conventional commits per task (`feat(mcp): ...`, `feat(runner): ...`, etc.).
- TDD ordering: failing test → impl → green → commit.
- Capability gate: every endpoint declares `Depends(require_tier(Tier.ZERO | Tier.LOCAL | Tier.CLOUD))`.
- Audit log on every mutation via `packages/db/audit.py::write_audit`.
- OTel: every MCP invocation wrapped in `mcp.invoke` span (attrs: provider, tool, run_id, step_id, outcome).
- No barrel files (`__init__.py` stays empty except docstring).
- WS channel naming: `run:<run_id>` per-run, `workspace:<workspace_id>` workspace-wide (see `docs/API.md` §4).

---

## Task 1: `packages/mcp` scaffolding

Bootstrap the package with `pyproject.toml`, module skeleton, Pydantic models, and error hierarchy.

### 1.1 `packages/mcp/pyproject.toml`

```toml
[project]
name = "suitest-mcp"
version = "0.4.0"
requires-python = ">=3.12"
dependencies = [
  "mcp>=1.0.0", "httpx>=0.27", "websockets>=12", "pydantic>=2.7",
  "structlog>=24.1", "opentelemetry-api>=1.25", "opentelemetry-sdk>=1.25",
  "anyio>=4.3", "redis[hiredis]>=5.0",
  "suitest-shared", "suitest-db", "suitest-core",
]

[project.optional-dependencies]
test = ["pytest>=8.2", "pytest-asyncio>=0.23", "pytest-mock>=3.14",
        "testcontainers[postgres,redis,minio]>=4.5"]

[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/suitest_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "strict"
```

### 1.2 Directory skeleton

```
packages/mcp/
├── pyproject.toml
├── src/suitest_mcp/
│   ├── __init__.py          # version constant only
│   ├── client.py            # transport wrapper
│   ├── registry.py          # provider catalog
│   ├── pool.py              # connection pool
│   ├── routing.py           # target_kind → provider
│   ├── invoker.py           # orchestrator entry
│   ├── health.py            # background probe
│   ├── normalizer.py        # MCP result → DB shape
│   ├── models.py            # Pydantic v2 models
│   ├── errors.py
│   ├── providers/
│   │   ├── __init__.py
│   │   └── builtin_specs.py
│   └── bundled/
│       ├── __init__.py
│       ├── in_process_runtime.py
│       ├── api_http.py
│       ├── playwright.py
│       └── postgres.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── mcp_server_mock.py
```

### 1.3 `models.py`

```python
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class McpTransport(StrEnum):
    STDIO = "stdio"; SSE = "sse"; WS = "ws"; IN_PROCESS = "in_process"


class McpHealthState(StrEnum):
    OK = "ok"; DEGRADED = "degraded"; DOWN = "down"; UNKNOWN = "unknown"


class McpToolSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Annotated[str, Field(min_length=1)]
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpProviderConfig(BaseModel):
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
    kind: Literal["SCREENSHOT", "HAR", "DOM_SNAPSHOT", "CONSOLE_LOG", "VIDEO", "TRACE", "CUSTOM"]
    filename: str
    content_type: str
    bytes_: bytes | None = Field(default=None, alias="bytes", repr=False)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpToolCall(BaseModel):
    provider: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    step_id: str | None = None
    workspace_id: str | None = None


class McpToolResult(BaseModel):
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    artifacts: list[McpArtifact] = Field(default_factory=list)
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None


class McpHealthStatus(BaseModel):
    provider_id: str
    name: str
    state: McpHealthState
    latency_ms: int | None = None
    error: str | None = None
    checked_at: datetime
```

### 1.4 `errors.py`

```python
class McpError(Exception):
    code: str = "MCP_GENERIC"
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code: self.code = code

class McpProviderUnavailable(McpError): code = "MCP_PROVIDER_UNAVAILABLE"
class McpProviderUnhealthy(McpError):   code = "MCP_PROVIDER_UNHEALTHY"
class McpToolTimeout(McpError):         code = "MCP_TOOL_TIMEOUT"
class McpToolFailed(McpError):          code = "MCP_TOOL_FAILED"
class McpPoolExhausted(McpError):       code = "MCP_POOL_EXHAUSTED"
class McpHandshakeFailed(McpError):     code = "MCP_HANDSHAKE_FAILED"
```

### Steps

- [ ] **1.1** Create `pyproject.toml`; add to root uv workspace members
- [ ] **1.2** Create directory skeleton (empty docstring per file, no barrels)
- [ ] **1.3** Write `models.py` and `errors.py`
- [ ] **1.4** `uv sync`; verify `import suitest_mcp.models` succeeds
- [ ] **1.5** `tests/test_models.py` instantiating each model with valid + invalid input
- [ ] **1.6** `uv run pytest packages/mcp/tests -q` green
- [ ] **1.7** `uv run mypy packages/mcp/src` clean
- [ ] **1.8** Commit: `feat(mcp): scaffold packages/mcp with pyproject + models + errors`

---

## Task 2: Generic MCP client + connection lifecycle

Async wrapper around `mcp` SDK supporting stdio / SSE / WS / in-process transports.

### 2.1 `client.py`

```python
from __future__ import annotations
import contextlib, time
from dataclasses import dataclass
from typing import Any
import anyio, structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.websocket import websocket_client
from opentelemetry import trace
from suitest_mcp.errors import McpHandshakeFailed, McpToolFailed, McpToolTimeout
from suitest_mcp.models import McpProviderConfig, McpToolResult, McpTransport

log = structlog.get_logger(__name__)
tracer = trace.get_tracer("suitest.mcp.client")


@dataclass
class McpSession:
    provider: McpProviderConfig
    session: ClientSession
    cleanup: Any
    created_at: float
    last_used_at: float
    invocations: int = 0

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.session.list_tools()
        return [{"name": t.name, "description": t.description or "",
                 "input_schema": t.inputSchema or {}} for t in result.tools]

    async def call_tool(self, tool: str, arguments: dict[str, Any], *,
                        timeout_seconds: float) -> McpToolResult:
        self.invocations += 1
        self.last_used_at = time.monotonic()
        start = time.perf_counter()
        with tracer.start_as_current_span("mcp.invoke") as span:
            span.set_attribute("mcp.provider", self.provider.name)
            span.set_attribute("mcp.tool", tool)
            try:
                with anyio.fail_after(timeout_seconds):
                    result = await self.session.call_tool(name=tool, arguments=arguments)
            except TimeoutError as exc:
                raise McpToolTimeout(f"tool {tool} on {self.provider.name} timed out") from exc
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout = ""
            output: dict[str, Any] = {}
            for content in result.content:
                if getattr(content, "type", "") == "text":
                    stdout += content.text + "\n"
                else:
                    output.setdefault("blocks", []).append(
                        {"type": content.type, "data": getattr(content, "data", None)})
            if result.isError:
                raise McpToolFailed(stdout.strip() or "isError=true")
            return McpToolResult(ok=True, output=output, stdout=stdout.strip(),
                                 stderr="", duration_ms=duration_ms)


async def open_session(provider: McpProviderConfig) -> McpSession:
    if provider.transport == McpTransport.STDIO:
        params = StdioServerParameters(command=provider.command[0],
                                       args=list(provider.command[1:]), env={**provider.env})
        ctx = stdio_client(params)
    elif provider.transport == McpTransport.SSE:
        ctx = sse_client(provider.endpoint, headers=provider.config_json.get("headers", {}))
    elif provider.transport == McpTransport.WS:
        ctx = websocket_client(provider.endpoint)
    elif provider.transport == McpTransport.IN_PROCESS:
        from suitest_mcp.bundled.in_process_runtime import in_process_client
        ctx = in_process_client(provider)
    else:
        raise McpHandshakeFailed(f"unknown transport {provider.transport}")

    try:
        async with anyio.fail_after(provider.spawn_timeout_seconds):
            read, write = await ctx.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
    except TimeoutError as exc:
        with contextlib.suppress(Exception): await ctx.__aexit__(None, None, None)
        raise McpHandshakeFailed(
            f"handshake with {provider.name} timed out after {provider.spawn_timeout_seconds}s") from exc

    async def _cleanup() -> None:
        with contextlib.suppress(Exception): await session.__aexit__(None, None, None)
        with contextlib.suppress(Exception): await ctx.__aexit__(None, None, None)
    return McpSession(provider=provider, session=session, cleanup=_cleanup,
                      created_at=time.monotonic(), last_used_at=time.monotonic())
```

### 2.2 `tests/mcp_server_mock.py` (echo server spawnable as subprocess)

```python
import sys
from pathlib import Path

SCRIPT = r"""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
app = Server("mock-mcp")
@app.list_tools()
async def list_tools():
    return [Tool(name="echo", description="echo", inputSchema={"type": "object"}),
            Tool(name="boom", description="raises", inputSchema={"type": "object"})]
@app.call_tool()
async def call_tool(name, arguments):
    if name == "boom": raise RuntimeError("boom")
    return [TextContent(type="text", text="ECHO:" + str(arguments))]
async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())
if __name__ == "__main__": asyncio.run(main())
"""

class MockMcpServer:
    def __init__(self, tmp_path: Path):
        self.script = tmp_path / "mock_mcp_server.py"
        self.script.write_text(SCRIPT)
    @property
    def command(self) -> list[str]: return [sys.executable, str(self.script)]
```

### 2.3 `tests/test_client.py` — 4 cases

```python
import pytest
from suitest_mcp.client import open_session
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.models import McpProviderConfig, McpTransport

pytestmark = pytest.mark.asyncio

def _cfg(cmd): return McpProviderConfig(id="p1", workspace_id="w1", name="mock",
    kind="test", transport=McpTransport.STDIO, command=cmd)

async def test_open_session_lists_tools(mock_mcp_server):
    sess = await open_session(_cfg(mock_mcp_server.command))
    try: assert any(t["name"] == "echo" for t in await sess.list_tools())
    finally: await sess.cleanup()

async def test_call_tool_returns_result(mock_mcp_server):
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        r = await sess.call_tool("echo", {"hello": "world"}, timeout_seconds=5.0)
        assert r.ok and "ECHO" in r.stdout
    finally: await sess.cleanup()

async def test_call_tool_failure_raises(mock_mcp_server):
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        with pytest.raises(McpToolFailed):
            await sess.call_tool("boom", {}, timeout_seconds=5.0)
    finally: await sess.cleanup()

async def test_call_tool_timeout(mock_mcp_server):
    sess = await open_session(_cfg(mock_mcp_server.command))
    try:
        with pytest.raises(McpToolTimeout):
            await sess.call_tool("echo", {}, timeout_seconds=0.0001)
    finally: await sess.cleanup()
```

### Steps

- [ ] **2.1** Write `client.py` (open_session + McpSession.call_tool)
- [ ] **2.2** Write `tests/mcp_server_mock.py` + `tests/conftest.py` fixture
- [ ] **2.3** Write `tests/test_client.py` (4 cases)
- [ ] **2.4** Tests green; verify OTel span `mcp.invoke` emitted via in-memory exporter
- [ ] **2.5** mypy strict pass
- [ ] **2.6** Commit: `feat(mcp): generic async client with stdio/sse/ws/in-process transports`

---

## Task 3: Connection pool

Per-provider LRU pool with TTL, max-sessions cap, async-lock-guarded spawn, and condition-var-based fair queueing.

### 3.1 `pool.py`

```python
from __future__ import annotations
import asyncio, collections, contextlib, time
from typing import AsyncIterator
import structlog
from suitest_mcp.client import McpSession, open_session
from suitest_mcp.errors import McpPoolExhausted
from suitest_mcp.models import McpProviderConfig

log = structlog.get_logger(__name__)


class _ProviderPool:
    def __init__(self, provider: McpProviderConfig) -> None:
        self.provider = provider
        self.idle: collections.deque[McpSession] = collections.deque()
        self.live = 0
        self.cond = asyncio.Condition()

    async def acquire(self, *, queue_timeout: float) -> McpSession:
        deadline = time.monotonic() + queue_timeout
        async with self.cond:
            while True:
                while self.idle:
                    sess = self.idle.popleft()
                    if time.monotonic() - sess.last_used_at > self.provider.idle_ttl_seconds:
                        await sess.cleanup(); self.live -= 1; continue
                    return sess
                if self.live < self.provider.max_sessions:
                    self.live += 1; break
                wait_time = deadline - time.monotonic()
                if wait_time <= 0:
                    raise McpPoolExhausted(f"pool exhausted for {self.provider.name}")
                try: await asyncio.wait_for(self.cond.wait(), timeout=wait_time)
                except TimeoutError as exc:
                    raise McpPoolExhausted(f"timed out on {self.provider.name}") from exc
        try: sess = await open_session(self.provider)
        except BaseException:
            async with self.cond: self.live -= 1; self.cond.notify_all()
            raise
        return sess

    async def release(self, sess: McpSession, *, recycle: bool = False) -> None:
        async with self.cond:
            cap = self.provider.config_json.get("max_requests_per_session", 1000)
            if recycle or sess.invocations >= cap:
                await sess.cleanup(); self.live -= 1
            else:
                sess.last_used_at = time.monotonic(); self.idle.append(sess)
            self.cond.notify()

    async def shutdown(self) -> None:
        async with self.cond:
            while self.idle:
                await self.idle.popleft().cleanup(); self.live -= 1


class McpPool:
    def __init__(self, *, queue_timeout_seconds: float = 30.0) -> None:
        self._pools: dict[str, _ProviderPool] = {}
        self._lock = asyncio.Lock()
        self.queue_timeout_seconds = queue_timeout_seconds

    async def _get_pool(self, provider: McpProviderConfig) -> _ProviderPool:
        async with self._lock:
            if provider.id not in self._pools:
                self._pools[provider.id] = _ProviderPool(provider)
            return self._pools[provider.id]

    @contextlib.asynccontextmanager
    async def acquire(self, provider: McpProviderConfig) -> AsyncIterator[McpSession]:
        pool = await self._get_pool(provider)
        sess = await pool.acquire(queue_timeout=self.queue_timeout_seconds)
        recycle = False
        try: yield sess
        except Exception: recycle = True; raise
        finally: await pool.release(sess, recycle=recycle)

    async def shutdown(self) -> None:
        async with self._lock:
            pools = list(self._pools.values()); self._pools.clear()
        for p in pools: await p.shutdown()
```

### 3.2 Tests — `tests/test_pool.py` (4 cases)

```python
import pytest
from suitest_mcp.errors import McpPoolExhausted
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.pool import McpPool

pytestmark = pytest.mark.asyncio

def _cfg(cmd, **k): return McpProviderConfig(id="p", workspace_id="w", name="mock",
    kind="test", transport=McpTransport.STDIO, command=cmd, **k)

async def test_pool_reuses_idle(mock_mcp_server):
    pool = McpPool()
    try:
        async with pool.acquire(_cfg(mock_mcp_server.command, max_sessions=1)) as s1:
            await s1.call_tool("echo", {"i": 1}, timeout_seconds=5)
        async with pool.acquire(_cfg(mock_mcp_server.command, max_sessions=1)) as s2:
            assert s2.invocations >= 1
    finally: await pool.shutdown()

async def test_pool_caps(mock_mcp_server):
    pool = McpPool(queue_timeout_seconds=0.5); cfg = _cfg(mock_mcp_server.command, max_sessions=2)
    try:
        async with pool.acquire(cfg), pool.acquire(cfg):
            with pytest.raises(McpPoolExhausted):
                async with pool.acquire(cfg): pass
    finally: await pool.shutdown()

async def test_pool_evicts_on_idle_ttl(mock_mcp_server):
    pool = McpPool(); cfg = _cfg(mock_mcp_server.command, max_sessions=1, idle_ttl_seconds=0)
    try:
        async with pool.acquire(cfg): pass
        async with pool.acquire(cfg) as s2: assert s2.invocations == 0
    finally: await pool.shutdown()

async def test_pool_recycles_on_exception(mock_mcp_server):
    pool = McpPool(); cfg = _cfg(mock_mcp_server.command, max_sessions=1)
    try:
        with pytest.raises(RuntimeError):
            async with pool.acquire(cfg): raise RuntimeError("boom")
        async with pool.acquire(cfg) as s2: assert s2.invocations == 0
    finally: await pool.shutdown()
```

### Steps

- [ ] **3.1** Write `pool.py`
- [ ] **3.2** Write `tests/test_pool.py` (4 cases)
- [ ] **3.3** Tests red → impl → green
- [ ] **3.4** mypy strict pass
- [ ] **3.5** Commit: `feat(mcp): connection pool with LRU + TTL + per-provider cap`

---

## Task 4: Routing table + registry

Bundled providers load at import-time; DB-stored custom providers loaded per workspace via the M1a `McpProviderRepository`. Routing resolves `target_kind` → primary + fallback, with workspace overrides in `workspace_capabilities.features_json.routing_overrides`.

### 4.1 `providers/builtin_specs.py`

```python
from suitest_mcp.models import McpProviderConfig, McpTransport

BUILTIN_SPECS: list[McpProviderConfig] = [
    McpProviderConfig(id="builtin:api-http-mcp", workspace_id="_builtin_", name="api-http-mcp",
        kind="http", transport=McpTransport.IN_PROCESS, endpoint="in-process://api-http",
        config_json={"tools": ["http.request", "http.assert_status", "http.assert_json_path", "http.assert_header"]},
        is_default_for_target={"BE_REST": True}, max_sessions=8),
    McpProviderConfig(id="builtin:playwright-mcp", workspace_id="_builtin_", name="playwright-mcp",
        kind="browser", transport=McpTransport.STDIO, command=["npx", "-y", "@playwright/mcp@latest"],
        config_json={"version_pin": "@playwright/mcp@latest"},
        is_default_for_target={"FE_WEB": True}, max_sessions=2, spawn_timeout_seconds=30.0),
    McpProviderConfig(id="builtin:postgres-mcp", workspace_id="_builtin_", name="postgres-mcp",
        kind="db", transport=McpTransport.IN_PROCESS, endpoint="in-process://postgres",
        config_json={"tools": ["db.query", "db.exec", "db.insert", "db.delete",
                               "db.assert_row_exists", "db.assert_row_count"]},
        is_default_for_target={"DATA": True}, max_sessions=4),
]
```

### 4.2 `registry.py`

```python
from __future__ import annotations
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.mcp_provider import McpProviderRepository
from suitest_mcp.errors import McpProviderUnavailable
from suitest_mcp.models import McpProviderConfig
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS

log = structlog.get_logger(__name__)


class McpRegistry:
    def __init__(self) -> None:
        self._by_workspace: dict[str, dict[str, McpProviderConfig]] = {}

    async def load_for_workspace(self, session: AsyncSession, workspace_id: str) -> None:
        rows = await McpProviderRepository(session).list_for_workspace(workspace_id)
        providers: dict[str, McpProviderConfig] = {
            spec.name: spec.model_copy(update={"workspace_id": workspace_id})
            for spec in BUILTIN_SPECS
        }
        for row in rows:
            providers[row.name] = McpProviderConfig.model_validate(row)
        self._by_workspace[workspace_id] = providers
        log.info("mcp.registry.loaded", workspace_id=workspace_id, count=len(providers))

    def get(self, workspace_id: str, name: str) -> McpProviderConfig:
        try: return self._by_workspace[workspace_id][name]
        except KeyError as exc:
            raise McpProviderUnavailable(f"unknown provider {name!r} for ws {workspace_id}") from exc

    def list_for_workspace(self, workspace_id: str) -> list[McpProviderConfig]:
        return list(self._by_workspace.get(workspace_id, {}).values())
```

### 4.3 `routing.py`

```python
from __future__ import annotations
from typing import Any
from suitest_shared.domain.enums import TargetKind
from suitest_mcp.errors import McpProviderUnavailable
from suitest_mcp.models import McpProviderConfig
from suitest_mcp.registry import McpRegistry

DEFAULT_ROUTING: dict[TargetKind, tuple[str, str | None]] = {
    TargetKind.BE_REST:    ("api-http-mcp", None),
    TargetKind.BE_GRAPHQL: ("api-http-mcp", None),  # graphql-mcp in M2
    TargetKind.BE_GRPC:    ("api-http-mcp", None),  # grpc-mcp in M2
    TargetKind.FE_WEB:     ("playwright-mcp", None),
    TargetKind.FE_MOBILE:  ("playwright-mcp", None),  # appium-mcp v2
    TargetKind.DATA:       ("postgres-mcp", None),
    TargetKind.INFRA:      ("api-http-mcp", None),  # k8s-mcp M2
    TargetKind.CUSTOM:     ("", None),
}


def resolve_provider(registry: McpRegistry, *, workspace_id: str, target_kind: TargetKind,
                     explicit: str | None, overrides: dict[str, Any] | None = None) -> McpProviderConfig:
    if explicit:
        return registry.get(workspace_id, explicit)
    overrides = overrides or {}
    if target_kind.value in overrides:
        rule = overrides[target_kind.value]
        if rule.get("primary"):
            try: return registry.get(workspace_id, rule["primary"])
            except McpProviderUnavailable:
                if rule.get("fallback"):
                    return registry.get(workspace_id, rule["fallback"])
    primary, fallback = DEFAULT_ROUTING.get(target_kind, ("", None))
    if not primary:
        raise McpProviderUnavailable(f"no default routing for {target_kind}")
    try: return registry.get(workspace_id, primary)
    except McpProviderUnavailable:
        if fallback: return registry.get(workspace_id, fallback)
        raise
```

### 4.4 Tests — `tests/test_registry_routing.py` (6 cases)

Test matrix: registry returns bundled provider; default FE_WEB routes to playwright-mcp; explicit step provider wins; workspace override wins; override falls back when primary missing; no provider raises `McpProviderUnavailable`.

### Steps

- [ ] **4.1** Write `providers/builtin_specs.py`
- [ ] **4.2** Write `registry.py` using existing M1a `McpProviderRepository`
- [ ] **4.3** Write `routing.py`
- [ ] **4.4** Write `tests/test_registry_routing.py` (6 cases enumerated above)
- [ ] **4.5** Tests green; mypy strict pass
- [ ] **4.6** Commit: `feat(mcp): registry + routing with workspace overrides + fallback`

---

## Task 5: Health monitoring

Background asyncio task pings every registered provider every 60s with `list_tools()` smoke. Persists `mcp_providers.health_status` + `last_health_at`. Publishes `mcp.provider.health` on Redis `workspace:<id>` channel on state transitions. Auto-disables routing if DOWN >5 min.

### 5.1 `health.py`

```python
from __future__ import annotations
import asyncio, json, time
from datetime import datetime, timezone
import redis.asyncio as redis_async, structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_db.repositories.mcp_provider import McpProviderRepository
from suitest_mcp.client import open_session
from suitest_mcp.errors import McpError
from suitest_mcp.models import McpHealthState, McpHealthStatus, McpProviderConfig
from suitest_mcp.registry import McpRegistry

log = structlog.get_logger(__name__)
PROBE_INTERVAL_SECONDS = 60
PROBE_TIMEOUT_SECONDS = 5.0
AUTO_DISABLE_AFTER_SECONDS = 300


class HealthMonitor:
    def __init__(self, *, registry: McpRegistry,
                 session_factory: async_sessionmaker[AsyncSession],
                 redis_client: redis_async.Redis) -> None:
        self.registry = registry; self.session_factory = session_factory; self.redis = redis_client
        self._task: asyncio.Task[None] | None = None
        self._last_ok: dict[str, float] = {}
        self._last_state: dict[str, McpHealthState] = {}
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="mcp-health")

    async def stop(self) -> None:
        self._stop.set()
        if self._task: await self._task; self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try: await self._probe_all()
            except Exception: log.exception("mcp.health.loop_error")
            try: await asyncio.wait_for(self._stop.wait(), timeout=PROBE_INTERVAL_SECONDS)
            except TimeoutError: pass

    async def _probe_all(self) -> None:
        for workspace_id in list(self.registry._by_workspace.keys()):
            for provider in self.registry.list_for_workspace(workspace_id):
                status = await self._probe(provider)
                await self._persist(provider, status)
                await self._maybe_publish(workspace_id, provider, status)

    async def _probe(self, provider: McpProviderConfig) -> McpHealthStatus:
        start = time.perf_counter()
        try:
            sess = await asyncio.wait_for(open_session(provider), timeout=PROBE_TIMEOUT_SECONDS)
            try:
                tools = await sess.list_tools()
                latency_ms = int((time.perf_counter() - start) * 1000)
                state = McpHealthState.OK if tools else McpHealthState.DEGRADED
                return McpHealthStatus(provider_id=provider.id, name=provider.name, state=state,
                                       latency_ms=latency_ms, checked_at=datetime.now(timezone.utc))
            finally: await sess.cleanup()
        except (McpError, TimeoutError, Exception) as exc:
            return McpHealthStatus(provider_id=provider.id, name=provider.name,
                                   state=McpHealthState.DOWN,
                                   latency_ms=int((time.perf_counter() - start) * 1000),
                                   error=str(exc), checked_at=datetime.now(timezone.utc))

    async def _persist(self, provider: McpProviderConfig, status: McpHealthStatus) -> None:
        if provider.id.startswith("builtin:"): return  # in-memory only
        async with self.session_factory() as session:
            await McpProviderRepository(session).update_health(
                provider.id, status.state.value, status.checked_at)
            await session.commit()

    async def _maybe_publish(self, workspace_id: str, provider: McpProviderConfig,
                             status: McpHealthStatus) -> None:
        prev = self._last_state.get(provider.id)
        if status.state == McpHealthState.OK:
            self._last_ok[provider.id] = time.monotonic()
        if prev != status.state:
            self._last_state[provider.id] = status.state
            await self.redis.publish(f"workspace:{workspace_id}", json.dumps({
                "event": "mcp.provider.health",
                "data": {"providerId": provider.id, "name": provider.name,
                         "status": status.state.value, "latencyMs": status.latency_ms,
                         "error": status.error},
            }))

    def is_routable(self, provider_id: str) -> bool:
        state = self._last_state.get(provider_id, McpHealthState.UNKNOWN)
        if state == McpHealthState.DOWN:
            last_ok = self._last_ok.get(provider_id)
            if last_ok is None or (time.monotonic() - last_ok) > AUTO_DISABLE_AFTER_SECONDS:
                return False
        return True
```

### 5.2 Tests — `tests/test_health.py` (4 cases)

Probe returns OK against mock server; probe returns DOWN against `/bin/false` spawn (forced fail); publishes only on state transition (not on every probe); `is_routable()` returns False past auto-disable threshold.

### Steps

- [ ] **5.1** Write `health.py`
- [ ] **5.2** Add `fake_redis` (in-memory pub/sub stub) and `db_session_factory` fixtures to `tests/conftest.py`
- [ ] **5.3** Verify M1a `McpProviderRepository.update_health(id, status, checked_at)` exists; add migration column `last_health_at` if missing
- [ ] **5.4** Write tests (4 cases)
- [ ] **5.5** Tests green; mypy strict pass
- [ ] **5.6** Commit: `feat(mcp): health monitor with 60s probe + redis pubsub + auto-disable`

---

## Task 6: Bundled provider — api-http-mcp (in-process)

Built-in MCP server with `http.*` tools running in-process for zero subprocess overhead. Uses the SDK's connected memory streams to bridge a `Server` instance and a `ClientSession`.

### 6.1 `bundled/in_process_runtime.py`

```python
from __future__ import annotations
import contextlib
from typing import AsyncIterator
import anyio
from mcp.server import Server
from mcp.shared.memory import create_connected_server_and_client_streams
from suitest_mcp.bundled.api_http import build_api_http_server
from suitest_mcp.bundled.postgres import build_postgres_server
from suitest_mcp.models import McpProviderConfig

_BUILDERS = {"api-http-mcp": build_api_http_server, "postgres-mcp": build_postgres_server}


@contextlib.asynccontextmanager
async def in_process_client(provider: McpProviderConfig) -> AsyncIterator[tuple]:
    builder = _BUILDERS.get(provider.name)
    if builder is None: raise ValueError(f"no in-process builder for {provider.name}")
    server: Server = builder(provider)
    async with create_connected_server_and_client_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, server_streams[0], server_streams[1],
                          server.create_initialization_options())
            yield client_streams
            tg.cancel_scope.cancel()
```

### 6.2 `bundled/api_http.py`

```python
from __future__ import annotations
import json, re
from typing import Any
import httpx
from jsonpath_ng.ext import parse as jsonpath_parse
from mcp.server import Server
from mcp.types import TextContent, Tool
from suitest_mcp.models import McpProviderConfig


def build_api_http_server(provider: McpProviderConfig) -> Server:
    app: Server = Server("api-http-mcp")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="http.request", description="Execute HTTP request",
                 inputSchema={"type":"object","required":["method","url"],
                              "properties":{"method":{"type":"string"},"url":{"type":"string"},
                                            "headers":{"type":"object"},"json":{"type":"object"},
                                            "body":{"type":"string"},"timeout_seconds":{"type":"number"}}}),
            Tool(name="http.assert_status", description="Assert status code",
                 inputSchema={"type":"object","required":["result","equals"],
                              "properties":{"result":{"type":"object"},"equals":{"type":"integer"}}}),
            Tool(name="http.assert_json_path", description="Assert jsonpath value",
                 inputSchema={"type":"object","required":["result","path"],
                              "properties":{"result":{"type":"object"},"path":{"type":"string"},
                                            "equals":{},"matches":{"type":"string"}}}),
            Tool(name="http.assert_header", description="Assert response header",
                 inputSchema={"type":"object","required":["result","name","equals"],
                              "properties":{"result":{"type":"object"},"name":{"type":"string"},
                                            "equals":{"type":"string"}}}),
        ]

    @app.call_tool()
    async def call(name: str, args: dict[str, Any]) -> list[TextContent]:
        if name == "http.request":          return await _do_request(args)
        if name == "http.assert_status":    return _assert_status(args)
        if name == "http.assert_json_path": return _assert_jsonpath(args)
        if name == "http.assert_header":    return _assert_header(args)
        raise ValueError(f"unknown tool {name}")

    return app


async def _do_request(args: dict[str, Any]) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=float(args.get("timeout_seconds", 30)),
                                  follow_redirects=False) as c:
        r = await c.request(args["method"].upper(), args["url"], headers=args.get("headers"),
                            json=args.get("json"), content=args.get("body"))
        try: body_json: Any = r.json()
        except Exception: body_json = None
        return [TextContent(type="text", text=json.dumps({
            "status": r.status_code, "headers": dict(r.headers),
            "body_text": r.text, "body_json": body_json,
            "elapsed_ms": int(r.elapsed.total_seconds() * 1000), "url": str(r.url),
        }))]


def _assert_status(args):
    if int(args["result"]["status"]) != int(args["equals"]):
        raise AssertionError(f"status {args['result']['status']} != {args['equals']}")
    return [TextContent(type="text", text="ok")]


def _assert_jsonpath(args):
    body = args["result"].get("body_json")
    if body is None: raise AssertionError("body is not JSON")
    matches = [m.value for m in jsonpath_parse(args["path"]).find(body)]
    if not matches: raise AssertionError(f"jsonpath {args['path']} no match")
    actual = matches[0]
    if "equals" in args and actual != args["equals"]:
        raise AssertionError(f"{actual!r} != {args['equals']!r}")
    if "matches" in args and not re.match(args["matches"], str(actual)):
        raise AssertionError(f"{actual!r} !~ {args['matches']!r}")
    return [TextContent(type="text", text=json.dumps({"matched": actual}))]


def _assert_header(args):
    found = next((v for k, v in args["result"].get("headers", {}).items()
                  if k.lower() == args["name"].lower()), None)
    if found != args["equals"]:
        raise AssertionError(f"header {args['name']}: {found!r} != {args['equals']!r}")
    return [TextContent(type="text", text="ok")]
```

### 6.3 Tests — `tests/test_bundled_api_http.py` (4 cases, integration via testcontainers `kennethreitz/httpbin`)

Cases: GET returns 200 + payload; `http.assert_status` matches; `http.assert_json_path` against `httpbin/json`; status mismatch raises `McpToolFailed`.

### Steps

- [ ] **6.1** Add `jsonpath-ng` to `packages/mcp/pyproject.toml`
- [ ] **6.2** Write `in_process_runtime.py` + `bundled/api_http.py`
- [ ] **6.3** Write integration tests against testcontainers httpbin (4 cases)
- [ ] **6.4** Tests green; mypy strict pass
- [ ] **6.5** Commit: `feat(mcp): bundled api-http-mcp with request + status/jsonpath/header assertions`

---

## Task 7: Bundled provider — playwright-mcp

Subprocess wrapper for upstream `@playwright/mcp`. The wrapper module ships only metadata; the Node package is installed in the Docker image at build time.

### 7.1 `bundled/playwright.py`

```python
"""Playwright-MCP provider metadata.

Spawned as subprocess via `npx -y @playwright/mcp@latest`. The bundled spec
lives in `providers/builtin_specs.py`. Live tool catalog comes from
`session.list_tools()` at runtime; the list below is informational only.

Docker build (apps/runner Dockerfile + apps/api Dockerfile):
    RUN npm install -g @playwright/mcp@1.0.0 \\
     && npx playwright install --with-deps chromium
"""

from __future__ import annotations
from suitest_mcp.models import McpToolSchema

DECLARED_TOOLS: list[McpToolSchema] = [
    McpToolSchema(name="browser.navigate"),
    McpToolSchema(name="browser.click"),
    McpToolSchema(name="browser.type"),
    McpToolSchema(name="browser.fill_form"),
    McpToolSchema(name="browser.screenshot"),
    McpToolSchema(name="browser.evaluate"),
    McpToolSchema(name="browser.wait_for"),
    McpToolSchema(name="browser.get_dom"),
    McpToolSchema(name="browser.assert_text"),
    McpToolSchema(name="browser.start_recording"),  # M2
    McpToolSchema(name="browser.stop_recording"),   # M2
    McpToolSchema(name="browser.network_logs"),
]
```

### 7.2 Test fixture HTML — `tests/fixtures/test_page.html`

```html
<!doctype html><html><head><title>Suitest Test</title></head>
<body><h1 id="hero">Hello Suitest</h1><input id="q" /><button id="go">Go</button></body></html>
```

### 7.3 Tests — `tests/test_bundled_playwright.py`

```python
import pytest
from pathlib import Path
from testcontainers.core.container import DockerContainer
from suitest_mcp.client import open_session
from suitest_mcp.providers.builtin_specs import BUILTIN_SPECS

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def test_page_url():
    with DockerContainer("nginx:1.27-alpine").with_exposed_ports(80) \
            .with_volume_mapping(str(FIXTURE_DIR), "/usr/share/nginx/html") as c:
        yield f"http://{c.get_container_host_ip()}:{c.get_exposed_port(80)}/test_page.html"


def _cfg(): 
    spec = next(s for s in BUILTIN_SPECS if s.name == "playwright-mcp")
    return spec.model_copy(update={"workspace_id": "ws"})


async def test_playwright_navigate_screenshot_dom(test_page_url):
    sess = await open_session(_cfg())
    try:
        await sess.call_tool("browser.navigate", {"url": test_page_url}, timeout_seconds=30)
        shot = await sess.call_tool("browser.screenshot", {}, timeout_seconds=30)
        assert shot.ok
        text = await sess.call_tool("browser.get_dom", {"selector": "#hero"}, timeout_seconds=10)
        assert "Hello Suitest" in text.stdout
    finally: await sess.cleanup()
```

### Steps

- [ ] **7.1** Write `bundled/playwright.py` metadata
- [ ] **7.2** Add HTML fixture
- [ ] **7.3** Write integration test (marked `@pytest.mark.integration`, skipped by default unless `--integration`)
- [ ] **7.4** Update `docs/DEPLOYMENT.md` with Docker bundling instructions (`npm install @playwright/mcp` + `npx playwright install`)
- [ ] **7.5** Commit: `feat(mcp): bundled playwright-mcp metadata + integration smoke`

---

## Task 8: Bundled provider — postgres-mcp (in-process)

In-process Python MCP wrapping psycopg async. Workspace DSN comes from `provider.config_json["dsn"]`. Decision: in-process (no Node dep) for easier air-gapped deploy.

### 8.1 `bundled/postgres.py`

```python
from __future__ import annotations
import json
from typing import Any
import psycopg, psycopg_pool
from mcp.server import Server
from mcp.types import TextContent, Tool
from suitest_mcp.models import McpProviderConfig

_POOLS: dict[str, psycopg_pool.AsyncConnectionPool] = {}


async def _pool_for(provider: McpProviderConfig) -> psycopg_pool.AsyncConnectionPool:
    dsn = provider.config_json.get("dsn") or provider.endpoint
    if not dsn or dsn.startswith("in-process://"):
        raise RuntimeError("postgres-mcp requires config_json.dsn")
    key = f"{provider.id}:{dsn}"
    if key not in _POOLS:
        _POOLS[key] = psycopg_pool.AsyncConnectionPool(dsn, min_size=0, max_size=4, open=False)
        await _POOLS[key].open()
    return _POOLS[key]


def build_postgres_server(provider: McpProviderConfig) -> Server:
    app: Server = Server("postgres-mcp")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        S = {"type": "string"}; O = {"type": "object"}; A = {"type": "array"}
        return [
            Tool(name="db.query",    description="SELECT rows",
                 inputSchema={"type":"object","required":["sql"],"properties":{"sql":S,"params":A}}),
            Tool(name="db.exec",     description="DML/DDL",
                 inputSchema={"type":"object","required":["sql"],"properties":{"sql":S,"params":A}}),
            Tool(name="db.insert",   description="Insert row",
                 inputSchema={"type":"object","required":["table","row"],"properties":{"table":S,"row":O}}),
            Tool(name="db.delete",   description="Delete rows",
                 inputSchema={"type":"object","required":["table","where"],"properties":{"table":S,"where":O}}),
            Tool(name="db.assert_row_exists", description="Assert >=1 row",
                 inputSchema={"type":"object","required":["table","where"],"properties":{"table":S,"where":O}}),
            Tool(name="db.assert_row_count",  description="Assert exact count",
                 inputSchema={"type":"object","required":["table","where","count"],
                              "properties":{"table":S,"where":O,"count":{"type":"integer"}}}),
        ]

    @app.call_tool()
    async def call(name: str, args: dict[str, Any]) -> list[TextContent]:
        pool = await _pool_for(provider)
        async with pool.connection() as conn:
            if name == "db.query":
                rows = await _query(conn, args["sql"], args.get("params"))
                return [TextContent(type="text", text=json.dumps(rows, default=str))]
            if name == "db.exec":
                return [TextContent(type="text", text=json.dumps(
                    {"affected": await _exec(conn, args["sql"], args.get("params"))}))]
            if name == "db.insert":
                sql, params = _insert(args["table"], args["row"])
                return [TextContent(type="text", text=json.dumps({"affected": await _exec(conn, sql, params)}))]
            if name == "db.delete":
                sql, params = _delete(args["table"], args["where"])
                return [TextContent(type="text", text=json.dumps({"affected": await _exec(conn, sql, params)}))]
            if name == "db.assert_row_exists":
                sql, params = _count(args["table"], args["where"])
                rows = await _query(conn, sql, params)
                if rows[0]["count"] < 1:
                    raise AssertionError(f"no rows in {args['table']} where {args['where']}")
                return [TextContent(type="text", text="ok")]
            if name == "db.assert_row_count":
                sql, params = _count(args["table"], args["where"])
                rows = await _query(conn, sql, params)
                if rows[0]["count"] != args["count"]:
                    raise AssertionError(f"count {rows[0]['count']} != {args['count']}")
                return [TextContent(type="text", text="ok")]
        raise ValueError(f"unknown tool {name}")
    return app


async def _query(conn, sql, params):
    async with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        cols = [c.name for c in (cur.description or [])]
        return [dict(zip(cols, row)) for row in await cur.fetchall()]

async def _exec(conn, sql, params):
    async with conn.cursor() as cur:
        await cur.execute(sql, params or [])
        return cur.rowcount

def _insert(table, row):
    cols = ",".join(row); ph = ",".join(["%s"] * len(row))
    return f"INSERT INTO {table} ({cols}) VALUES ({ph})", list(row.values())

def _delete(table, where):
    clauses = " AND ".join(f"{k}=%s" for k in where)
    return f"DELETE FROM {table} WHERE {clauses}", list(where.values())

def _count(table, where):
    if not where: return f"SELECT COUNT(*) AS count FROM {table}", []
    clauses = " AND ".join(f"{k}=%s" for k in where)
    return f"SELECT COUNT(*) AS count FROM {table} WHERE {clauses}", list(where.values())
```

### 8.2 Tests — `tests/test_bundled_postgres.py` (3 cases, testcontainers postgres)

Cases: `db.exec` CREATE + `db.insert` + `db.query` round-trip; `db.assert_row_exists` passes / fails appropriately; `db.assert_row_count` exact match.

### Steps

- [ ] **8.1** Add `psycopg[binary]`, `psycopg-pool` to `packages/mcp/pyproject.toml`
- [ ] **8.2** Write `bundled/postgres.py`
- [ ] **8.3** Write integration tests (3 cases)
- [ ] **8.4** Tests green; mypy strict pass
- [ ] **8.5** Commit: `feat(mcp): bundled postgres-mcp in-process with query/assert tools`

---

## Task 9: Invoker + telemetry

`McpInvoker.invoke(...)` combines pool + routing + audit + Redis events. Single entry point for runner (and later, agent).

### 9.1 `invoker.py`

```python
from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass
from typing import Any
import redis.asyncio as redis_async, structlog
from opentelemetry import trace
from suitest_db.audit import write_audit
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.health import HealthMonitor
from suitest_mcp.models import McpToolResult
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_mcp.routing import resolve_provider
from suitest_shared.domain.enums import TargetKind

log = structlog.get_logger(__name__)
tracer = trace.get_tracer("suitest.mcp.invoker")


@dataclass
class InvokeContext:
    workspace_id: str
    run_id: str | None
    step_id: str | None
    actor_user_id: str | None
    target_kind: TargetKind
    routing_overrides: dict[str, Any] | None = None


class McpInvoker:
    def __init__(self, *, registry: McpRegistry, pool: McpPool,
                 health: HealthMonitor | None, redis_client: redis_async.Redis,
                 audit_session_factory) -> None:
        self.registry = registry; self.pool = pool; self.health = health
        self.redis = redis_client; self.audit_session_factory = audit_session_factory

    async def invoke(self, *, explicit_provider: str | None, tool: str,
                     arguments: dict[str, Any], ctx: InvokeContext) -> McpToolResult:
        provider = resolve_provider(self.registry, workspace_id=ctx.workspace_id,
                                    target_kind=ctx.target_kind, explicit=explicit_provider,
                                    overrides=ctx.routing_overrides)
        if self.health and not self.health.is_routable(provider.id):
            raise McpToolFailed(f"provider {provider.name} auto-disabled (DOWN >threshold)")
        arg_hash = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()
        await self._publish(ctx, "mcp.tool.start", {"provider": provider.name, "tool": tool})

        start = time.perf_counter()
        with tracer.start_as_current_span("mcp.invoke") as span:
            for k, v in (("mcp.provider", provider.name), ("mcp.tool", tool),
                         ("suitest.workspace_id", ctx.workspace_id),
                         ("suitest.run_id", ctx.run_id or ""),
                         ("suitest.step_id", ctx.step_id or "")):
                span.set_attribute(k, v)
            try:
                async with self.pool.acquire(provider) as sess:
                    result = await sess.call_tool(tool, arguments,
                                                  timeout_seconds=provider.call_timeout_seconds)
                outcome = "ok"
            except McpToolTimeout as exc:
                span.record_exception(exc)
                await self._finalize(ctx, provider, tool, arg_hash, "timeout",
                                     int((time.perf_counter() - start) * 1000), str(exc))
                raise
            except McpToolFailed as exc:
                span.record_exception(exc)
                await self._finalize(ctx, provider, tool, arg_hash, "failed",
                                     int((time.perf_counter() - start) * 1000), str(exc))
                raise

        await self._finalize(ctx, provider, tool, arg_hash, outcome, result.duration_ms, None)
        return result

    async def _publish(self, ctx: InvokeContext, event: str, data: dict[str, Any]) -> None:
        if not ctx.run_id: return
        await self.redis.publish(f"run:{ctx.run_id}", json.dumps({
            "event": event,
            "data": {"runId": ctx.run_id, "stepId": ctx.step_id, **data},
        }))

    async def _finalize(self, ctx, provider, tool, arg_hash, outcome, duration_ms, error):
        await self._publish(ctx, "mcp.tool.end", {
            "provider": provider.name, "tool": tool, "outcome": outcome,
            "durationMs": duration_ms, "error": error,
        })
        async with self.audit_session_factory() as s:
            await write_audit(s, workspace_id=ctx.workspace_id, user_id=ctx.actor_user_id,
                action="mcp.invoke", resource_type="mcp_provider", resource_id=provider.name,
                metadata={"tool": tool, "arg_hash": arg_hash, "outcome": outcome,
                          "duration_ms": duration_ms, "run_id": ctx.run_id, "step_id": ctx.step_id})
            await s.commit()
```

### 9.2 Tests — `tests/test_invoker.py`

```python
import json, pytest
from suitest_mcp.invoker import InvokeContext, McpInvoker
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import TargetKind

pytestmark = pytest.mark.asyncio


async def test_invoker_emits_start_end_and_returns(mock_mcp_server, fake_redis, db_session_factory):
    reg = McpRegistry()
    reg._by_workspace = {"ws": {"mock": McpProviderConfig(id="b:mock", workspace_id="ws",
        name="mock", kind="test", transport=McpTransport.STDIO,
        command=mock_mcp_server.command)}}
    invoker = McpInvoker(registry=reg, pool=McpPool(), health=None,
                        redis_client=fake_redis, audit_session_factory=db_session_factory)
    ctx = InvokeContext(workspace_id="ws", run_id="r1", step_id="s1",
                        actor_user_id="u1", target_kind=TargetKind.CUSTOM)
    r = await invoker.invoke(explicit_provider="mock", tool="echo",
                             arguments={"x": 1}, ctx=ctx)
    assert r.ok
    events = [json.loads(m)["event"] for m in fake_redis.published["run:r1"]]
    assert events == ["mcp.tool.start", "mcp.tool.end"]
```

### Steps

- [ ] **9.1** Write `invoker.py`
- [ ] **9.2** Ensure `packages/db/audit.py::write_audit` exists (from M1a); add minimal version if missing
- [ ] **9.3** Write `tests/test_invoker.py`
- [ ] **9.4** Tests green; mypy strict pass
- [ ] **9.5** Commit: `feat(mcp): invoker orchestrating pool + routing + audit + redis events`

---

## Task 10: `apps/runner` scaffolding

ARQ worker entrypoint. Single queue `suitest:runs`. Concurrency = 4. Retries = 2.

### 10.1 `apps/runner/pyproject.toml`

```toml
[project]
name = "suitest-runner"
version = "0.4.0"
requires-python = ">=3.12"
dependencies = [
  "arq>=0.26", "redis[hiredis]>=5.0", "aioboto3>=13.0",
  "structlog>=24.1", "opentelemetry-instrumentation-asgi>=0.46b0",
  "pydantic-settings>=2.3",
  "suitest-mcp", "suitest-db", "suitest-shared", "suitest-core",
]

[project.optional-dependencies]
test = ["pytest>=8.2", "pytest-asyncio>=0.23", "moto[s3]>=5.0",
        "testcontainers[postgres,redis,minio]>=4.5"]

[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/suitest_runner"]

[tool.pytest.ini_options]
asyncio_mode = "strict"
```

### 10.2 `settings.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUITEST_", env_file=".env", extra="ignore")
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "suitest-artifacts"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    runner_concurrency: int = 4
    runner_max_retries: int = 2
    runner_job_timeout_seconds: int = 1800
    mcp_max_sessions_per_workspace: int = 16
    mcp_queue_timeout_seconds: float = 30.0
```

### 10.3 `worker.py`

```python
from __future__ import annotations
from typing import Any
import redis.asyncio as redis_async, structlog
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from suitest_mcp.health import HealthMonitor
from suitest_mcp.invoker import McpInvoker
from suitest_mcp.pool import McpPool
from suitest_mcp.registry import McpRegistry
from suitest_runner.settings import RunnerSettings
from suitest_runner.jobs.run_test_case import run_test_case

log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    s = RunnerSettings()
    ctx["settings"] = s
    engine = create_async_engine(s.database_url, pool_pre_ping=True)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    ctx["redis"] = redis_async.from_url(s.redis_url, decode_responses=False)
    ctx["registry"] = McpRegistry()
    ctx["pool"] = McpPool(queue_timeout_seconds=s.mcp_queue_timeout_seconds)
    ctx["health"] = HealthMonitor(registry=ctx["registry"],
        session_factory=ctx["session_factory"], redis_client=ctx["redis"])
    await ctx["health"].start()
    ctx["invoker"] = McpInvoker(registry=ctx["registry"], pool=ctx["pool"],
        health=ctx["health"], redis_client=ctx["redis"],
        audit_session_factory=ctx["session_factory"])
    log.info("runner.started", concurrency=s.runner_concurrency)


async def shutdown(ctx: dict[str, Any]) -> None:
    if ctx.get("health"): await ctx["health"].stop()
    if ctx.get("pool"): await ctx["pool"].shutdown()
    if ctx.get("redis"): await ctx["redis"].close()
    if ctx.get("engine"): await ctx["engine"].dispose()


class WorkerSettings:
    functions = [run_test_case]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(RunnerSettings().redis_url)
    queue_name = "suitest:runs"
    max_jobs = RunnerSettings().runner_concurrency
    job_timeout = RunnerSettings().runner_job_timeout_seconds
    max_tries = RunnerSettings().runner_max_retries + 1
    keep_result = 3600
```

### 10.4 `__main__.py`

```python
from arq import run_worker
from suitest_runner.worker import WorkerSettings
if __name__ == "__main__":
    run_worker(WorkerSettings)
```

### 10.5 `jobs/run_test_case.py` stub

```python
import structlog
log = structlog.get_logger(__name__)

async def run_test_case(ctx, run_id: str) -> dict:
    """Job entrypoint. Full impl in Task 12."""
    log.info("runner.job.pickup", run_id=run_id)
    return {"run_id": run_id, "status": "stub"}
```

### 10.6 Test — `tests/test_worker_boot.py`

```python
import pytest
from arq import create_pool
from arq.connections import RedisSettings

pytestmark = pytest.mark.asyncio


async def test_worker_enqueue(redis_url):
    pool = await create_pool(RedisSettings.from_dsn(redis_url))
    job = await pool.enqueue_job("run_test_case", "r-1", _queue_name="suitest:runs")
    assert job is not None
```

### Steps

- [ ] **10.1** Create `apps/runner/pyproject.toml` + register in root uv workspace
- [ ] **10.2** Write `settings.py`, `worker.py`, `__main__.py`, `jobs/run_test_case.py` stub
- [ ] **10.3** Write `tests/test_worker_boot.py`
- [ ] **10.4** `uv run python -m suitest_runner` boots cleanly in dev compose
- [ ] **10.5** mypy strict pass
- [ ] **10.6** Commit: `feat(runner): scaffold ARQ worker with startup/shutdown lifecycle`

---

## Task 11: Step executor

Resolves provider, parses `TestStep.code` as JSON tool-call structure, invokes, returns `StepResult`.

**Decision — step code format:** `TestStep.code` is JSON of shape:

```json
{
  "tool": "browser.navigate",
  "arguments": { "url": "{{base_url}}/login" },
  "assertions": [
    { "tool": "browser.assert_text", "arguments": { "selector": "h1", "contains": "Welcome" } }
  ]
}
```

If `code` is empty: ZERO tier → `SKIP` with reason `NO_LLM_FOR_AGENTIC_STEP`. LOCAL/CLOUD → deferred to M3.

### 11.1 `executors/step_executor.py`

```python
from __future__ import annotations
import json, time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import structlog
from suitest_db.models.case import TestStep as TestStepRow
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.invoker import InvokeContext, McpInvoker
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import StepOutcome, TargetKind, Tier

log = structlog.get_logger(__name__)


@dataclass
class StepResult:
    outcome: StepOutcome
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    error_message: str | None
    mcp_result: McpToolResult | None


async def execute_step(*, invoker: McpInvoker, test_step: TestStepRow, run_id: str,
                      workspace_id: str, actor_user_id: str | None, tier: Tier,
                      routing_overrides: dict[str, Any] | None) -> StepResult:
    started = datetime.now(timezone.utc); t0 = time.perf_counter()

    def _done(outcome, msg=None, mcp=None, stdout="", stderr=""):
        return StepResult(outcome=outcome, started_at=started,
            completed_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            stdout=stdout, stderr=stderr, error_message=msg, mcp_result=mcp)

    if not test_step.code:
        if tier == Tier.ZERO:
            return _done(StepOutcome.SKIP, msg="NO_LLM_FOR_AGENTIC_STEP: step has no code")
        return _done(StepOutcome.SKIP, msg="TODO(M3): agentic translate not yet implemented")

    try: parsed = json.loads(test_step.code)
    except json.JSONDecodeError as exc:
        return _done(StepOutcome.ERROR, msg=f"INVALID_STEP_CODE: {exc}")

    ctx = InvokeContext(workspace_id=workspace_id, run_id=run_id, step_id=test_step.id,
        actor_user_id=actor_user_id, target_kind=TargetKind(test_step.target_kind),
        routing_overrides=routing_overrides)
    tool: str = parsed["tool"]
    arguments: dict[str, Any] = parsed.get("arguments", {})
    assertions: list[dict[str, Any]] = parsed.get("assertions", [])

    try:
        result = await invoker.invoke(explicit_provider=test_step.mcp_provider,
                                      tool=tool, arguments=arguments, ctx=ctx)
        for a in assertions:
            await invoker.invoke(explicit_provider=test_step.mcp_provider,
                tool=a["tool"],
                arguments={**a.get("arguments", {}),
                           "result": json.loads(result.stdout) if result.stdout.startswith("{") else {}},
                ctx=ctx)
        return _done(StepOutcome.PASS, mcp=result, stdout=result.stdout, stderr=result.stderr)
    except McpToolTimeout as exc:
        return _done(StepOutcome.ERROR, msg=f"MCP_TOOL_TIMEOUT: {exc}")
    except McpToolFailed as exc:
        return _done(StepOutcome.FAIL, msg=f"MCP_TOOL_FAILED: {exc}", stderr=str(exc))
    except Exception as exc:
        log.exception("step.executor.error", step_id=test_step.id)
        return _done(StepOutcome.ERROR, msg=f"INTERNAL: {exc}")
```

### 11.2 Tests — `tests/test_step_executor.py` (4 cases)

```python
import json, pytest
from unittest.mock import AsyncMock, MagicMock
from suitest_runner.executors.step_executor import execute_step
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import StepOutcome, TargetKind, Tier

pytestmark = pytest.mark.asyncio

def _step(code, provider="api-http-mcp", target=TargetKind.BE_REST):
    s = MagicMock(); s.id="s1"; s.code=code; s.mcp_provider=provider; s.target_kind=target.value
    return s

async def test_no_code_zero_skip():
    inv = MagicMock(); inv.invoke = AsyncMock()
    r = await execute_step(invoker=inv, test_step=_step(None), run_id="r", workspace_id="w",
        actor_user_id="u", tier=Tier.ZERO, routing_overrides=None)
    assert r.outcome == StepOutcome.SKIP and "NO_LLM_FOR_AGENTIC_STEP" in r.error_message

async def test_with_code_passes():
    inv = MagicMock()
    inv.invoke = AsyncMock(return_value=McpToolResult(ok=True, output={}, stdout="{}", duration_ms=42))
    code = json.dumps({"tool": "http.request", "arguments": {"method": "GET", "url": "x"}})
    r = await execute_step(invoker=inv, test_step=_step(code), run_id="r", workspace_id="w",
        actor_user_id="u", tier=Tier.ZERO, routing_overrides=None)
    assert r.outcome == StepOutcome.PASS

async def test_failed_assertion_marks_fail():
    inv = MagicMock(); inv.invoke = AsyncMock(side_effect=McpToolFailed("status 200 != 404"))
    code = json.dumps({"tool": "http.request", "arguments": {}})
    r = await execute_step(invoker=inv, test_step=_step(code), run_id="r", workspace_id="w",
        actor_user_id="u", tier=Tier.ZERO, routing_overrides=None)
    assert r.outcome == StepOutcome.FAIL

async def test_invalid_json_marks_error():
    inv = MagicMock(); inv.invoke = AsyncMock()
    r = await execute_step(invoker=inv, test_step=_step("not json"), run_id="r", workspace_id="w",
        actor_user_id="u", tier=Tier.ZERO, routing_overrides=None)
    assert r.outcome == StepOutcome.ERROR and "INVALID_STEP_CODE" in r.error_message
```

### Steps

- [ ] **11.1** Write `executors/step_executor.py`
- [ ] **11.2** Write `tests/test_step_executor.py` (4 cases)
- [ ] **11.3** Tests green; mypy strict pass
- [ ] **11.4** Commit: `feat(runner): step executor with code parse + outcome decision tree`

---

## Task 12: Run orchestrator

Full `run_test_case` job impl: load run + steps, dispatch per-step to executor, publish events, aggregate, update.

### 12.1 Expected repo helpers (verify exist in M1a, add if missing)

- `RunRepository.get_with_selection(run_id) -> (Run, list[(case_id, step_idx, TestStepRow)])`
- `RunRepository.update_status(run_id, status, **fields)`
- `RunStepRepository.create(...)`
- `WorkspaceCapabilityRepository.get(workspace_id)`

### 12.2 `jobs/run_test_case.py` (full)

```python
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from typing import Any
import structlog
from suitest_db.repositories.run import RunRepository
from suitest_db.repositories.run_step import RunStepRepository
from suitest_db.repositories.workspace_capability import WorkspaceCapabilityRepository
from suitest_runner.executors.step_executor import execute_step
from suitest_runner.artifacts import upload_artifacts
from suitest_shared.domain.enums import RunStatus, StepOutcome, Tier

log = structlog.get_logger(__name__)


async def run_test_case(ctx: dict[str, Any], run_id: str) -> dict[str, Any]:
    factory = ctx["session_factory"]; redis = ctx["redis"]
    invoker = ctx["invoker"]; registry = ctx["registry"]

    async with factory() as session:
        run_repo = RunRepository(session)
        run, selection = await run_repo.get_with_selection(run_id)
        if run is None:
            log.warning("runner.job.missing_run", run_id=run_id)
            return {"error": "RUN_NOT_FOUND"}
        workspace_id = run.project.workspace_id
        if workspace_id not in registry._by_workspace:
            await registry.load_for_workspace(session, workspace_id)
        capability = await WorkspaceCapabilityRepository(session).get(workspace_id)
        tier = Tier(capability.tier) if capability else Tier.ZERO
        overrides = (capability.features_json or {}).get("routing_overrides") if capability else None
        await run_repo.update_status(run_id, RunStatus.RUNNING,
            started_at=datetime.now(timezone.utc), tier_at_runtime=tier)
        await session.commit()

    await _publish(redis, run_id, "run.started", {"runId": run_id, "tier": tier.value})

    summary = {"total": 0, "passed": 0, "failed": 0, "errored": 0, "skipped": 0}
    t0 = time.perf_counter()

    for case_id, step_order, test_step in selection:
        summary["total"] += 1
        await _publish(redis, run_id, "run.step.started", {
            "runId": run_id, "stepIndex": step_order, "action": test_step.action,
            "mcpProvider": test_step.mcp_provider, "targetKind": test_step.target_kind,
        })

        result = await execute_step(invoker=invoker, test_step=test_step, run_id=run_id,
            workspace_id=workspace_id, actor_user_id=run.triggered_by, tier=tier,
            routing_overrides=overrides)

        async with factory() as session:
            run_step = await RunStepRepository(session).create(
                run_id=run_id, case_id=case_id, step_order=step_order,
                outcome=result.outcome, started_at=result.started_at,
                completed_at=result.completed_at, duration_ms=result.duration_ms,
                stdout=result.stdout, stderr=result.stderr,
                error_message=result.error_message)
            if result.mcp_result and result.mcp_result.artifacts:
                await upload_artifacts(session=session, ctx=ctx, run_id=run_id,
                    run_step_id=run_step.id, step_order=step_order,
                    artifacts=result.mcp_result.artifacts)
            await session.commit()

        await _publish(redis, run_id, "run.step.completed", {
            "runId": run_id, "stepIndex": step_order, "outcome": result.outcome.value,
            "durationMs": result.duration_ms, "error": result.error_message,
        })
        summary["passed" if result.outcome == StepOutcome.PASS else
                "failed" if result.outcome == StepOutcome.FAIL else
                "skipped" if result.outcome == StepOutcome.SKIP else "errored"] += 1

    duration_ms = int((time.perf_counter() - t0) * 1000)
    final_status = (RunStatus.FAIL if (summary["failed"] + summary["errored"]) > 0
                    else RunStatus.PASS)

    async with factory() as session:
        await RunRepository(session).update_status(run_id, final_status,
            completed_at=datetime.now(timezone.utc), duration_ms=duration_ms,
            total_steps=summary["total"], passed_steps=summary["passed"],
            failed_steps=summary["failed"])
        await session.commit()

    await _publish(redis, run_id, "run.completed", {
        "runId": run_id, "status": final_status.value,
        "totalSteps": summary["total"], "passedSteps": summary["passed"],
        "failedSteps": summary["failed"], "durationMs": duration_ms,
    })

    if summary["failed"] + summary["errored"] > 0:
        try:
            from suitest_api.services.defect_service import DefectService
            async with factory() as session:
                await DefectService(session).file_for_failed_run(run_id)
                await session.commit()
        except Exception as exc:
            log.warning("runner.defect.skip", reason=str(exc))

    return {"run_id": run_id, "status": final_status.value, **summary}


async def _publish(redis, run_id, event, data):
    await redis.publish(f"run:{run_id}", json.dumps({"event": event, "data": data}))
```

### 12.3 Tests — `tests/test_run_orchestrator.py` (4 cases)

Fixtures `stub_ctx_with_run` etc. live in `tests/conftest.py` and inject a fake invoker that returns PASS/FAIL deterministically by step order, a fake repo with in-memory selection, a fake redis with `published: dict[str, list[bytes]]`.

```python
import json, pytest
from suitest_runner.jobs.run_test_case import run_test_case

pytestmark = pytest.mark.asyncio


async def test_publishes_full_event_sequence_with_one_fail(stub_ctx_with_run):
    ctx, redis_stub = stub_ctx_with_run  # 2 PASS + 1 FAIL stub
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "FAIL"
    events = [json.loads(m)["event"] for m in redis_stub.published["run:run-1"]]
    assert events[0] == "run.started"
    assert events[-1] == "run.completed"
    assert events.count("run.step.started") == 3
    assert events.count("run.step.completed") == 3


async def test_persists_three_run_steps(stub_ctx_with_run):
    ctx, _ = stub_ctx_with_run
    await run_test_case(ctx, "run-1")
    assert len(ctx["_inserted_steps"]) == 3


async def test_all_pass_marks_run_pass(stub_ctx_all_pass):
    ctx, _ = stub_ctx_all_pass
    out = await run_test_case(ctx, "run-1")
    assert out["status"] == "PASS"
    assert out["passed"] == 3 and out["failed"] == 0


async def test_missing_run_returns_error(stub_ctx_empty):
    out = await run_test_case(stub_ctx_empty, "missing")
    assert out["error"] == "RUN_NOT_FOUND"
```

### Steps

- [ ] **12.1** Verify (or add) M1a repo helpers `RunRepository.get_with_selection/update_status`, `RunStepRepository.create`, `WorkspaceCapabilityRepository.get`
- [ ] **12.2** Write full `jobs/run_test_case.py`
- [ ] **12.3** Write fixtures + tests (4 cases)
- [ ] **12.4** Tests green; mypy strict pass
- [ ] **12.5** Commit: `feat(runner): run orchestrator with per-step execution + event stream + aggregation`

---

## Task 13: Artifact capture + MinIO upload

After each step, MCP artifacts (screenshots/HAR/console logs) upload to MinIO; `artifacts` table receives row with `s3://bucket/runs/.../kind/filename` URL.

### 13.1 `artifacts.py`

```python
from __future__ import annotations
import mimetypes
from typing import Any, Iterable
import aioboto3, structlog
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.repositories.artifact import ArtifactRepository
from suitest_mcp.models import McpArtifact
from suitest_shared.domain.enums import ArtifactKind

log = structlog.get_logger(__name__)


async def upload_artifacts(*, session: AsyncSession, ctx: dict[str, Any], run_id: str,
                          run_step_id: str, step_order: int,
                          artifacts: Iterable[McpArtifact]) -> None:
    s = ctx["settings"]
    repo = ArtifactRepository(session)
    async with aioboto3.Session().client("s3", endpoint_url=s.s3_endpoint,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key) as client:
        for art in artifacts:
            key = f"runs/{run_id}/{step_order}/{art.kind.lower()}/{art.filename}"
            body = art.bytes_ if art.bytes_ is not None else (art.text or "").encode()
            ct = art.content_type or mimetypes.guess_type(art.filename)[0] or "application/octet-stream"
            await client.put_object(Bucket=s.s3_bucket, Key=key, Body=body, ContentType=ct)
            await repo.create(run_step_id=run_step_id, kind=ArtifactKind[art.kind],
                url=f"s3://{s.s3_bucket}/{key}", size_bytes=len(body),
                mime_type=ct, metadata=art.metadata)
            log.info("artifact.uploaded", run_id=run_id, key=key, bytes=len(body))
```

### 13.2 Tests — `tests/test_artifacts.py` (moto-mocked S3)

```python
import pytest
from moto import mock_aws
from suitest_runner.artifacts import upload_artifacts
from suitest_mcp.models import McpArtifact

pytestmark = pytest.mark.asyncio


@mock_aws
async def test_upload_round_trip(moto_s3_setup, db_session):
    art = McpArtifact(kind="SCREENSHOT", filename="step.png",
                       content_type="image/png", bytes=b"PNGFAKE")
    await upload_artifacts(session=db_session, ctx={"settings": moto_s3_setup},
        run_id="r1", run_step_id="rs1", step_order=0, artifacts=[art])
    import boto3
    s3 = boto3.client("s3", endpoint_url=moto_s3_setup.s3_endpoint,
        aws_access_key_id=moto_s3_setup.s3_access_key,
        aws_secret_access_key=moto_s3_setup.s3_secret_key)
    obj = s3.get_object(Bucket=moto_s3_setup.s3_bucket,
                        Key="runs/r1/0/screenshot/step.png")
    assert obj["Body"].read() == b"PNGFAKE"
    rows = await db_session.scalars("SELECT * FROM artifacts WHERE run_step_id='rs1'")
    assert len(list(rows)) == 1
```

### Steps

- [ ] **13.1** Write `apps/runner/src/suitest_runner/artifacts.py`
- [ ] **13.2** Add `moto[s3]` to runner test deps
- [ ] **13.3** Verify M1a `ArtifactRepository.create()` exists; add if missing
- [ ] **13.4** Write tests with moto-mocked S3
- [ ] **13.5** Tests green
- [ ] **13.6** Commit: `feat(runner): artifact pipeline uploads to S3/MinIO + persists DB rows`

---

## Task 14: WebSocket gateway in `apps/api`

FastAPI native WS endpoint `/ws?token=<jwt>`. Connection manager joins clients to Redis pub/sub channels. Heartbeat every 30s.

### 14.1 `ws/manager.py`

```python
from __future__ import annotations
import asyncio
from collections import defaultdict
import redis.asyncio as redis_async, structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)


class WsConnection:
    def __init__(self, ws: WebSocket, user_id: str, workspace_id: str) -> None:
        self.ws = ws; self.user_id = user_id
        self.workspace_id = workspace_id
        self.channels: set[str] = set()


class WsConnectionManager:
    def __init__(self, redis_client: redis_async.Redis) -> None:
        self.redis = redis_client
        self._connections: dict[int, WsConnection] = {}
        self._channel_listeners: dict[str, set[int]] = defaultdict(set)
        self._listener_task: asyncio.Task[None] | None = None
        self._pubsub: redis_async.client.PubSub | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._pubsub = self.redis.pubsub()
        self._listener_task = asyncio.create_task(self._listen(), name="ws-listener")

    async def stop(self) -> None:
        if self._listener_task: self._listener_task.cancel()
        if self._pubsub: await self._pubsub.close()

    async def add(self, conn: WsConnection) -> None:
        async with self._lock: self._connections[id(conn)] = conn

    async def remove(self, conn: WsConnection) -> None:
        async with self._lock:
            self._connections.pop(id(conn), None)
            for ch in list(conn.channels):
                self._channel_listeners[ch].discard(id(conn))
                if not self._channel_listeners[ch] and self._pubsub:
                    await self._pubsub.unsubscribe(ch)
                    self._channel_listeners.pop(ch, None)

    async def subscribe(self, conn: WsConnection, channel: str) -> None:
        async with self._lock:
            if not self._channel_listeners[channel] and self._pubsub:
                await self._pubsub.subscribe(channel)
            self._channel_listeners[channel].add(id(conn))
            conn.channels.add(channel)

    async def unsubscribe(self, conn: WsConnection, channel: str) -> None:
        async with self._lock:
            self._channel_listeners.get(channel, set()).discard(id(conn))
            conn.channels.discard(channel)
            if not self._channel_listeners.get(channel) and self._pubsub:
                await self._pubsub.unsubscribe(channel)

    async def _listen(self) -> None:
        assert self._pubsub
        while True:
            msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None: continue
            channel = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
            data = msg["data"]
            if isinstance(data, bytes): data = data.decode()
            async with self._lock:
                ids = list(self._channel_listeners.get(channel, set()))
            for lid in ids:
                conn = self._connections.get(lid)
                if conn:
                    try: await conn.ws.send_text(data)
                    except Exception: log.warning("ws.send.failed", conn=lid)
```

### 14.2 `routers/ws.py`

```python
from __future__ import annotations
import asyncio, json
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from suitest_api.deps.auth import current_user_from_ws_token
from suitest_api.ws.manager import WsConnection, WsConnectionManager

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(...),
                     manager: WsConnectionManager = Depends()):
    user = await current_user_from_ws_token(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION); return
    await websocket.accept()
    conn = WsConnection(ws=websocket, user_id=user.id,
                        workspace_id=user.default_workspace_id)
    await manager.add(conn)
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))
    try:
        await manager.subscribe(conn, f"workspace:{conn.workspace_id}")
        while True:
            raw = await websocket.receive_text()
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            ev = msg.get("event"); data = msg.get("data", {})
            if ev == "subscribe.run" and data.get("runId"):
                await manager.subscribe(conn, f"run:{data['runId']}")
            elif ev == "unsubscribe.run" and data.get("runId"):
                await manager.unsubscribe(conn, f"run:{data['runId']}")
    except WebSocketDisconnect: pass
    finally:
        heartbeat_task.cancel()
        await manager.remove(conn)


async def _heartbeat(ws):
    while True:
        await asyncio.sleep(30)
        try: await ws.send_text(json.dumps({"event": "ping"}))
        except Exception: return
```

### 14.3 Tests — `tests/test_ws_gateway.py`

```python
import asyncio, json, pytest
from httpx_ws import aconnect_ws

pytestmark = pytest.mark.asyncio


async def test_two_clients_receive_published(app, redis_client, auth_token):
    async with aconnect_ws(f"/ws?token={auth_token}", app=app) as a, \
               aconnect_ws(f"/ws?token={auth_token}", app=app) as b:
        for c in (a, b):
            await c.send_text(json.dumps({"event": "subscribe.run", "data": {"runId": "42"}}))
        await asyncio.sleep(0.1)
        await redis_client.publish("run:42",
            json.dumps({"event": "run.step.log", "data": {"line": "hi"}}))
        m1 = await asyncio.wait_for(a.receive_text(), 2)
        m2 = await asyncio.wait_for(b.receive_text(), 2)
        assert json.loads(m1)["event"] == "run.step.log"
        assert json.loads(m2)["event"] == "run.step.log"


async def test_unauthorized_token_closes(app):
    async with aconnect_ws("/ws?token=bad", app=app) as c:
        with pytest.raises(Exception):
            await asyncio.wait_for(c.receive_text(), 1)
```

### Steps

- [ ] **14.1** Write `ws/manager.py`
- [ ] **14.2** Write `routers/ws.py`; register in `apps/api/src/suitest_api/main.py`; wire `WsConnectionManager` lifecycle to FastAPI lifespan
- [ ] **14.3** Add `current_user_from_ws_token` to `apps/api/src/suitest_api/deps/auth.py`
- [ ] **14.4** Add `httpx-ws` to api test deps
- [ ] **14.5** Write `tests/test_ws_gateway.py` (2 cases)
- [ ] **14.6** mypy strict pass
- [ ] **14.7** Commit: `feat(api): websocket gateway with auth + run room subscriptions + heartbeat`

---

## Task 15: `POST /runs` endpoint

Per `docs/API.md` §3.5. Validates project + selection + MCP providers. Enqueues ARQ job. Returns 202 + run record.

### 15.1 `schemas/runs.py`

```python
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import RunStatus, RunTrigger, Tier


class RunSelectionItem(BaseModel):
    case_id: str = Field(alias="caseId")
    selected_step_ids: list[str] | None = Field(default=None, alias="selectedStepIds")


class CreateRunBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)
    project_id: str = Field(alias="projectId")
    name: str = Field(min_length=1, max_length=255)
    selection: list[RunSelectionItem]
    branch: str | None = None
    commit_sha: str | None = Field(default=None, alias="commitSha")
    env: str = "staging"
    trigger: RunTrigger = RunTrigger.MANUAL
    mcp_routing_override: dict[str, Any] | None = Field(default=None, alias="mcpRoutingOverride")


class RunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: str
    public_id: str = Field(serialization_alias="publicId")
    project_id: str = Field(serialization_alias="projectId")
    name: str
    branch: str | None
    commit_sha: str | None = Field(serialization_alias="commitSha")
    env: str
    trigger: RunTrigger
    status: RunStatus
    tier_at_runtime: Tier = Field(serialization_alias="tierAtRuntime")
    started_at: datetime | None = Field(serialization_alias="startedAt")
    completed_at: datetime | None = Field(serialization_alias="completedAt")
    duration_ms: int | None = Field(serialization_alias="durationMs")
    total_steps: int = Field(serialization_alias="totalSteps")
    passed_steps: int = Field(serialization_alias="passedSteps")
    failed_steps: int = Field(serialization_alias="failedSteps")
    created_at: datetime = Field(serialization_alias="createdAt")
```

### 15.2 `routers/runs.py` — create handler

```python
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from suitest_api.deps.arq import get_arq
from suitest_api.deps.auth import current_user
from suitest_api.deps.db import get_session
from suitest_api.deps.tier import require_tier
from suitest_api.schemas.runs import CreateRunBody, RunPublic
from suitest_api.services.run_service import RunService
from suitest_shared.domain.enums import Tier

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunPublic, status_code=status.HTTP_202_ACCEPTED)
async def create_run(body: CreateRunBody, session=Depends(get_session),
                     user=Depends(current_user), arq: ArqRedis = Depends(get_arq),
                     _: None = Depends(require_tier(Tier.ZERO | Tier.LOCAL | Tier.CLOUD))) -> RunPublic:
    svc = RunService(session)
    try:
        run = await svc.create_run(project_id=body.project_id, name=body.name,
            selection=[i.model_dump(by_alias=False) for i in body.selection],
            branch=body.branch, commit_sha=body.commit_sha, env=body.env,
            trigger=body.trigger, user_id=user.id,
            mcp_routing_override=body.mcp_routing_override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = await arq.enqueue_job("run_test_case", run.id, _queue_name="suitest:runs")
    await svc.attach_arq_job_id(run.id, job.job_id)
    await session.commit()
    return RunPublic.model_validate(run)
```

### 15.3 `services/run_service.py` — `create_run` core logic

```python
async def create_run(self, *, project_id, name, selection, branch, commit_sha,
                     env, trigger, user_id, mcp_routing_override):
    project = await self.session.get(Project, project_id)
    if project is None: raise ValueError("project not found")
    if not selection: raise ValueError("selection cannot be empty")

    registered = {p.name for p in await McpProviderRepository(self.session)
                  .list_for_workspace(project.workspace_id)}
    registered |= {"api-http-mcp", "playwright-mcp", "postgres-mcp"}  # bundled

    for item in selection:
        case = await self.session.get(TestCase, item["case_id"])
        if not case or case.suite.project_id != project_id:
            raise ValueError(f"case {item['case_id']} not in project")
        for step in case.steps:
            if step.mcp_provider and step.mcp_provider not in registered:
                raise ValueError(f"step {step.id} references unregistered MCP {step.mcp_provider}")

    cap = await WorkspaceCapabilityRepository(self.session).get(project.workspace_id)
    tier = Tier(cap.tier) if cap else Tier.ZERO

    run = RunRow(public_id=generate_public_id("run"), project_id=project_id, name=name,
        branch=branch, commit_sha=commit_sha, env=env, trigger=trigger,
        triggered_by=user_id, status=RunStatus.QUEUED, tier_at_runtime=tier,
        metadata={"selection": selection, "mcp_routing_override": mcp_routing_override})
    self.session.add(run); await self.session.flush()
    await write_audit(self.session, workspace_id=project.workspace_id, user_id=user_id,
        action="run.create", resource_type="run", resource_id=run.id,
        metadata={"trigger": trigger.value})
    return run


async def attach_arq_job_id(self, run_id, job_id):
    run = await self.session.get(RunRow, run_id)
    run.metadata = {**(run.metadata or {}), "arq_job_id": job_id}
```

### 15.4 Tests — `tests/test_runs_endpoint.py` (4 cases)

Cases: 202 + record returned and tier=ZERO; unknown project → 400; unknown MCP provider → 400; ARQ enqueue invoked with `run_test_case`.

### Steps

- [ ] **15.1** Write `schemas/runs.py` and `routers/runs.py`
- [ ] **15.2** Extend `RunService.create_run` + `attach_arq_job_id`
- [ ] **15.3** Write tests (4 cases)
- [ ] **15.4** Tests green; mypy strict pass
- [ ] **15.5** Commit: `feat(api): POST /runs validates selection + MCP routing + enqueues ARQ job`

---

## Task 16: `POST /runs/:id/cancel` + `/rerun`

### 16.1 Endpoints

```python
@router.post("/{run_id}/cancel", response_model=RunPublic)
async def cancel_run(run_id: str, session=Depends(get_session),
                     user=Depends(current_user), arq: ArqRedis = Depends(get_arq)):
    svc = RunService(session)
    run = await svc.get(run_id)
    if run is None: raise HTTPException(404)
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise HTTPException(409, detail="run not cancellable")
    job_id = (run.metadata or {}).get("arq_job_id")
    if job_id:
        try: await arq.abort_job(job_id)
        except Exception: pass
    await svc.update_status(run_id, RunStatus.CANCELLED)
    await session.commit()
    return RunPublic.model_validate(await svc.get(run_id))


@router.post("/{run_id}/rerun", response_model=RunPublic, status_code=202)
async def rerun(run_id: str, session=Depends(get_session),
                user=Depends(current_user), arq: ArqRedis = Depends(get_arq)):
    svc = RunService(session)
    src = await svc.get(run_id)
    if src is None: raise HTTPException(404)
    new_run = await svc.clone_for_rerun(src, user_id=user.id)
    job = await arq.enqueue_job("run_test_case", new_run.id, _queue_name="suitest:runs")
    await svc.attach_arq_job_id(new_run.id, job.job_id)
    await session.commit()
    return RunPublic.model_validate(new_run)
```

### 16.2 Tests (3 cases)

Cancel QUEUED run → 200 + status CANCELLED; cancel COMPLETED run → 409; rerun clones → new id + status QUEUED.

### Steps

- [ ] **16.1** Implement cancel + rerun endpoints
- [ ] **16.2** Extend `RunService` with `clone_for_rerun`, `update_status`, `get`
- [ ] **16.3** Write tests
- [ ] **16.4** Commit: `feat(api): POST /runs/:id/cancel + /rerun`

> Note: scheduled cron runs (ARQ cron) deferred to M1d — out of scope for M1c.

---

## Task 17: Run logs cursor endpoint

`GET /api/v1/runs/:id/logs?cursor=N&limit=200`. Logs persisted to a new `run_step_logs` table written through alongside Redis pubsub by the orchestrator.

### 17.1 Alembic migration — `2026_05_27_run_step_logs.py`

```python
"""run_step_logs table for M1c persistent log streaming

Revision ID: 20260527_run_step_logs
"""

revision = "20260527_run_step_logs"
down_revision = "<previous>"


def upgrade() -> None:
    op.create_table("run_step_logs",
        sa.Column("id", sa.String(30), primary_key=True),
        sa.Column("run_id", sa.String(30),
                  sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_step_id", sa.String(30),
                  sa.ForeignKey("run_steps.id", ondelete="CASCADE"), nullable=True),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Index("ix_run_step_logs_run_seq", "run_id", "seq"),
    )


def downgrade() -> None:
    op.drop_table("run_step_logs")
```

### 17.2 ORM + repo

```python
# packages/db/src/suitest_db/models/run_step_log.py
class RunStepLog(Base):
    __tablename__ = "run_step_logs"
    id: Mapped[str] = mapped_column(String(30), primary_key=True, default=cuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run_step_id: Mapped[str | None] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 17.3 Orchestrator hook

In Task 12's orchestrator, every event published to Redis is **also** persisted via `RunStepLogRepository.append(run_id, run_step_id, level, message)`. `seq` is incrementing per-run (use a Redis `INCR run:<id>:logseq` counter for monotonicity).

### 17.4 Endpoint

```python
@router.get("/{run_id}/logs")
async def get_logs(run_id: str, cursor: int = 0, limit: int = 200,
                   session=Depends(get_session), user=Depends(current_user)) -> dict:
    rows = await RunStepLogRepository(session).list_after(run_id, cursor=cursor, limit=limit)
    next_cursor = rows[-1].seq if rows else cursor
    return {"items": [{"seq": r.seq, "level": r.level, "message": r.message,
                       "createdAt": r.created_at.isoformat()} for r in rows],
            "nextCursor": next_cursor, "hasMore": len(rows) == limit}
```

### 17.5 Test

```python
async def test_logs_paginate_500(api_client, run_with_500_logs):
    rid = run_with_500_logs.id
    p1 = (await api_client.get(f"/api/v1/runs/{rid}/logs?limit=200")).json()
    p2 = (await api_client.get(f"/api/v1/runs/{rid}/logs?cursor={p1['nextCursor']}&limit=200")).json()
    p3 = (await api_client.get(f"/api/v1/runs/{rid}/logs?cursor={p2['nextCursor']}&limit=200")).json()
    assert len(p1["items"]) == 200 and len(p2["items"]) == 200 and len(p3["items"]) == 100
    assert p3["hasMore"] is False
```

### Steps

- [ ] **17.1** Write alembic migration for `run_step_logs`
- [ ] **17.2** Write `RunStepLog` ORM + `RunStepLogRepository.append/list_after`
- [ ] **17.3** Modify Task 12 orchestrator to write-through logs (with per-run seq counter from Redis)
- [ ] **17.4** Implement `GET /runs/:id/logs`
- [ ] **17.5** Write pagination test
- [ ] **17.6** Commit: `feat(api): persisted run logs with cursor pagination + run_step_logs migration`

---

## Task 18: Artifact signed URL

`GET /api/v1/runs/:id/artifacts/:artifactId` returns presigned URL via aioboto3 (TTL 1h).

### 18.1 Endpoint

```python
@router.get("/{run_id}/artifacts/{artifact_id}")
async def get_artifact_signed_url(run_id: str, artifact_id: str,
                                  session=Depends(get_session), user=Depends(current_user)):
    art = await ArtifactRepository(session).get(artifact_id)
    if not art or not art.url.startswith("s3://"): raise HTTPException(404)
    bucket, key = art.url.replace("s3://", "").split("/", 1)
    async with aioboto3.Session().client("s3", endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key) as client:
        url = await client.generate_presigned_url("get_object",
            Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    await write_audit(session, workspace_id=user.default_workspace_id, user_id=user.id,
        action="artifact.signed_url", resource_type="artifact", resource_id=artifact_id,
        metadata={"run_id": run_id})
    await session.commit()
    return {"url": url, "expiresInSeconds": 3600,
            "kind": art.kind.value, "mimeType": art.mime_type}
```

### 18.2 Test

```python
async def test_signed_url_fetches(api_client, run_with_artifact, moto_s3):
    r = await api_client.get(
        f"/api/v1/runs/{run_with_artifact.id}/artifacts/{run_with_artifact.artifact_id}")
    assert r.status_code == 200
    import httpx
    async with httpx.AsyncClient() as c:
        obj = await c.get(r.json()["url"])
    assert obj.status_code == 200 and obj.content == b"PNGFAKE"
```

### Steps

- [ ] **18.1** Implement endpoint with audit log
- [ ] **18.2** Write test against moto-mocked S3
- [ ] **18.3** Commit: `feat(api): GET /runs/:id/artifacts/:id returns presigned S3 URL`

---

## Task 19: FE wiring for live run detail

Wire `apps/web/src/routes/_app/runs/$runId.tsx` (M1b placeholder) to: REST fetch run/steps/artifacts, WS subscribe to `run:<id>`, append logs, update step status, swap browser preview screenshot.

### 19.1 `lib/ws-client.ts` — typed hook

```ts
type RunEvent =
  | { event: "run.started"; data: { runId: string; tier: string } }
  | { event: "run.step.started"; data: { runId: string; stepIndex: number; action: string;
                                          mcpProvider: string; targetKind: string } }
  | { event: "run.step.log"; data: { runId: string; stepIndex: number; level: string;
                                      message: string; time: string } }
  | { event: "run.step.completed"; data: { runId: string; stepIndex: number;
                                            outcome: string; durationMs: number } }
  | { event: "run.completed"; data: { runId: string; status: string; totalSteps: number;
                                       passedSteps: number; failedSteps: number; durationMs: number } };

export function useRunStream(runId: string, onEvent: (e: RunEvent) => void): void;
```

### 19.2 `routes/_app/runs/$runId.tsx` outline

```tsx
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchRun, fetchRunSteps, fetchRunArtifacts } from "@/lib/api-client";
import { useRunStream } from "@/lib/ws-client";
import { RunSummaryCard } from "@/components/runs/RunSummaryCard";
import { StepTable } from "@/components/runs/StepTable";
import { LogPane } from "@/components/runs/LogPane";
import { BrowserPreview } from "@/components/runs/BrowserPreview";

export const Route = createFileRoute("/_app/runs/$runId")({ component: RunDetailPage });

function RunDetailPage() {
  const { runId } = Route.useParams();
  const { data: run } = useQuery({ queryKey: ["run", runId], queryFn: () => fetchRun(runId) });
  const { data: steps = [], refetch: refetchSteps } = useQuery({
    queryKey: ["run-steps", runId], queryFn: () => fetchRunSteps(runId) });
  const { data: artifacts = [], refetch: refetchArtifacts } = useQuery({
    queryKey: ["run-artifacts", runId], queryFn: () => fetchRunArtifacts(runId) });
  const [logs, setLogs] = useState<{ stepIndex: number; level: string; message: string; time: string }[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const autoScrollRef = useRef(true);

  useRunStream(runId, (e) => {
    switch (e.event) {
      case "run.step.log": setLogs((p) => [...p, e.data]); break;
      case "run.step.started":
      case "run.step.completed": refetchSteps(); break;
      case "run.completed": refetchSteps(); refetchArtifacts(); break;
    }
  });

  useEffect(() => {
    const latest = [...artifacts].reverse().find((a) => a.kind === "SCREENSHOT");
    if (latest) {
      fetch(`/api/v1/runs/${runId}/artifacts/${latest.id}`)
        .then((r) => r.json()).then((j) => setPreviewUrl(j.url));
    }
  }, [artifacts, runId]);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12"><RunSummaryCard run={run} /></div>
      <div className="col-span-7"><StepTable steps={steps} /></div>
      <div className="col-span-5"><BrowserPreview url={previewUrl} /></div>
      <div className="col-span-12"><LogPane logs={logs} autoScrollRef={autoScrollRef} /></div>
    </div>
  );
}
```

### 19.3 Tests — vitest with MockWs

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { RunDetailPage } from "../$runId";
import { MockWs } from "@/test/mock-ws";

describe("RunDetailPage", () => {
  it("appends log line when WS publishes run.step.log", async () => {
    const ws = new MockWs();
    render(<RunDetailPage />, { wrapper: makeWrapper({ ws }) });
    await act(() => ws.emit({ event: "run.step.log",
      data: { runId: "r1", stepIndex: 0, level: "info",
              message: "hello", time: "2026-05-26T00:00:00Z" } }));
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("preserves user scroll position when scrolled up", async () => { /* ... */ });
});
```

### Steps

- [ ] **19.1** Extend `ws-client.ts` with typed `useRunStream`
- [ ] **19.2** Implement `RunDetailPage` + sub-components (`RunSummaryCard`, `StepTable`, `LogPane`, `BrowserPreview`)
- [ ] **19.3** Add `MockWs` test helper at `apps/web/src/test/mock-ws.ts`
- [ ] **19.4** Write vitest tests (log append, auto-scroll respect)
- [ ] **19.5** Commit: `feat(web): wire run detail to live WS stream + artifact preview`

---

## Task 20: MCP provider browser UI (read-only)

Wire `apps/web/src/routes/_app/integrations.tsx` MCP Servers tab to `GET /mcp/providers`. List items with health pill, name, kind, tool count. Click → modal with tool list. "Try it" form deferred to M2.

### 20.1 Component outline

```tsx
import { useQuery } from "@tanstack/react-query";
import { fetchMcpProviders, fetchMcpProvider } from "@/lib/api-client";
import { useState } from "react";
import { useWorkspaceStream } from "@/lib/ws-client";
import { HealthPill } from "@/components/mcp/HealthPill";
import { ProviderModal } from "@/components/mcp/ProviderModal";

export function McpServersPanel() {
  const { data: providers = [], refetch } = useQuery({
    queryKey: ["mcp-providers"], queryFn: fetchMcpProviders });
  const [openId, setOpenId] = useState<string | null>(null);

  useWorkspaceStream((e) => { if (e.event === "mcp.provider.health") refetch(); });

  return (
    <>
      <ul className="grid grid-cols-1 gap-2">
        {providers.map((p) => (
          <li key={p.id}
              className="rounded border border-border p-3 flex items-center gap-3 cursor-pointer"
              onClick={() => setOpenId(p.id)}>
            <HealthPill status={p.healthStatus} />
            <span className="font-medium">{p.name}</span>
            <span className="text-fg-3 text-sm">{p.kind}</span>
            <span className="ml-auto text-fg-4 text-xs">{p.tools?.length ?? 0} tools</span>
          </li>
        ))}
      </ul>
      {openId && <ProviderModal id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
```

### 20.2 Tests

```tsx
it("renders providers from API", async () => {
  vi.mocked(fetchMcpProviders).mockResolvedValue([
    { id: "1", name: "playwright-mcp", kind: "browser", healthStatus: "ok",
      tools: [{ name: "browser.navigate" }] }]);
  render(<McpServersPanel />, { wrapper });
  expect(await screen.findByText("playwright-mcp")).toBeInTheDocument();
  expect(screen.getByText("1 tools")).toBeInTheDocument();
});

it("updates health pill on WS event", async () => {
  // emit mcp.provider.health → refetch → new pill status
});
```

### Steps

- [ ] **20.1** Implement `McpServersPanel`, `HealthPill`, `ProviderModal`
- [ ] **20.2** Wire into `integrations.tsx` tab
- [ ] **20.3** Write vitest tests
- [ ] **20.4** Commit: `feat(web): MCP provider browser with health pill + tool list modal`

---

## Task 21: Concurrency + resource limits

Document + enforce tuning knobs end-to-end.

### 21.1 Env vars (add to `.env.example`)

```
SUITEST_RUNNER_CONCURRENCY=4
SUITEST_RUNNER_MAX_RETRIES=2
SUITEST_RUNNER_JOB_TIMEOUT_SECONDS=1800
SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE=16
SUITEST_MCP_QUEUE_TIMEOUT_SECONDS=30
```

### 21.2 Workspace-level cap — `packages/mcp/src/suitest_mcp/workspace_cap.py`

```python
from __future__ import annotations
import asyncio, time
from collections import defaultdict
from contextlib import asynccontextmanager
from suitest_mcp.errors import McpPoolExhausted


class WorkspacePoolCap:
    def __init__(self, *, max_per_workspace: int) -> None:
        self.max = max_per_workspace
        self._counts: dict[str, int] = defaultdict(int)
        self._cond = asyncio.Condition()

    @asynccontextmanager
    async def reserve(self, workspace_id: str, *, timeout: float):
        deadline = time.monotonic() + timeout
        async with self._cond:
            while self._counts[workspace_id] >= self.max:
                wait_time = deadline - time.monotonic()
                if wait_time <= 0:
                    raise McpPoolExhausted(f"ws {workspace_id} cap {self.max} reached")
                try: await asyncio.wait_for(self._cond.wait(), timeout=wait_time)
                except TimeoutError as exc:
                    raise McpPoolExhausted(f"ws {workspace_id} queue timeout") from exc
            self._counts[workspace_id] += 1
        try: yield
        finally:
            async with self._cond:
                self._counts[workspace_id] -= 1
                self._cond.notify_all()
```

Wire into `McpInvoker.invoke()` to wrap `pool.acquire` with `cap.reserve(ctx.workspace_id, ...)`.

### 21.3 Stress test

```python
async def test_stress_8_parallel_runs_throttled(stub_ctx_8_runs):
    tasks = [asyncio.create_task(run_test_case(stub_ctx_8_runs, f"r{i}")) for i in range(8)]
    results = await asyncio.gather(*tasks)
    assert all(r["status"] in ("PASS", "FAIL") for r in results)
    assert stub_ctx_8_runs["_peak_live"] <= 4   # cap=4
```

### Steps

- [ ] **21.1** Add env vars to `.env.example` and `RunnerSettings`
- [ ] **21.2** Implement `WorkspacePoolCap`
- [ ] **21.3** Wire into invoker
- [ ] **21.4** Write stress test
- [ ] **21.5** Update `docs/DEPLOYMENT.md` + `docs/MCP_PLUGINS.md` §8 with env var names (cross-check)
- [ ] **21.6** Commit: `feat(mcp): workspace-level session cap with fair queue + stress test`

---

## Task 22: DoD smoke test (E2E)

Closing loop: create case via API → POST /runs → connect WS → assert events → assert artifacts uploaded → assert run PASS.

### 22.1 Test — `tests/e2e/test_m1c_smoke.py`

```python
import asyncio, json, pytest
from httpx_ws import aconnect_ws

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_full_run_lifecycle(api_client, nginx_test_page_url, auth_token):
    # 1. Create case with 5 playwright-mcp steps
    steps = [
        {"action": "Navigate", "expected": "Page loads",
         "mcpProvider": "playwright-mcp", "targetKind": "FE_WEB",
         "code": json.dumps({"tool": "browser.navigate",
                             "arguments": {"url": nginx_test_page_url}})},
        {"action": "Screenshot", "expected": "captured",
         "mcpProvider": "playwright-mcp", "targetKind": "FE_WEB",
         "code": json.dumps({"tool": "browser.screenshot", "arguments": {"fullPage": True}})},
        {"action": "Assert heading", "expected": "Hello Suitest",
         "mcpProvider": "playwright-mcp", "targetKind": "FE_WEB",
         "code": json.dumps({"tool": "browser.assert_text",
                              "arguments": {"selector": "#hero", "contains": "Hello Suitest"}})},
        {"action": "Type", "expected": "filled",
         "mcpProvider": "playwright-mcp", "targetKind": "FE_WEB",
         "code": json.dumps({"tool": "browser.type",
                              "arguments": {"selector": "#q", "text": "hi"}})},
        {"action": "Click", "expected": "clicked",
         "mcpProvider": "playwright-mcp", "targetKind": "FE_WEB",
         "code": json.dumps({"tool": "browser.click", "arguments": {"selector": "#go"}})},
    ]
    case = (await api_client.post("/api/v1/test-cases", json={
        "name": "Smoke flow", "suiteId": "<seeded>", "source": "MANUAL", "steps": steps,
    })).json()

    # 2. POST /runs
    run_id = (await api_client.post("/api/v1/runs", json={
        "projectId": case["projectId"], "name": "E2E smoke",
        "selection": [{"caseId": case["id"]}],
    })).json()["id"]

    # 3. Connect WS + collect events
    events: list[dict] = []
    async with aconnect_ws(f"/ws?token={auth_token}", app=api_client.app) as ws:
        await ws.send_text(json.dumps({"event": "subscribe.run", "data": {"runId": run_id}}))
        async def collect():
            while True:
                events.append(json.loads(await ws.receive_text()))
                if events[-1].get("event") == "run.completed": return
        await asyncio.wait_for(collect(), timeout=120)

    # 4. Assert event sequence
    kinds = [e["event"] for e in events]
    assert "run.started" in kinds
    assert kinds.count("run.step.started") == 5
    assert kinds.count("run.step.completed") == 5
    assert kinds[-1] == "run.completed"
    final = events[-1]["data"]
    assert final["status"] == "PASS"
    assert final["totalSteps"] == 5 and final["passedSteps"] == 5

    # 5. Assert artifacts uploaded
    arts = (await api_client.get(f"/api/v1/runs/{run_id}/artifacts")).json()
    assert any(a["kind"] == "SCREENSHOT" for a in arts)

    # 6. Signed URL fetches the object
    art = next(a for a in arts if a["kind"] == "SCREENSHOT")
    signed = (await api_client.get(
        f"/api/v1/runs/{run_id}/artifacts/{art['id']}")).json()
    assert signed["url"].startswith("http")
```

### 22.2 CI workflow stub — `.github/workflows/m1c-e2e.yml`

```yaml
name: M1c E2E
on: [pull_request]
jobs:
  smoke:
    runs-on: ubuntu-latest
    services:
      docker: { image: docker:dind, options: --privileged }
    steps:
      - uses: actions/checkout@v4
      - run: docker compose up -d
      - run: uv sync
      - run: uv run pytest -m e2e -q
```

### Steps

- [ ] **22.1** Author E2E smoke test
- [ ] **22.2** Add CI workflow stub running against full docker-compose stack
- [ ] **22.3** Verify all 22 tasks' tests pass in CI
- [ ] **22.4** Tag `v0.4.0-m1c`; push tag
- [ ] **22.5** Commit: `chore: tag v0.4.0-m1c — M1c DoD complete`

---

## Definition of Done — M1c

A green check on every box below:

- [ ] All 22 tasks committed individually with conventional-commit messages
- [ ] `pytest` green: `packages/mcp`, `apps/runner`, `apps/api`
- [ ] `vitest` green: `apps/web`
- [ ] `mypy --strict packages apps` returns 0 errors
- [ ] `ruff check` + `ruff format --check` clean
- [ ] Acceptance criteria M1-16 through M1-20 from ROADMAP.md all checked
- [ ] E2E smoke green: create case → run → WS events received → artifacts viewable
- [ ] No LLM call anywhere in M1c-touched code — verify with `grep -r 'litellm\|openai\|anthropic' apps/runner apps/api packages/mcp` (zero hits expected)
- [ ] `docs/DEPLOYMENT.md` updated: Playwright npm install + browser install RUN lines; runner env vars; MinIO bucket bootstrap
- [ ] `docs/MCP_PLUGINS.md` §8 env var names match Task 21 reality
- [ ] `v0.4.0-m1c` tag pushed

## Cross-reference checklist

| ROADMAP acceptance | Implementing task |
|--------------------|-------------------|
| M1-16 packages/mcp registry + client + pool | Tasks 1-5 |
| M1-17 bundled providers (playwright, api-http, postgres) | Tasks 6-8 |
| M1-18 ARQ worker dispatch per-step | Tasks 10-12 |
| M1-19 WebSocket log streaming + screenshot + MinIO | Tasks 13-14, 17 |
| M1-20 Run cancel + rerun (scheduled cron → M1d) | Task 16 |

> Scheduled cron runs (ARQ cron) are explicitly deferred to **M1d** and tracked in the next milestone plan.

---

_End of plan 04 — M1c — ZERO Runner + MCP Bundle._
