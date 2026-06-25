"""Integration tests for the plugins marketplace endpoints (M9-4).

Uses the real DB (SUITEST_TEST_DATABASE_URL) via the ``api_db`` fixture.
Marketplace GET endpoints are public (no auth required).
POST requires ADMIN/OWNER role.

NOTE: The ``api_db`` fixture TRUNCATEs all tables before each test, so migration
seed data is absent at test runtime.  Tests that verify seeded manifests must
insert them via a seed helper instead.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from api_harness import ApiDb
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_manifests(session: AsyncSession) -> None:
    """Insert the four example manifests that mirror the migration seed."""
    from suitest_db.ids import new_id
    from suitest_db.models.plugin_manifest import PluginManifest

    manifests = [
        PluginManifest(
            id=new_id(),
            name="suitest-xray-reporter",
            display_name="XRay Test Reporter",
            description="Submit results to Xray",
            version="1.0.0",
            plugin_type="reporter",
            author="Suitest Community",
            homepage_url="https://github.com/suiflex/suitest-xray-reporter",
            install_command="pip install suitest-xray-reporter",
            is_official=False,
            is_community=True,
        ),
        PluginManifest(
            id=new_id(),
            name="suitest-qtest-reporter",
            display_name="qTest Reporter",
            description="Push results to qTest Manager",
            version="1.0.0",
            plugin_type="reporter",
            author="Suitest Community",
            homepage_url="https://github.com/suiflex/suitest-qtest-reporter",
            install_command="pip install suitest-qtest-reporter",
            is_official=False,
            is_community=True,
        ),
        PluginManifest(
            id=new_id(),
            name="suitest-asana-adapter",
            display_name="Asana Integration Adapter",
            description="Create Asana tasks from defects",
            version="1.0.0",
            plugin_type="integration_adapter",
            author="Suitest Community",
            homepage_url="https://github.com/suiflex/suitest-asana-adapter",
            install_command="pip install suitest-asana-adapter",
            is_official=False,
            is_community=True,
        ),
        PluginManifest(
            id=new_id(),
            name="suitest-clickup-adapter",
            display_name="ClickUp Integration Adapter",
            description="Create ClickUp tasks from defects",
            version="1.0.0",
            plugin_type="integration_adapter",
            author="Suitest Community",
            homepage_url="https://github.com/suiflex/suitest-clickup-adapter",
            install_command="pip install suitest-clickup-adapter",
            is_official=False,
            is_community=True,
        ),
    ]
    for m in manifests:
        session.add(m)
    await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_anon_client(api_db: ApiDb) -> AsyncGenerator[AsyncClient, None]:
    """Anonymous client with plugin manifests pre-seeded."""
    async with api_db.maker() as session:
        await _seed_manifests(session)
    async with api_db.client(None) as c:
        yield c


@pytest_asyncio.fixture
async def anon_client(api_db: ApiDb) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx client with NO authenticated user (anonymous)."""
    async with api_db.client(None) as c:
        yield c


@pytest_asyncio.fixture
async def admin_client(api_db: ApiDb) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx client authenticated as a workspace ADMIN."""
    from suitest_shared.domain.enums import Role

    user = await api_db.seed_user(email="admin@example.com", name="Admin User")
    workspace = await api_db.seed_workspace(slug="test-ws", name="Test Workspace")
    await api_db.seed_membership(user_id=user.id, workspace_id=workspace.id, role=Role.ADMIN)

    async with api_db.client(user) as c:
        c.headers["x-workspace-id"] = workspace.id
        yield c


@pytest_asyncio.fixture
async def seeded_admin_client(api_db: ApiDb) -> AsyncGenerator[AsyncClient, None]:
    """ADMIN client with plugin manifests pre-seeded."""
    from suitest_shared.domain.enums import Role

    user = await api_db.seed_user(email="admin2@example.com", name="Admin User 2")
    workspace = await api_db.seed_workspace(slug="test-ws-2", name="Test Workspace 2")
    await api_db.seed_membership(user_id=user.id, workspace_id=workspace.id, role=Role.ADMIN)
    async with api_db.maker() as session:
        await _seed_manifests(session)
    async with api_db.client(user) as c:
        c.headers["x-workspace-id"] = workspace.id
        yield c


@pytest_asyncio.fixture
async def viewer_client(api_db: ApiDb) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx client authenticated as a VIEWER (not ADMIN)."""
    from suitest_shared.domain.enums import Role

    user = await api_db.seed_user(email="viewer@example.com", name="Viewer User")
    workspace = await api_db.seed_workspace(slug="viewer-ws", name="Viewer Workspace")
    await api_db.seed_membership(user_id=user.id, workspace_id=workspace.id, role=Role.VIEWER)

    async with api_db.client(user) as c:
        c.headers["x-workspace-id"] = workspace.id
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/plugins/marketplace  — seeded by fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_marketplace_list_returns_seeded_plugins(seeded_anon_client) -> None:  # type: ignore[no-untyped-def]
    """Four seeded manifests must appear in the list."""
    resp = await seeded_anon_client.get("/api/v1/plugins/marketplace")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    names = {p["name"] for p in data}
    assert "suitest-xray-reporter" in names
    assert "suitest-qtest-reporter" in names
    assert "suitest-asana-adapter" in names
    assert "suitest-clickup-adapter" in names


