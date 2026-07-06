"""Per-audience rate limiting via :mod:`slowapi` (Task 12, docs/API.md §5).

Three audiences are bucketed separately by the ``_audience_key`` function:

1. **Bearer token** (``Authorization: Bearer <token>``) — bucket key
   ``token:<sha256(token)[:16]>``. Higher per-minute budget (1000/min) earmarked
   for CI/SDK integrations; applied via per-route ``@limiter.limit(...)`` overrides
   on SDK-facing endpoints. M1a has no SDK-only routes, so this is documented
   here and demonstrated on ``/capabilities`` as the wiring sample. Full
   audience-tiered limits land alongside the SDK in M4.
2. **Cookie session** (``suitest_session=...``) — bucket key
   ``user:<sha256(cookie)[:16]>``. Each authenticated browser shares a stable
   session id, so the hashed cookie value is a stable, anonymous bucket id.
   Subject to the global ``default_limits`` (600/min).
3. **Anonymous** (no auth) — bucket key ``ip:<client.host>``. Same 600/min
   budget; relevant for unauthenticated probes against ``/health`` /
   ``/capabilities``.

Per-route overrides (planned, see docs/API.md §5):

- Webhook routes (M1d future) — exempt via ``@limiter.exempt``.
- Agent routes (M3 future) — ``@limiter.limit("60/minute")`` keyed by workspace.
- Generation routes (M3 future) — ``@limiter.limit("20/minute")`` keyed by
  workspace.

Anonymous-route exemptions (Issue I1):

Health / probe / docs endpoints share the anonymous IP bucket with public
traffic. To keep Prometheus scrapers + k8s liveness probes from burning the
budget for legitimate anonymous users, the following routes are
**always exempt** from the rate limiter:

- ``/health`` — liveness probe (handler decorated with ``@limiter.exempt``).
- ``/capabilities/health`` — public health probe (same).
- ``/openapi.json`` — schema doc (~75KB); exempted in :func:`suitest_api.main._exempt_anonymous_routes`
  by inserting the FastAPI-auto-registered handler name into
  ``Limiter._exempt_routes`` post-wiring.
- ``/docs`` — Swagger UI shell; same mechanism as ``/openapi.json``.
- ``/metrics`` — Prometheus exposition; same mechanism (Prometheus's
  ``instrumentator.expose`` registers the handler we cannot decorate).

Storage backend: Redis when ``SUITEST_REDIS_URL`` is set (matches docker-compose
in M0), in-process ``memory://`` fallback otherwise so dev/tests without Redis
still work. ``headers_enabled=True`` so the standard ``Retry-After`` /
``X-RateLimit-*`` headers ride on every response.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from slowapi import Limiter
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.requests import Request
    from starlette.responses import Response

# slowapi types `default_limits` as ``list[str | Callable[..., str]]`` (invariant
# list, see PEP 484), so the alias here keeps callers honest without `list[Any]`.
_LimitSpec = str | Callable[..., str]


def _hash_bucket(value: str) -> str:
    """Return the first 16 hex chars of ``sha256(value)`` — stable anonymous bucket id."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _audience_key(request: Request) -> str:
    """Resolve the rate-limit bucket for the inbound request.

    Order matters: Bearer wins over cookie wins over IP. The Bearer prefix is
    distinct so per-route overrides can target only the SDK audience later
    (cf. ``@limiter.limit("1000/minute", key_func=...)`` patterns in M4).
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header:
        prefix, _, token = auth_header.partition(" ")
        if prefix.lower() == "bearer" and token:
            return f"token:{_hash_bucket(token)}"

    session_cookie = request.cookies.get("suitest_session")
    if session_cookie:
        return f"user:{_hash_bucket(session_cookie)}"

    client = request.client
    host = client.host if client is not None else "unknown"
    return f"ip:{host}"


def build_limiter(
    *,
    storage_uri: str | None = None,
    default_limits: list[_LimitSpec] | None = None,
    enabled: bool = True,
) -> Limiter:
    """Construct a :class:`slowapi.Limiter` bound to ``_audience_key``.

    ``storage_uri`` defaults to ``$SUITEST_REDIS_URL`` (matches docker-compose) and
    falls back to ``memory://`` so unit tests and dev shells without Redis still
    work. ``default_limits`` applies to every route without a per-route override —
    this is what enforces the 600/min web-user budget. Tests inject a low limit
    (e.g. ``["5/minute"]``) to keep the over-threshold case cheap.
    """
    resolved_storage = storage_uri or os.environ.get("SUITEST_REDIS_URL", "memory://")
    resolved_defaults: list[_LimitSpec] = (
        default_limits if default_limits is not None else ["600/minute"]
    )
    return Limiter(
        key_func=_audience_key,
        storage_uri=resolved_storage,
        default_limits=resolved_defaults,
        headers_enabled=True,
        enabled=enabled,
    )


def iter_flattened_routes(routes: object) -> Iterator[object]:
    """Yield every route, descending into fastapi >= 0.139 ``_IncludedRouter``s.

    ``app.routes`` no longer flattens ``include_router`` results; the real
    APIRoutes hang off each entry's ``original_router``. Callers that used to
    scan ``app.routes`` for endpoints must walk this instead.
    """
    for route in routes:  # type: ignore[attr-defined]
        yield route
        sub = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if sub:
            yield from iter_flattened_routes(sub)


def _resolve_endpoint(routes: object, scope: dict[str, object]) -> Callable[..., object] | None:
    """Recursively resolve the endpoint function for ``scope``.

    fastapi >= 0.139 registers each ``include_router`` as a nested
    ``_IncludedRouter`` entry in ``app.routes`` instead of flattening the
    APIRoutes. slowapi's flat ``_find_route_handler`` then resolves every
    included route to ``None``, and its middleware treats ``None`` as exempt —
    silently disabling the limiter for the whole /api/v1 surface. This walker
    descends into anything that exposes ``.routes``.
    """
    from starlette.routing import Match

    for route in routes:  # type: ignore[attr-defined]
        endpoint = getattr(route, "endpoint", None)
        matcher = getattr(route, "matches", None)
        child_scope: dict[str, object] = {}
        if matcher is not None:
            match, child_scope = matcher(scope)
            if match == Match.NONE:
                continue
            if match == Match.FULL and endpoint is not None:
                return endpoint  # type: ignore[no-any-return]
        # fastapi's _IncludedRouter exposes no ``.routes``; the real APIRoutes
        # hang off ``original_router`` (their paths already carry the prefix).
        sub_routes = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if sub_routes:
            found = _resolve_endpoint(sub_routes, {**scope, **child_scope})
            if found is not None:
                return found
    return None


class RouterAwareSlowAPIMiddleware(BaseHTTPMiddleware):
    """slowapi's middleware with nested-router endpoint resolution.

    Same contract as :class:`slowapi.middleware.SlowAPIMiddleware`, but the
    handler lookup uses :func:`_resolve_endpoint` (see its docstring for the
    fastapi 0.139 ``_IncludedRouter`` gap this closes).
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        from slowapi.middleware import _should_exempt, sync_check_limits

        app = request.app
        limiter: Limiter = app.state.limiter
        if not limiter.enabled:
            return await call_next(request)

        handler = _resolve_endpoint(app.routes, dict(request.scope))
        if _should_exempt(limiter, handler):
            return await call_next(request)

        error_response, should_inject_headers = sync_check_limits(limiter, request, handler, app)
        if error_response is not None:
            return error_response

        response = await call_next(request)
        if should_inject_headers:
            response = limiter._inject_headers(response, request.state.view_rate_limit)
        return response
