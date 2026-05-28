"""FastAPI application factory."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from suitest_api import __version__
from suitest_api.capabilities import build_base_capabilities
from suitest_api.middleware.audit import AuditContextMiddleware
from suitest_api.middleware.observability import SpanAttributesMiddleware
from suitest_api.middleware.ratelimit import build_limiter
from suitest_api.observability import setup_observability
from suitest_api.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown hooks.

    Resolves the deployment capabilities from env exactly once and stashes the
    immutable base :class:`~suitest_shared.schemas.capabilities.Capabilities` on
    ``app.state.capabilities``. A misconfigured tier (``ConfigError``) propagates
    here, so the app refuses to boot rather than serving the wrong tier. Also
    records ``app.state.started_at`` for the ``/capabilities/health`` uptime.
    """
    if not getattr(app.state, "settings", None):
        app.state.settings = get_settings()
    app.state.started_at = time.monotonic()
    app.state.capabilities = build_base_capabilities()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the FastAPI app. Pure factory — no side effects at import."""
    from suitest_api.auth.router import router as auth_router
    from suitest_api.routers.analytics import router as analytics_router
    from suitest_api.routers.auth_me import router as auth_me_router
    from suitest_api.routers.capabilities import router as capabilities_router
    from suitest_api.routers.defects import router as defects_router
    from suitest_api.routers.documents import router as documents_router
    from suitest_api.routers.integrations import router as integrations_router
    from suitest_api.routers.projects import router as projects_router
    from suitest_api.routers.requirements import requirements_router, traceability_router
    from suitest_api.routers.runs import router as runs_router
    from suitest_api.routers.suites import router as suites_router
    from suitest_api.routers.test_cases import router as test_cases_router
    from suitest_api.routers.workspaces import router as workspaces_router

    resolved = settings or get_settings()

    app = FastAPI(
        title="Suitest API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings

    # Rate limiter: per-audience buckets (Bearer / cookie / IP) with default 600/min.
    # Stashed on app.state for SlowAPIMiddleware + the 429 handler to pick up.
    # See suitest_api.middleware.ratelimit for the audience key contract.
    app.state.limiter = build_limiter()

    def _ratelimit_exceeded(request: Request, exc: Exception) -> Response:
        """Adapt slowapi's typed handler to Starlette's ``(Request, Exception)`` shape."""
        assert isinstance(exc, RateLimitExceeded)  # narrows for mypy strict
        return _rate_limit_exceeded_handler(request, exc)

    app.add_exception_handler(RateLimitExceeded, _ratelimit_exceeded)

    # ORDER MATTERS — Starlette wraps ``add_middleware`` calls inside-out: the
    # last call becomes the OUTERMOST layer. Target request flow:
    #   CORS → FastAPIInstrumentor (OTel) → SlowAPIMiddleware
    #     → AuditContextMiddleware → SpanAttributesMiddleware → handler.
    #
    # SpanAttributesMiddleware must run AFTER AuditContextMiddleware populates
    # the ContextVar, AND inside the OTel span so ``set_attributes`` lands on the
    # right span — so we add SpanAttributesMiddleware first (innermost), then
    # AuditContextMiddleware, then SlowAPIMiddleware. ``setup_observability()``
    # below installs the FastAPI instrumentor. ``CORSMiddleware`` is added LAST
    # (outermost) so OPTIONS preflights short-circuit before the rate limiter
    # sees them (Issue I2).
    app.add_middleware(SpanAttributesMiddleware, fastapi_app=app)
    # Binds the per-request audit attribution (ip/ua/workspace) so the global
    # SQLAlchemy after_flush listener can write AuditLog rows.
    app.add_middleware(AuditContextMiddleware)
    # Enforces per-audience rate limits (docs/API.md §5). Reads app.state.limiter,
    # short-circuits with 429 + Retry-After when the bucket is exhausted. Exempt
    # routes (``/health``, ``/metrics``, ``/openapi.json``, ``/docs``,
    # ``/capabilities/health``) are wired via :func:`_exempt_anonymous_routes`
    # below — see :mod:`suitest_api.middleware.ratelimit` for the contract.
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — no DB / Redis touch."""
        return {"status": "ok", "service": "api", "version": __version__}

    # Exempt the liveness probe from the rate limiter so Kubernetes probes /
    # uptime monitors don't share the anonymous IP bucket with public traffic
    # (Issue I1). We register the handler name directly rather than using
    # ``@limiter.exempt`` as a decorator — same effect (slowapi's exempt
    # decorator's only side effect is ``_exempt_routes.add(name)``) but keeps
    # the handler's typed signature intact for mypy strict.
    app.state.limiter._exempt_routes.add(f"{health.__module__}.{health.__name__}")

    app.include_router(capabilities_router)
    app.include_router(auth_router)
    app.include_router(auth_me_router)
    app.include_router(workspaces_router)
    app.include_router(projects_router)
    app.include_router(suites_router)
    app.include_router(test_cases_router)
    app.include_router(requirements_router)
    app.include_router(traceability_router)
    app.include_router(runs_router)
    app.include_router(defects_router)
    app.include_router(integrations_router)
    app.include_router(documents_router)
    app.include_router(analytics_router)

    # Observability is wired BEFORE CORS so:
    #   1. FastAPIInstrumentor sees every non-preflight request (CORS short-circuits
    #      OPTIONS before tracing — acceptable, preflights carry no app payload).
    #   2. Prometheus `/metrics` route is appended after all real routes (clean
    #      route order in the router).
    # Skipped automatically when SUITEST_OTEL_DISABLED=true; idempotent via
    # `app.state.otel_setup` guard.
    from suitest_api.auth.db import engine as auth_engine

    setup_observability(app, engine=auth_engine)

    # Exempt anonymous / probe routes (``/openapi.json``, ``/docs``,
    # ``/metrics``, ``/capabilities/health``) AFTER ``setup_observability`` so
    # the ``/metrics`` route exists. ``/health`` is already exempted via the
    # ``@limiter.exempt`` decorator on its inline handler above.
    _exempt_anonymous_routes(app)

    # CORS is added LAST so it becomes the OUTERMOST middleware (Starlette LIFO).
    # OPTIONS preflights then short-circuit before SlowAPIMiddleware sees them —
    # otherwise every preflight would burn one slot in the anonymous IP bucket
    # (Issue I2).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.web_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


