"""HTTP-level test for :class:`AuditContextMiddleware` (Task 6.6).

Asserts the middleware binds the per-request :data:`audit_ctx` with the values it
can see *before* routing: client IP, user-agent, and the ``X-Workspace-Id`` header.
``user_id`` is ``None`` at this layer by design (auth is a route dependency that
runs after middleware — see the middleware module docstring).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.main import create_app
from suitest_db.audit import AuditContext, audit_ctx


@pytest_asyncio.fixture
async def echo_client() -> AsyncIterator[AsyncClient]:
    """App with an extra route that echoes the bound audit context as JSON."""
    app = create_app()

    @app.get("/_test/audit-ctx")
    async def _echo() -> dict[str, str | None]:
        ctx: AuditContext | None = audit_ctx.get()
        assert ctx is not None, "middleware must bind audit_ctx for every request"
        return {
            "user_id": ctx.user_id,
            "workspace_id": ctx.workspace_id,
            "ip_address": ctx.ip_address,
            "user_agent": ctx.user_agent,
        }

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_audit_middleware_sets_context_from_headers(echo_client: AsyncClient) -> None:
    response = await echo_client.get(
        "/_test/audit-ctx",
        headers={"X-Workspace-Id": "ws_x", "User-Agent": "smoke-agent/1.0"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == "ws_x"
    assert body["user_agent"] == "smoke-agent/1.0"
    assert body["ip_address"] is not None  # ASGITransport supplies a client host
    assert body["user_id"] is None  # M1a: set later in the service layer


@pytest.mark.asyncio
async def test_audit_middleware_resets_context_after_request(echo_client: AsyncClient) -> None:
    # After the request completes the ContextVar must be reset back to None so
    # attribution never leaks across requests handled on the same worker.
    await echo_client.get("/_test/audit-ctx", headers={"X-Workspace-Id": "ws_x"})
    assert audit_ctx.get() is None
