"""Contract + resolution tests for the /capabilities endpoint (Task 5, plan 5.9).

Most cases drive env via ``monkeypatch.setenv`` and assert the resolved snapshot
returned by ``GET /capabilities`` through a fresh app (so the startup hook re-reads
env). The two "raises" cases assert the app refuses to boot under a misconfigured
tier. ``test_capabilities_workspace_overlay`` boots a pgvector testcontainer,
applies the Alembic chain, seeds a ``WorkspaceCapability`` row, and asserts the DB
overlay wins over an env-ZERO base.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.auth.db import get_async_session
from suitest_api.main import create_app
from suitest_core.capabilities import ConfigError
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import AutonomyLevel, Tier

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PKG_ROOT = _REPO_ROOT / "packages" / "db"


async def _capabilities_via_fresh_app(headers: dict[str, str] | None = None) -> dict[str, object]:
    """Boot a fresh app (re-resolving env at startup) and GET /capabilities."""
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/capabilities", headers=headers or {})
    assert response.status_code == 200
    data: dict[str, object] = response.json()
    return data


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts from a pristine ZERO env unless it opts into providers."""
    for var in (
        "SUITEST_LLM_PROVIDER",
        "SUITEST_LLM_BASE_URL",
        "SUITEST_LLM_API_KEY",
        "SUITEST_LLM_MODEL",
        "SUITEST_EMBEDDINGS_BACKEND",
        "SUITEST_EMBEDDINGS_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.asyncio
async def test_capabilities_zero_default() -> None:
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "ZERO"
    llm = data["llm"]
    assert isinstance(llm, dict)
    assert llm["provider"] == "none"
    features = data["features"]
    assert isinstance(features, dict)
    assert features["manual_tcm"] is True
    assert features["ai_generation"] is False
    autonomy = data["autonomy"]
    assert isinstance(autonomy, dict)
    assert autonomy["default"] == "manual"
    assert autonomy["available"] == ["manual"]


@pytest.mark.asyncio
async def test_capabilities_local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SUITEST_LLM_BASE_URL", "http://localhost:11434")
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "LOCAL"
    features = data["features"]
    assert isinstance(features, dict)
    assert features["ai_generation"] is True
    assert features["ai_diagnose"] is True
    autonomy = data["autonomy"]
    assert isinstance(autonomy, dict)
    assert autonomy["default"] == "assist"


@pytest.mark.asyncio
async def test_capabilities_local_missing_base_url_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "ollama")
    app = create_app()
    with pytest.raises(ConfigError):
        async with LifespanManager(app):
            pass  # pragma: no cover -- startup must raise before this runs


@pytest.mark.asyncio
async def test_capabilities_cloud_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("SUITEST_LLM_API_KEY", "sk-x")
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "CLOUD"
    llm = data["llm"]
    assert isinstance(llm, dict)
    assert llm["provider"] == "anthropic"
    assert llm["is_test_provider"] is False


@pytest.mark.asyncio
async def test_capabilities_cloud_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
    app = create_app()
    with pytest.raises(ConfigError):
        async with LifespanManager(app):
            pass  # pragma: no cover -- startup must raise before this runs


@pytest.mark.asyncio
async def test_capabilities_cloud_bedrock_no_key_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "bedrock")
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "CLOUD"
    features = data["features"]
    assert isinstance(features, dict)
    assert features["ai_generation"] is True


@pytest.mark.asyncio
async def test_capabilities_embeddings_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_EMBEDDINGS_BACKEND", "fastembed")
    data = await _capabilities_via_fresh_app()
    embeddings = data["embeddings"]
    assert isinstance(embeddings, dict)
    assert embeddings["enabled"] is True
    assert embeddings["backend"] == "fastembed"
    assert embeddings["dim"] == 384
    features = data["features"]
    assert isinstance(features, dict)
    assert features["semantic_search"] is True


@pytest.mark.asyncio
async def test_capabilities_embeddings_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_EMBEDDINGS_BACKEND", "openai")
    data = await _capabilities_via_fresh_app()
    embeddings = data["embeddings"]
    assert isinstance(embeddings, dict)
    assert embeddings["enabled"] is True
    assert embeddings["dim"] == 1536


@pytest.mark.asyncio
async def test_capabilities_embeddings_none() -> None:
    data = await _capabilities_via_fresh_app()
    embeddings = data["embeddings"]
    assert isinstance(embeddings, dict)
    assert embeddings["enabled"] is False
    assert embeddings["backend"] == "none"
    features = data["features"]
    assert isinstance(features, dict)
    assert features["semantic_search"] is False


