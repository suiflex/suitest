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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.web_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ORDER MATTERS — Starlette wraps `add_middleware` calls inside-out: the last
    # call becomes the OUTERMOST layer. Request flow we want:
    #   OTel (FastAPIInstrumentor) → SlowAPIMiddleware → AuditContextMiddleware
    #     → SpanAttributesMiddleware → CORS → handler.
    # SpanAttributesMiddleware must run AFTER AuditContextMiddleware populates the
    # ContextVar, AND inside the OTel span so set_attributes lands on the right span.
    # So we add SpanAttributesMiddleware first (innermost-of-the-two), then Audit,
    # then SlowAPIMiddleware (so 429s short-circuit before the handler runs but
    # still get traced by OTel), then setup_observability() runs LAST so
    # FastAPIInstrumentor sits outermost.
    app.add_middleware(SpanAttributesMiddleware, fastapi_app=app)
    # Binds the per-request audit attribution (ip/ua/workspace) so the global
    # SQLAlchemy after_flush listener can write AuditLog rows.
    app.add_middleware(AuditContextMiddleware)
    # Enforces per-audience rate limits (docs/API.md §5). Reads app.state.limiter,
    # short-circuits with 429 + Retry-After when the bucket is exhausted.
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — no DB / Redis touch."""
        return {"status": "ok", "service": "api", "version": __version__}

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

    # Observability is wired LAST so:
    #   1. FastAPIInstrumentor becomes the outermost middleware (sees every request).
    #   2. Prometheus `/metrics` route is appended after all real routes (clean
    #      route order in the router).
    # Skipped automatically when SUITEST_OTEL_DISABLED=true; idempotent via
    # `app.state.otel_setup` guard.
    from suitest_api.auth.db import engine as auth_engine

    setup_observability(app, engine=auth_engine)
    return app


app = create_app()
