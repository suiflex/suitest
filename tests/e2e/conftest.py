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
from datetime import UTC, datetime, timedelta
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
def auth_secret() -> str:
    """JWT signing secret shared with the api container.

    Required — there is no sensible default in production code paths. The
    fixture raises ``pytest.skip`` rather than hard-failing so a smoke run
    against a partially-bootstrapped stack reports cleanly.
    """
    secret = os.environ.get("SUITEST_AUTH_SECRET")
    if not secret:
        pytest.skip("SUITEST_AUTH_SECRET not set — E2E requires a real api secret")
    return secret


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
            "INSERT INTO workspaces (id, slug, name, region) VALUES ($1, $2, $3, $4)",
            workspace_id,
            f"e2e-{suffix}",
            f"E2E Workspace {suffix}",
            "ap-southeast-1",
        )
        await conn.execute(
            "INSERT INTO memberships (id, workspace_id, user_id, role) VALUES ($1, $2, $3, 'OWNER')",
            _cuid_like(),
            workspace_id,
            uuid.UUID(user_id),
        )
        await conn.execute(
            "INSERT INTO projects (id, workspace_id, slug, name) VALUES ($1, $2, $3, $4)",
            project_id,
            workspace_id,
            f"e2e-proj-{suffix}",
            "E2E Project",
        )
        await conn.execute(
            'INSERT INTO suites (id, project_id, name, "order") VALUES ($1, $2, $3, 0)',
            suite_id,
            project_id,
            "E2E Suite",
        )
        await conn.execute(
            "INSERT INTO test_cases (id, suite_id, public_id, name, source) "
            "VALUES ($1, $2, $3, $4, 'MANUAL')",
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


@pytest.fixture
def auth_token(auth_secret: str, seeded_case: dict[str, str]) -> str:
    """Mint a FastAPI-Users-compatible JWT for the seeded test user.

    Mirrors :func:`fastapi_users.authentication.JWTStrategy.write_token` so
    the api container accepts the token via the same ``get_jwt_strategy``
    code path the WS gateway uses. We use the ``audience`` claim
    ``fastapi-users:auth`` which is the library default.
    """
    import jwt as pyjwt

    now = datetime.now(tz=UTC)
    payload = {
        "sub": seeded_case["user_id"],
        "aud": ["fastapi-users:auth"],
        "exp": int((now + timedelta(minutes=30)).timestamp()),
        "iat": int(now.timestamp()),
    }
    return pyjwt.encode(payload, auth_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def api_client(
    api_base_url: str, auth_token: str, seeded_case: dict[str, str]
) -> AsyncIterator[AsyncClient]:
    """httpx ``AsyncClient`` bound to the live api with auth + workspace headers."""
    from httpx import AsyncClient

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-Workspace-Id": seeded_case["workspace_id"],
    }
    async with AsyncClient(base_url=api_base_url, headers=headers, timeout=30.0) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cuid_like() -> str:
    """Return a 25-char lowercase id that fits the project's CUID columns.

    The id columns are ``TEXT`` constrained by application code, not by the
    schema, so any unique string of the right shape works for a smoke seed.
    """
    return "c" + uuid.uuid4().hex[:24]


def _playwright_steps(nginx_url: str) -> list[dict[str, object]]:
    """The five playwright-mcp steps the smoke run executes.

    Mirrors the example in plan §22.1 but adapted to the bundled
    ``playwright-mcp`` tool names exposed by ``packages/mcp/bundled/playwright``.
    """
    return [
        {
            "action": "Navigate",
            "expected": "Page loads",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser.navigate", "arguments": {"url": nginx_url}},
        },
        {
            "action": "Screenshot",
            "expected": "captured",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser.screenshot", "arguments": {"fullPage": True}},
        },
        {
            "action": "Assert heading",
            "expected": "Hello Suitest",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {
                "tool": "browser.assert_text",
                "arguments": {"selector": "#hero", "contains": "Hello Suitest"},
            },
        },
        {
            "action": "Type",
            "expected": "filled",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {
                "tool": "browser.type",
                "arguments": {"selector": "#q", "text": "hi"},
            },
        },
        {
            "action": "Click",
            "expected": "clicked",
            "mcp_provider": "playwright-mcp",
            "target_kind": "FE_WEB",
            "code": {"tool": "browser.click", "arguments": {"selector": "#go"}},
        },
    ]