@pytest.mark.asyncio
async def test_marketplace_list_filter_by_type(seeded_anon_client) -> None:  # type: ignore[no-untyped-def]
    """Filtering by plugin_type must return only matching entries."""
    resp = await seeded_anon_client.get("/api/v1/plugins/marketplace?plugin_type=reporter")
    assert resp.status_code == 200
    data = resp.json()
    assert all(p["plugin_type"] == "reporter" for p in data)
    names = {p["name"] for p in data}
    assert "suitest-xray-reporter" in names
    assert "suitest-qtest-reporter" in names
    assert "suitest-asana-adapter" not in names


@pytest.mark.asyncio
async def test_marketplace_list_no_auth_required(seeded_anon_client) -> None:  # type: ignore[no-untyped-def]
    """GET /marketplace must work without any auth headers."""
    resp = await seeded_anon_client.get("/api/v1/plugins/marketplace")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_marketplace_list_empty_when_nothing_seeded(anon_client) -> None:  # type: ignore[no-untyped-def]
    """With no seeded data the list must be empty (not 500)."""
    resp = await anon_client.get("/api/v1/plugins/marketplace")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/v1/plugins/marketplace/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_marketplace_get_by_name(seeded_anon_client) -> None:  # type: ignore[no-untyped-def]
    resp = await seeded_anon_client.get("/api/v1/plugins/marketplace/suitest-xray-reporter")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "suitest-xray-reporter"
    assert data["plugin_type"] == "reporter"
    assert "install_command" in data


@pytest.mark.asyncio
async def test_marketplace_get_not_found(anon_client) -> None:  # type: ignore[no-untyped-def]
    resp = await anon_client.get("/api/v1/plugins/marketplace/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/plugins/marketplace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_plugin_requires_auth(anon_client) -> None:  # type: ignore[no-untyped-def]
    """Unauthenticated POST must be rejected."""
    resp = await anon_client.post(
        "/api/v1/plugins/marketplace",
        json={
            "name": "anon-plugin",
            "display_name": "Anon Plugin",
            "version": "1.0.0",
            "plugin_type": "reporter",
        },
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_submit_plugin_requires_admin(viewer_client) -> None:  # type: ignore[no-untyped-def]
    """VIEWER role must not be allowed to submit plugins."""
    resp = await viewer_client.post(
        "/api/v1/plugins/marketplace",
        json={
            "name": "viewer-plugin",
            "display_name": "Viewer Plugin",
            "version": "1.0.0",
            "plugin_type": "reporter",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_submit_plugin_admin_creates_entry(admin_client) -> None:  # type: ignore[no-untyped-def]
    """ADMIN can submit a new manifest and it becomes retrievable."""
    payload = {
        "name": "my-custom-reporter",
        "display_name": "My Custom Reporter",
        "description": "A test reporter plugin",
        "version": "0.9.0",
        "plugin_type": "reporter",
        "author": "test-author",
        "homepage_url": "https://example.com/my-reporter",
        "install_command": "pip install my-custom-reporter",
    }
    resp = await admin_client.post("/api/v1/plugins/marketplace", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-custom-reporter"
    assert data["is_community"] is True
    assert data["is_official"] is False
    assert "id" in data

    # Must be retrievable by name
    get_resp = await admin_client.get(f"/api/v1/plugins/marketplace/{data['name']}")
    assert get_resp.status_code == 200


@pytest.mark.asyncio
async def test_submit_duplicate_plugin_returns_409(seeded_admin_client) -> None:  # type: ignore[no-untyped-def]
    """Submitting a plugin with a name that already exists must return 409."""
    payload = {
        "name": "suitest-xray-reporter",  # seeded by fixture
        "display_name": "Duplicate XRay",
        "version": "9.9.9",
        "plugin_type": "reporter",
    }
    resp = await seeded_admin_client.post("/api/v1/plugins/marketplace", json=payload)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/v1/plugins/reporters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reporters_list(anon_client) -> None:  # type: ignore[no-untyped-def]
    """Reporter list must include the bundled XRay and qTest reporters."""
    resp = await anon_client.get("/api/v1/plugins/reporters")
    assert resp.status_code == 200
    data = resp.json()
    names = {r["name"] for r in data}
    assert "xray" in names
    assert "qtest" in names


# ---------------------------------------------------------------------------
# GET /api/v1/plugins/integration-adapters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_adapters_list(anon_client) -> None:  # type: ignore[no-untyped-def]
    """Integration adapter list must include Asana and ClickUp."""
    resp = await anon_client.get("/api/v1/plugins/integration-adapters")
    assert resp.status_code == 200
    data = resp.json()
    kinds = {a["kind"] for a in data}
    assert "asana" in kinds
    assert "clickup" in kinds


# ---------------------------------------------------------------------------
# GET /api/v1/plugins/mcp-providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_providers_list_returns_list(anon_client) -> None:  # type: ignore[no-untyped-def]
    """MCP providers endpoint must return a list (empty OK when no plugins installed)."""
    resp = await anon_client.get("/api/v1/plugins/mcp-providers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
