"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from suitest_api import __version__
from suitest_api.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown hooks (no-op for M0)."""
    if not getattr(app.state, "settings", None):
        app.state.settings = get_settings()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the FastAPI app. Pure factory — no side effects at import."""
    from suitest_api.auth.router import router as auth_router
    from suitest_api.routers.capabilities import router as capabilities_router

    app = FastAPI(
        title="Suitest API",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe — no DB / Redis touch."""
        return {"status": "ok", "service": "api", "version": __version__}

    app.include_router(capabilities_router)
    app.include_router(auth_router)
    return app


app = create_app()