@pytest.mark.asyncio
async def test_capabilities_response_matches_spec_shape_zero() -> None:
    """Snapshot vs the ZERO sample JSON in CAPABILITY_TIERS §10."""
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "ZERO"
    assert data["llm"] == {
        "provider": "none",
        "model": None,
        "base_url": None,
        "is_test_provider": False,
    }
    assert data["embeddings"] == {
        "enabled": False,
        "backend": "none",
        "model": None,
        "dim": None,
    }
    assert data["features"] == {
        "manual_tcm": True,
        "deterministic_runner": True,
        "deterministic_generator_openapi": True,
        "deterministic_generator_recorder": True,
        "deterministic_generator_crawler": True,
        "ai_generation": False,
        "ai_execution_agentic": False,
        "ai_diagnose": False,
        "ai_conversation": False,
        "semantic_search": False,
        "fts_search": True,
        "auto_defect_filing_ai": False,
        "auto_defect_filing_rule": True,
    }
    assert data["autonomy"] == {"available": ["manual"], "default": "manual"}
    assert data["mcpProviders"] == []
    assert isinstance(data["version"], str)


@pytest.mark.asyncio
async def test_capabilities_response_matches_spec_shape_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot vs the CLOUD sample JSON in CAPABILITY_TIERS §10."""
    monkeypatch.setenv("SUITEST_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("SUITEST_LLM_API_KEY", "sk-x")
    monkeypatch.setenv("SUITEST_LLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("SUITEST_EMBEDDINGS_BACKEND", "openai")
    data = await _capabilities_via_fresh_app()
    assert data["tier"] == "CLOUD"
    assert data["llm"] == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "base_url": None,
        "is_test_provider": False,
    }
    assert data["embeddings"] == {
        "enabled": True,
        "backend": "openai",
        "model": "text-embedding-3-small",
        "dim": 1536,
    }
    assert data["features"] == {
        "manual_tcm": True,
        "deterministic_runner": True,
        "deterministic_generator_openapi": True,
        "deterministic_generator_recorder": True,
        "deterministic_generator_crawler": True,
        "ai_generation": True,
        "ai_execution_agentic": True,
        "ai_diagnose": True,
        "ai_conversation": True,
        "semantic_search": True,
        "fts_search": True,
        "auto_defect_filing_ai": True,
        "auto_defect_filing_rule": True,
    }
    assert data["autonomy"] == {
        "available": ["manual", "assist", "semi_auto", "auto"],
        "default": "assist",
    }


@pytest.mark.asyncio
async def test_capabilities_health(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/capabilities/health")
    assert response.status_code == 200
    body = response.json()
    assert body["tier"] == "ZERO"
    assert body["status"] == "ok"
    assert isinstance(body["uptimeSec"], int)
    assert body["uptimeSec"] >= 0


# -- workspace overlay (DB-backed) ----------------------------------------


@pytest.fixture(scope="module")
def _overlay_database_url() -> Iterator[str]:
    """Provide a pgvector database and apply the Alembic chain once."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL as SqlAlchemyUrl
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    if not os.environ.get("SUITEST_ENCRYPTION_KEY"):
        import base64

        os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"\x00" * 32).decode()

    external = os.environ.get("SUITEST_DATABASE_URL")
    if external:
        base_url = make_url(external)
        db_name = f"suitest_overlay_{os.urandom(8).hex()}"
        admin_url = base_url.set(drivername="postgresql+psycopg", database="postgres")
        external_url: SqlAlchemyUrl = base_url.set(
            drivername="postgresql+asyncpg",
            database=db_name,
        )
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))

            async def _bootstrap_external() -> None:
                engine = create_async_engine(external_url, future=True)
                async with engine.begin() as conn:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await engine.dispose()

            asyncio.run(_bootstrap_external())
            rendered = external_url.render_as_string(hide_password=False)
            prev = os.environ.get("SUITEST_DATABASE_URL")
            os.environ["SUITEST_DATABASE_URL"] = rendered
            try:
                cfg = Config(str(_DB_PKG_ROOT / "alembic.ini"))
                cfg.set_main_option("script_location", str(_DB_PKG_ROOT / "alembic"))
                cfg.set_main_option("sqlalchemy.url", rendered)
                command.upgrade(cfg, "head")
            finally:
                if prev is None:
                    os.environ.pop("SUITEST_DATABASE_URL", None)
                else:
                    os.environ["SUITEST_DATABASE_URL"] = prev
            yield rendered
        finally:
            with admin_engine.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity WHERE datname = :db_name"
                    ),
                    {"db_name": db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            admin_engine.dispose()
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        container_url = (
            f"postgresql+asyncpg://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )

        async def _bootstrap() -> None:
            engine = create_async_engine(container_url, future=True)
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await engine.dispose()

        asyncio.run(_bootstrap())

        prev = os.environ.get("SUITEST_DATABASE_URL")
        os.environ["SUITEST_DATABASE_URL"] = container_url
        try:
            cfg = Config(str(_DB_PKG_ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(_DB_PKG_ROOT / "alembic"))
            cfg.set_main_option("sqlalchemy.url", container_url)
            command.upgrade(cfg, "head")
        finally:
            if prev is None:
                os.environ.pop("SUITEST_DATABASE_URL", None)
            else:
                os.environ["SUITEST_DATABASE_URL"] = prev
        yield container_url


@pytest_asyncio.fixture
async def _overlay_session_maker(
    _overlay_database_url: str,
) -> AsyncIterator[object]:
    from sqlalchemy import NullPool
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_overlay_database_url, future=True, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_capabilities_workspace_overlay(_overlay_session_maker: object) -> None:
    """DB CLOUD WorkspaceCapability overrides an env-ZERO base."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    assert isinstance(_overlay_session_maker, async_sessionmaker)
    maker: async_sessionmaker[AsyncSession] = _overlay_session_maker

    async with maker() as seed:
        workspace = Workspace(slug="ws-overlay", name="Overlay WS")
        seed.add(workspace)
        await seed.flush()
        seed.add(
            WorkspaceCapability(
                workspace_id=workspace.id,
                tier=Tier.CLOUD,
                autonomy_level=AutonomyLevel.ASSIST,
                features_json={},
            )
        )
        await seed.commit()
        ws_id = workspace.id

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_async_session] = _override_session
    try:
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                response = await c.get("/capabilities", headers={"X-Workspace-Id": ws_id})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "CLOUD"
    assert data["features"]["ai_generation"] is True
    assert data["autonomy"]["default"] == "assist"

    async with maker() as cleanup:
        ws = await cleanup.get(Workspace, ws_id)
        if ws is not None:
            await cleanup.delete(ws)
            await cleanup.commit()


@pytest.mark.asyncio
async def test_capabilities_workspace_overlay_local_base_url_from_config(
    _overlay_session_maker: object,
) -> None:
    """Active LLMConfig (LOCAL) overlay reads base_url/model from config_json, not env.

    Regression for CAPABILITY_TIERS §11.2: a per-workspace Ollama base_url stored in
    ``LLMConfig.config_json`` must win over the env base (ZERO → base_url None).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    assert isinstance(_overlay_session_maker, async_sessionmaker)
    maker: async_sessionmaker[AsyncSession] = _overlay_session_maker

    async with maker() as seed:
        workspace = Workspace(slug="ws-local-overlay", name="Local Overlay WS")
        seed.add(workspace)
        await seed.flush()
        seed.add(
            WorkspaceCapability(
                workspace_id=workspace.id,
                tier=Tier.LOCAL,
                autonomy_level=AutonomyLevel.ASSIST,
                features_json={},
            )
        )
        seed.add(
            LLMConfig(
                workspace_id=workspace.id,
                provider="ollama",
                model="llama3.1",
                config_json={"base_url": "http://ws-ollama:11434"},
                is_active=True,
            )
        )
        await seed.commit()
        ws_id = workspace.id

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_async_session] = _override_session
    try:
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                response = await c.get("/capabilities", headers={"X-Workspace-Id": ws_id})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "LOCAL"
    llm = data["llm"]
    assert isinstance(llm, dict)
    assert llm["provider"] == "ollama"
    assert llm["model"] == "llama3.1"
    assert llm["base_url"] == "http://ws-ollama:11434"

    async with maker() as cleanup:
        ws = await cleanup.get(Workspace, ws_id)
        if ws is not None:
            await cleanup.delete(ws)
            await cleanup.commit()


@pytest.mark.asyncio
async def test_capabilities_unknown_workspace_returns_base(
    _overlay_session_maker: object,
) -> None:
    """Unknown workspace id → env-derived base (no 404, no overlay)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    assert isinstance(_overlay_session_maker, async_sessionmaker)
    maker: async_sessionmaker[AsyncSession] = _overlay_session_maker

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_async_session] = _override_session
    try:
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                response = await c.get(
                    "/capabilities", headers={"X-Workspace-Id": "does_not_exist"}
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["tier"] == "ZERO"
