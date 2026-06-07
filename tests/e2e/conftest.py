"""Fixtures for the M1c DoD smoke E2E suite (plan §Task 22).

These fixtures drive the test against a **live** docker-compose stack — the
``api`` + ``runner`` + ``postgres`` + ``redis`` + ``minio`` + ``e2e-nginx``
services are expected to already be running. Normal ``pytest`` runs skip
this directory because every test is marked ``@pytest.mark.e2e`` and the
default selector excludes the marker. CI brings the stack up explicitly in
``.github/workflows/m1c-e2e.yml`` before running ``pytest -m e2e``.

The fixtures intentionally do *not* import application code (no
``suitest_api``/``suitest_db`` imports) — the test is a black-box probe of
the deployed HTTP+WS surface. Database seeding is done over raw ``asyncpg``
so the harness keeps working even if internal package APIs shift.

Environment overrides
---------------------
* ``SUITEST_E2E_API_URL`` — base URL of the api container (default
  ``http://localhost:4000``).
* ``SUITEST_E2E_WS_URL`` — base URL of the WS gateway (default ``ws://localhost:4000``).
* ``SUITEST_E2E_NGINX_URL`` — URL the playwright-mcp steps drive against
  (default ``http://e2e-nginx:80`` when running *inside* docker, or
  ``http://localhost:8090`` when running from the host).
* ``SUITEST_DATABASE_URL`` — asyncpg URL used to seed the case (default
  ``postgresql+asyncpg://suitest:suitest@localhost:5432/suitest``).
* ``SUITEST_AUTH_SECRET`` — must match the api container's secret so the
  test-minted JWT validates.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from httpx import AsyncClient


# Defaults that work against the docker-compose stack from the host machine.
_DEFAULT_API_URL = "http://localhost:4000"
_DEFAULT_WS_URL = "ws://localhost:4000"
_DEFAULT_NGINX_URL = "http://localhost:8090"
_DEFAULT_DB_URL = "postgresql+asyncpg://suitest:suitest@localhost:5432/suitest"


def _env(name: str, default: str) -> str:
    """Return ``os.environ[name]`` or ``default`` when unset / empty."""
    value = os.environ.get(name)
    return value if value else default


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Base URL of the api container, exposed to host on port 4000."""
    return _env("SUITEST_E2E_API_URL", _DEFAULT_API_URL)


@pytest.fixture(scope="session")
def ws_base_url() -> str:
    """Base URL of the WebSocket gateway (same host as api, ``ws://`` scheme)."""
    return _env("SUITEST_E2E_WS_URL", _DEFAULT_WS_URL)


@pytest.fixture(scope="session")
def nginx_test_page_url() -> str:
    """URL of the static test page served by the ``e2e-nginx`` compose service.

    Inside docker-compose this resolves to ``http://e2e-nginx`` (service DNS).
    From the host (local debugging) the service publishes port ``8090``.
    """
    return _env("SUITEST_E2E_NGINX_URL", _DEFAULT_NGINX_URL)


@pytest.fixture(scope="session")
def database_url() -> str:
    """asyncpg URL used to seed the test case directly into Postgres."""
    return _env("SUITEST_DATABASE_URL", _DEFAULT_DB_URL)


