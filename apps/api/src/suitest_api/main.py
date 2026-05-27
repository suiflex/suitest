"""FastAPI application factory."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from suitest_api import __version__
from suitest_api.capabilities import build_base_capabilities
from suitest_api.middleware.audit import AuditContextMiddleware
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
    from suitest_api.routers.auth_me import router as auth_me_router
    from suitest_api.routers.capabilities import router as capabilities_router
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.web_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Binds the per-request audit attribution (ip/ua/workspace) so the global
    # SQLAlchemy after_flush listener can write AuditLog rows. Added after CORS so
    # CORS stays the outermost layer; both run before any route handler.
    app.add_middleware(AuditContextMiddleware)

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
    return app


app = create_app()
