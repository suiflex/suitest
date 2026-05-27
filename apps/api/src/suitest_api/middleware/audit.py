"""Request-scoped audit attribution middleware.

Binds an :class:`~suitest_db.audit.AuditContext` to the per-request
:data:`~suitest_db.audit.audit_ctx` ``ContextVar` so the global SQLAlchemy
``after_flush`` listener can attribute every mutation to a workspace + caller +
origin.

M1a limitation — ``user_id`` is left ``None`` here:
  Authentication is resolved by a *route dependency* (``current_active_user``),
  which runs AFTER this middleware in the ASGI stack. The middleware therefore
  cannot see the authenticated user. We populate what is available pre-routing
  (``ip_address``, ``user_agent``, and ``workspace_id`` from the ``X-Workspace-Id``
  header). Concrete ``user_id`` attribution lands in M1d, where mutating service
  methods set it from the resolved ``TenantContext``. This is acceptable for M1a
  because no mutating endpoints exist yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from suitest_db.audit import AuditContext, audit_ctx

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class AuditContextMiddleware:
    """Set :data:`audit_ctx` from the incoming request for its lifetime.

    A pure ASGI middleware (no ``BaseHTTPMiddleware`` overhead). The context token
    is always reset in ``finally`` so a failing/aborted request never leaks
    attribution into a pooled worker.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        ctx = AuditContext(
            user_id=None,  # M1a: see module docstring — set later in the service layer
            workspace_id=request.headers.get("X-Workspace-Id"),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        token = audit_ctx.set(ctx)
        try:
            await self.app(scope, receive, send)
        finally:
            audit_ctx.reset(token)