@pytest_asyncio.fixture
async def seeded_case(database_url: str, nginx_test_page_url: str) -> dict[str, str]:
    """Insert a workspace + project + suite + case + 5 playwright-mcp steps.

    Returns ``{user_id, workspace_id, project_id, case_id}`` keyed by stable
    names so the smoke test can drive the create-run + WS subscribe flow.
    The seed is idempotent per-run (rows are stamped with a fresh CUID) so
    reruns don't collide on globally-unique columns like ``test_cases.public_id``.
    """
    import json as _json

    import asyncpg

    # asyncpg expects a plain ``postgres://`` DSN (no SQLAlchemy +asyncpg suffix).
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    user_id = str(uuid.uuid4())
    workspace_id = _cuid_like()
    project_id = _cuid_like()
    suite_id = _cuid_like()
    case_id = _cuid_like()
    suffix = uuid.uuid4().hex[:8]

    steps_payload = _playwright_steps(nginx_test_page_url)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO users (id, email, hashed_password, is_active, is_superuser, "
            "is_verified, name) VALUES ($1, $2, $3, true, false, true, $4)",
            uuid.UUID(user_id),
            f"e2e-{suffix}@suitest.local",
            "x",  # not a real credential — test-only placeholder
            "E2E Smoke User",
        )
        await conn.execute(
            "INSERT INTO workspaces (id, slug, name, region, strict_zero_validation, mcp_routing_overrides) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            workspace_id,
            f"e2e-{suffix}",
            f"E2E Workspace {suffix}",
            "ap-southeast-1",
            True,
            "{}",
        )
        await conn.execute(
            "INSERT INTO memberships (id, workspace_id, user_id, role) VALUES ($1, $2, $3, 'OWNER')",
            _cuid_like(),
            workspace_id,
            uuid.UUID(user_id),
        )
        await conn.execute(
            "INSERT INTO projects (id, workspace_id, slug, name, default_mcp_routing) "
            "VALUES ($1, $2, $3, $4, $5::jsonb)",
            project_id,
            workspace_id,
            f"e2e-proj-{suffix}",
            "E2E Project",
            "{}",
        )
        await conn.execute(
            'INSERT INTO suites (id, project_id, name, "order", mcp_routing_overrides) '
            'VALUES ($1, $2, $3, 0, $4::jsonb)',
            suite_id,
            project_id,
            "E2E Suite",
            "{}",
        )
        await conn.execute(
            'INSERT INTO test_cases (id, suite_id, public_id, name, source, status, priority, order_in_suite) '
            "VALUES ($1, $2, $3, $4, 'MANUAL', 'ACTIVE', 'P2', 0)",
            case_id,
            suite_id,
            f"TC-E2E-{suffix.upper()}",
            "Smoke flow",
        )
        for idx, step in enumerate(steps_payload, start=1):
            await conn.execute(
                'INSERT INTO test_steps (id, case_id, "order", action, expected, '
                "mcp_provider, target_kind, code) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                _cuid_like(),
                case_id,
                idx,
                step["action"],
                step["expected"],
                step["mcp_provider"],
                step["target_kind"],
                _json.dumps(step["code"]),
            )
    finally:
        await conn.close()

    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "case_id": case_id,
    }


@pytest_asyncio.fixture
async def auth_token(seeded_case: dict[str, str]) -> str:
    """Mint a real FastAPI-Users JWT via the app's configured strategy."""
    from suitest_api.auth.manager import get_jwt_strategy

    strategy = get_jwt_strategy()
    return await strategy.write_token(_TokenSubject(seeded_case["user_id"]))  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def api_client(
    api_base_url: str, auth_token: str, seeded_case: dict[str, str]
) -> AsyncIterator[AsyncClient]:
    """httpx ``AsyncClient`` bound to the live api with session cookie + workspace header."""
    from httpx import AsyncClient

    headers = {
        "X-Workspace-Id": seeded_case["workspace_id"],
    }
    cookies = {"suitest_session": auth_token}
    async with AsyncClient(
        base_url=api_base_url,
        headers=headers,
        cookies=cookies,
        timeout=30.0,
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TokenSubject:
    """Minimal duck-type for ``JWTStrategy.write_token`` (only ``.id`` is read)."""

    def __init__(self, user_id: str) -> None:
        self.id = user_id



def _cuid_like() -> str:
    """Return a 25-char lowercase id that fits the project's CUID columns.

    The id columns are ``TEXT`` constrained by application code, not by the
    schema, so any unique string of the right shape works for a smoke seed.
    """
    return "c" + uuid.uuid4().hex[:24]


def _playwright_steps(nginx_url: str) -> list[dict[str, object]]:
    """The five playwright-mcp steps the smoke run executes.

    Upstream ``@playwright/mcp`` moved off raw selectors in favour of
    accessibility refs taken from ``browser_snapshot``. Element-bound tools
    (click / type / hover) now require a ``ref`` that the smoke run can't
    pre-compute, so this seed uses five element-less tools that share a
    stable input schema across recent upstream versions: ``browser_navigate``
    (url only) + ``browser_take_screenshot`` (optional ``fullPage``). The
    goal here is to exercise the orchestrator + MCP pool + WS event fan-out
    end-to-end, not to validate every browser tool's input shape.
    """
    return [
        {
            "action": "Navigate",
            "expected": "Page loads",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser_navigate", "arguments": {"url": nginx_url}},
        },
        {
            "action": "Screenshot",
            "expected": "captured",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser_take_screenshot", "arguments": {"fullPage": True}},
        },
        {
            "action": "Navigate (reload)",
            "expected": "Page loads",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser_navigate", "arguments": {"url": nginx_url}},
        },
        {
            "action": "Screenshot (post-reload)",
            "expected": "captured",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser_take_screenshot", "arguments": {"fullPage": False}},
        },
        {
            "action": "Navigate (final)",
            "expected": "Page loads",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser_navigate", "arguments": {"url": nginx_url}},
        },
    ]