def _exempt_anonymous_routes(app: FastAPI) -> None:
    """Mark library-registered anonymous routes as rate-limit exempt (Issue I1).

    ``slowapi``'s :meth:`Limiter.exempt` decorator works by adding the handler's
    ``<module>.<qualname>`` to ``Limiter._exempt_routes``; the middleware then
    skips any request whose resolved handler matches that set. We can't decorate
    handlers registered by libraries (FastAPI's auto-generated ``/openapi.json`` +
    ``/docs``, Prometheus's ``/metrics``), so we walk ``app.routes`` post-wiring
    and insert their handler names directly.

    Endpoints exempted:
      * ``/openapi.json`` — ~75KB; would otherwise burn the anonymous bucket on
        every docs / SDK regen.
      * ``/docs`` — Swagger UI shell; same DoS surface as ``/openapi.json``.
      * ``/metrics`` — Prometheus scrape target; scrapers (every 15-30s) share
        the anonymous IP bucket with public traffic without this.
      * ``/capabilities/health`` — public k8s readiness probe; defined in
        :mod:`suitest_api.routers.capabilities` whose router is shared across
        ``create_app`` calls, so we exempt it here (per-app) rather than at
        import time.
    """
    exempt_paths = {"/openapi.json", "/docs", "/metrics", "/capabilities/health"}
    limiter = app.state.limiter
    for route in app.routes:
        path = getattr(route, "path", None)
        if path not in exempt_paths:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        limiter._exempt_routes.add(name)


# Intentionally NO module-level ``app = create_app()``.
# Importing this module must be side-effect free: a module-level instance would
# (a) trigger OTel BatchSpanProcessor / Prometheus collector registration on
# every import (tooling like ``scripts/export-openapi.py`` would double-instrument
# the process), and (b) leak a background thread per import in dev/test runs.
# Production / dev uvicorn invocations use ``--factory suitest_api.main:create_app``
# (see ``apps/api/src/suitest_api/__main__.py`` and the API Dockerfile CMD).
