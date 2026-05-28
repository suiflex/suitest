"""Span-attribute enrichment middleware.

Picks up the per-request :class:`~suitest_db.audit.AuditContext` (populated by
:class:`~suitest_api.middleware.audit.AuditContextMiddleware`) and tags the
currently-active OTel span with multi-tenant attribution
(``workspace.id`` / ``user.id``) plus the resolved deployment ``capabilities.tier``.

ASGI ordering:
  Must mount *after* :class:`AuditContextMiddleware` so ``audit_ctx.get()`` is
  populated when we run. FastAPI applies middleware outermost-last (the most
  recently added wraps the previous), so calling ``app.add_middleware(...)`` here
  AFTER the audit middleware places this layer *inside* it — exactly what we want
  (audit sets the ContextVar before we read it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from suitest_db.audit import audit_ctx

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import ASGIApp, Receive, Scope, Send


class SpanAttributesMiddleware:
    """Tag the active OTel span with workspace/user/tier from request context."""

    def __init__(self, app: ASGIApp, fastapi_app: FastAPI) -> None:
        self.app = app
        self._fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        span = trace.get_current_span()
        ctx = audit_ctx.get()
        attrs: dict[str, str] = {}
        if ctx is not None:
            if ctx.workspace_id:
                attrs["workspace.id"] = ctx.workspace_id
            if ctx.user_id:
                attrs["user.id"] = ctx.user_id
        capabilities = getattr(self._fastapi_app.state, "capabilities", None)
        tier = getattr(getattr(capabilities, "tier", None), "value", None)
        if isinstance(tier, str) and tier:
            attrs["capabilities.tier"] = tier
        if attrs and span.is_recording():
            span.set_attributes(attrs)

        await self.app(scope, receive, send)
