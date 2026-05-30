"""Round-trip + schema-shape tests for the M1d-1 Alembic chain.

These tests boot a fresh ``pgvector/pgvector:pg16`` testcontainer per
**module** (the schema toggles we exercise — column adds, partial unique
indexes, FK with SET NULL — would leak state between tests if we reused a
single container), then drive Alembic through the canonical:

    upgrade head  →  downgrade <pre-m1d>  →  upgrade head

cycle and assert each new column / index / seed row behaves per
plan-05b §M1d-1 acceptance criteria.

Why a module-scoped container instead of session-scoped: the round-trip test
intentionally rolls back the whole M1d chain, then re-applies it. Co-tenant
tests in the rest of the api suite assume ``upgrade head`` was applied
exactly once and never reversed; sharing a container would deadlock that
expectation.

Per-test isolation: every assertion fixture wraps its work in an explicit
async transaction that is rolled back at teardown, so inserts a test makes
to verify e.g. ``mcp_providers.workspace_id IS NULL`` semantics do not leak
into the bundled-MCP verification query in a sibling test.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from alembic.config import Config

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB_PKG_ROOT = _REPO_ROOT / "packages" / "db"

# Last revision *before* the M1d chain — round-trip downgrade target.
_PRE_M1D_REV = "0015_run_step_logs"
# Head once the M1d chain is applied — used to assert linear chain integrity.
_M1D_HEAD_REV = "0024_m1d_09_req_soft_delete"


@pytest.fixture(scope="module")
def _m1d_database_url() -> Iterator[str]:
    """Boot a dedicated pgvector container for the M1d round-trip tests."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from testcontainers.postgres import PostgresContainer

    if not os.environ.get("SUITEST_ENCRYPTION_KEY"):
        os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"\x00" * 32).decode()

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        url = (
            f"postgresql+asyncpg://{container.username}:{container.password}"
            f"@{host}:{port}/{container.dbname}"
        )

        async def _bootstrap() -> None:
            engine = create_async_engine(url, future=True)
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await engine.dispose()

        asyncio.run(_bootstrap())
        yield url


def _alembic_cfg(url: str) -> Config:
    from alembic.config import Config as _Config

    cfg = _Config(str(_DB_PKG_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_DB_PKG_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="module")
def _migrated_head(_m1d_database_url: str) -> Iterator[str]:
    """Apply the full Alembic chain up to head once per module."""
    from alembic import command

    prev = os.environ.get("SUITEST_DATABASE_URL")
    os.environ["SUITEST_DATABASE_URL"] = _m1d_database_url
    try:
        command.upgrade(_alembic_cfg(_m1d_database_url), "head")
        yield _m1d_database_url
    finally:
        if prev is None:
            os.environ.pop("SUITEST_DATABASE_URL", None)
        else:
            os.environ["SUITEST_DATABASE_URL"] = prev


@pytest_asyncio.fixture
async def _engine(_migrated_head: str) -> AsyncIterator[object]:
    """Function-scoped async engine over the migrated container."""
    from sqlalchemy import NullPool
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(_migrated_head, future=True, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def _conn(_engine: object) -> AsyncIterator[object]:
    """Async connection inside an explicit transaction that ALWAYS rolls back.

    Using ``engine.begin()`` would commit on context exit and leak per-test
    rows into the bundled-MCP verification queries (which select ``workspace_id
    IS NULL``). The explicit transaction + finally-rollback keeps the shared
    schema clean while still letting each test do real ``INSERT`` statements.
    """
    conn = await _engine.connect()  # type: ignore[attr-defined]
    trans = await conn.begin()
    try:
        yield conn
    finally:
        await trans.rollback()
        await conn.close()


# ---------------------------------------------------------------------------
# Round-trip: upgrade head → downgrade pre-m1d → upgrade head
# ---------------------------------------------------------------------------


def test_upgrade_all_m1d_revisions_round_trips(_m1d_database_url: str) -> None:
    """``alembic upgrade head`` → ``downgrade <pre-m1d>`` → ``upgrade head`` clean."""
    from alembic import command
    from sqlalchemy import create_engine, text

    prev = os.environ.get("SUITEST_DATABASE_URL")
    os.environ["SUITEST_DATABASE_URL"] = _m1d_database_url
    try:
        cfg = _alembic_cfg(_m1d_database_url)
        # First upgrade — idempotent if the module-scoped fixture already ran.
        command.upgrade(cfg, "head")

        # Use a sync engine for the assertion sweep (Alembic's command API is
        # sync; we keep parity).
        sync_url = _m1d_database_url.replace("+asyncpg", "+psycopg")

        # Round-trip: roll back all 8 M1d revisions, then re-apply them.
        command.downgrade(cfg, _PRE_M1D_REV)

        # After downgrade, bundled seeds must be gone and ``enabled`` column
        # must not exist on mcp_providers.
        eng = create_engine(sync_url, future=True)
        try:
            with eng.connect() as c:
                rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                assert rev == _PRE_M1D_REV
                seeds = c.execute(
                    text(
                        "SELECT COUNT(*) FROM mcp_providers "
                        "WHERE name IN ('jirac-mcp', 'github-mcp')"
                    )
                ).scalar_one()
                assert seeds == 0
                col = c.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='mcp_providers' AND column_name='enabled'"
                    )
                ).first()
                assert col is None
        finally:
            eng.dispose()

        # Re-apply M1d.
        command.upgrade(cfg, "head")

        eng = create_engine(sync_url, future=True)
        try:
            with eng.connect() as c:
                rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                assert rev == _M1D_HEAD_REV
                seeds = c.execute(
                    text(
                        "SELECT COUNT(*) FROM mcp_providers "
                        "WHERE name IN ('jirac-mcp', 'github-mcp')"
                    )
                ).scalar_one()
                assert seeds == 2
        finally:
            eng.dispose()
    finally:
        if prev is None:
            os.environ.pop("SUITEST_DATABASE_URL", None)
        else:
            os.environ["SUITEST_DATABASE_URL"] = prev


# ---------------------------------------------------------------------------
# Schema-shape assertions (run after the module-scoped upgrade head).
# Each test uses the ``_conn`` fixture which always rolls back, so test
# inserts do not leak into the post-upgrade verification queries.
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return uuid.uuid4().hex


async def _make_workspace(conn: object) -> str:
    """Insert a minimal workspace and return its id."""
    from sqlalchemy import text

    wsid = _new_id()
    await conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO workspaces (id, slug, name, region) VALUES (:id, :s, :n, 'ap-southeast-1')"
        ),
        {"id": wsid, "s": f"ws-{wsid[:8]}", "n": "T"},
    )
    return wsid


async def _make_suite(conn: object, wsid: str) -> tuple[str, str]:
    """Insert a project + suite for the given workspace and return (pid, sid)."""
    from sqlalchemy import text

    pid = _new_id()
    await conn.execute(  # type: ignore[attr-defined]
        text("INSERT INTO projects (id, workspace_id, slug, name) VALUES (:id, :ws, :slug, :name)"),
        {"id": pid, "ws": wsid, "slug": f"p-{pid[:6]}", "name": "P"},
    )
    sid = _new_id()
    await conn.execute(  # type: ignore[attr-defined]
        text('INSERT INTO suites (id, project_id, name, "order") VALUES (:id, :p, :n, 0)'),
        {"id": sid, "p": pid, "n": "S"},
    )
    return pid, sid


@pytest.mark.asyncio
async def test_workspaces_strict_zero_validation_defaults_true(_conn: object) -> None:
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    val = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT strict_zero_validation FROM workspaces WHERE id = :id"),
        {"id": wsid},
    )
    assert val.scalar_one() is True


@pytest.mark.asyncio
async def test_workspaces_mcp_routing_overrides_defaults_empty_object(_conn: object) -> None:
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    val = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT mcp_routing_overrides FROM workspaces WHERE id = :id"),
        {"id": wsid},
    )
    assert val.scalar_one() == {}


@pytest.mark.asyncio
async def test_suites_deleted_at_partial_index_exists(_conn: object) -> None:
    """Partial index ``ix_suites_project_active`` is present post-upgrade."""
    from sqlalchemy import text

    row = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT indexname FROM pg_indexes WHERE indexname = 'ix_suites_project_active'")
    )
    assert row.scalar_one() == "ix_suites_project_active"
    # Definition includes the partial predicate.
    defn = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_suites_project_active'")
    )
    assert "deleted_at IS NULL" in defn.scalar_one()


@pytest.mark.asyncio
async def test_test_cases_order_in_suite_defaults_zero(_conn: object) -> None:
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    _, sid = await _make_suite(_conn, wsid)
    cid = _new_id()
    await _conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO test_cases (id, suite_id, public_id, name, source, status, priority) "
            "VALUES (:id, :s, :pub, :n, 'MANUAL', 'ACTIVE', 'P2')"
        ),
        {"id": cid, "s": sid, "pub": f"TC-{cid[:6]}", "n": "C"},
    )
    order = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT order_in_suite FROM test_cases WHERE id = :id"), {"id": cid}
    )
    assert order.scalar_one() == 0


@pytest.mark.asyncio
async def test_test_cases_suite_order_composite_index_exists(_conn: object) -> None:
    from sqlalchemy import text

    row = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT indexname FROM pg_indexes WHERE indexname = 'ix_test_cases_suite_order'")
    )
    assert row.scalar_one() == "ix_test_cases_suite_order"


@pytest.mark.asyncio
async def test_projects_gating_suite_id_fk_on_delete_set_null(_conn: object) -> None:
    """Deleting the gating suite nulls ``projects.gating_suite_id``."""
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    pid, sid = await _make_suite(_conn, wsid)
    await _conn.execute(  # type: ignore[attr-defined]
        text("UPDATE projects SET gating_suite_id = :s WHERE id = :p"),
        {"s": sid, "p": pid},
    )
    await _conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM suites WHERE id = :s"), {"s": sid}
    )
    val = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT gating_suite_id FROM projects WHERE id = :p"), {"p": pid}
    )
    assert val.scalar_one() is None


@pytest.mark.asyncio
async def test_mcp_provider_pins_all_nullable(_conn: object) -> None:
    """Inserting a provider with all four pin columns NULL must not raise."""
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    mid = _new_id()
    await _conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO mcp_providers ("
            "  id, workspace_id, name, kind, endpoint, transport,"
            "  config_json, is_default_for_target, health_status"
            ") VALUES ("
            "  :id, :ws, :n, 'playwright', 'stdio://x', 'stdio',"
            "  '{}'::jsonb, '{}'::jsonb, 'unknown'"
            ")"
        ),
        {"id": mid, "ws": wsid, "n": f"px-{mid[:6]}"},
    )
    pins = await _conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT command_pin, image_pin, version_pin, git_ref FROM mcp_providers WHERE id = :id"
        ),
        {"id": mid},
    )
    assert pins.one() == (None, None, None, None)


@pytest.mark.asyncio
async def test_defects_auto_dedup_partial_unique_scoped_to_system(_engine: object) -> None:
    """uq_defects_auto_dedup blocks duplicate system defects; user-filed dupes pass.

    This test cannot use the rolled-back ``_conn`` fixture because we need to
    observe an ``IntegrityError`` on the SECOND insert — the partial unique
    index only fires once both rows are visible in the same transaction. We
    use a dedicated workspace + run + case scope and clean up at the end.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    conn = await _engine.connect()  # type: ignore[attr-defined]
    trans = await conn.begin()
    try:
        wsid = await _make_workspace(conn)
        pid, sid = await _make_suite(conn, wsid)
        cid = _new_id()
        await conn.execute(
            text(
                "INSERT INTO test_cases (id, suite_id, public_id, name, source, status, priority) "
                "VALUES (:id, :s, :pub, :n, 'MANUAL', 'ACTIVE', 'P2')"
            ),
            {"id": cid, "s": sid, "pub": f"TC-{cid[:6]}", "n": "C"},
        )
        rid = _new_id()
        await conn.execute(
            text(
                "INSERT INTO runs ("
                "  id, public_id, project_id, name, env, trigger, status,"
                "  tier_at_runtime, total_steps, passed_steps, failed_steps"
                ") VALUES ("
                "  :id, :pub, :p, 'r', 'test', 'MANUAL', 'FAIL',"
                "  'ZERO', 1, 0, 1"
                ")"
            ),
            {"id": rid, "pub": f"RUN-{rid[:6]}", "p": pid},
        )

        # First system defect — succeeds.
        await conn.execute(
            text(
                "INSERT INTO defects ("
                "  id, public_id, workspace_id, test_case_id, run_id,"
                "  title, severity, status, agent_diagnosis_kind, created_by"
                ") VALUES ("
                "  :id, :pub, :ws, :tc, :run, 'T', 'MEDIUM', 'OPEN',"
                "  'MANUAL_TRIAGE', 'system'"
                ")"
            ),
            {
                "id": _new_id(),
                "pub": f"SUIT-{_new_id()[:6]}",
                "ws": wsid,
                "tc": cid,
                "run": rid,
            },
        )

        # Second system defect on same (run, case) — partial unique idx rejects.
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO defects ("
                    "  id, public_id, workspace_id, test_case_id, run_id,"
                    "  title, severity, status, agent_diagnosis_kind, created_by"
                    ") VALUES ("
                    "  :id, :pub, :ws, :tc, :run, 'T2', 'MEDIUM', 'OPEN',"
                    "  'MANUAL_TRIAGE', 'system'"
                    ")"
                ),
                {
                    "id": _new_id(),
                    "pub": f"SUIT-{_new_id()[:6]}",
                    "ws": wsid,
                    "tc": cid,
                    "run": rid,
                },
            )

        # That insert aborted the transaction; start a fresh one for the
        # user-filed retry.
        await trans.rollback()
        trans = await conn.begin()

        wsid = await _make_workspace(conn)
        pid, sid = await _make_suite(conn, wsid)
        cid = _new_id()
        await conn.execute(
            text(
                "INSERT INTO test_cases (id, suite_id, public_id, name, source, status, priority) "
                "VALUES (:id, :s, :pub, :n, 'MANUAL', 'ACTIVE', 'P2')"
            ),
            {"id": cid, "s": sid, "pub": f"TC-{cid[:6]}", "n": "C"},
        )
        rid = _new_id()
        await conn.execute(
            text(
                "INSERT INTO runs ("
                "  id, public_id, project_id, name, env, trigger, status,"
                "  tier_at_runtime, total_steps, passed_steps, failed_steps"
                ") VALUES ("
                "  :id, :pub, :p, 'r', 'test', 'MANUAL', 'FAIL',"
                "  'ZERO', 1, 0, 1"
                ")"
            ),
            {"id": rid, "pub": f"RUN-{rid[:6]}", "p": pid},
        )
        # User-filed defect on same (run, case) — partial predicate doesn't apply.
        await conn.execute(
            text(
                "INSERT INTO defects ("
                "  id, public_id, workspace_id, test_case_id, run_id,"
                "  title, severity, status, agent_diagnosis_kind, created_by"
                ") VALUES ("
                "  :id, :pub, :ws, :tc, :run, 'U1', 'MEDIUM', 'OPEN',"
                "  'MANUAL_TRIAGE', 'user_u1'"
                ")"
            ),
            {
                "id": _new_id(),
                "pub": f"SUIT-{_new_id()[:6]}",
                "ws": wsid,
                "tc": cid,
                "run": rid,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO defects ("
                "  id, public_id, workspace_id, test_case_id, run_id,"
                "  title, severity, status, agent_diagnosis_kind, created_by"
                ") VALUES ("
                "  :id, :pub, :ws, :tc, :run, 'U2', 'MEDIUM', 'OPEN',"
                "  'MANUAL_TRIAGE', 'user_u2'"
                ")"
            ),
            {
                "id": _new_id(),
                "pub": f"SUIT-{_new_id()[:6]}",
                "ws": wsid,
                "tc": cid,
                "run": rid,
            },
        )
    finally:
        await trans.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_mcp_providers_workspace_id_nullable_post_m1d(_conn: object) -> None:
    """A bundled provider row (``workspace_id IS NULL``) must be insertable."""
    from sqlalchemy import text

    mid = _new_id()
    await _conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO mcp_providers ("
            "  id, workspace_id, name, kind, endpoint, transport,"
            "  config_json, is_default_for_target, health_status"
            ") VALUES ("
            "  :id, NULL, :n, 'custom', 'stdio://x', 'stdio',"
            "  '{}'::jsonb, '{}'::jsonb, 'unknown'"
            ")"
        ),
        {"id": mid, "n": f"bundle-{mid[:6]}"},
    )
    val = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT workspace_id FROM mcp_providers WHERE id = :id"), {"id": mid}
    )
    assert val.scalar_one() is None


@pytest.mark.asyncio
async def test_mcp_providers_enabled_defaults_true_post_m1d(_conn: object) -> None:
    from sqlalchemy import text

    wsid = await _make_workspace(_conn)
    mid = _new_id()
    await _conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO mcp_providers ("
            "  id, workspace_id, name, kind, endpoint, transport,"
            "  config_json, is_default_for_target, health_status"
            ") VALUES ("
            "  :id, :ws, :n, 'playwright', 'stdio://x', 'stdio',"
            "  '{}'::jsonb, '{}'::jsonb, 'unknown'"
            ")"
        ),
        {"id": mid, "ws": wsid, "n": f"px-{mid[:6]}"},
    )
    val = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT enabled FROM mcp_providers WHERE id = :id"), {"id": mid}
    )
    assert val.scalar_one() is True


@pytest.mark.asyncio
async def test_seeded_jirac_mcp_row_disabled(_conn: object) -> None:
    from sqlalchemy import text

    row = await _conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT enabled, command_pin, workspace_id FROM mcp_providers WHERE name = 'jirac-mcp'"
        )
    )
    assert row.one() == (False, "jirac-mcp@jira-mcp-v2.0.1", None)


@pytest.mark.asyncio
async def test_seeded_github_mcp_row_disabled(_conn: object) -> None:
    from sqlalchemy import text

    row = await _conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT enabled, command_pin, workspace_id FROM mcp_providers WHERE name = 'github-mcp'"
        )
    )
    assert row.one() == (False, "github-mcp-server@v1.1.2", None)


@pytest.mark.asyncio
async def test_bundled_mcp_providers_post_upgrade_query(_conn: object) -> None:
    """The canonical verification query in plan-05b § M1d-1 Verification."""
    from sqlalchemy import text

    rows = await _conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT name, enabled, workspace_id FROM mcp_providers "
            "WHERE workspace_id IS NULL ORDER BY name"
        )
    )
    assert rows.all() == [
        ("github-mcp", False, None),
        ("jirac-mcp", False, None),
    ]


@pytest.mark.asyncio
async def test_no_new_global_public_id_sequences(_conn: object) -> None:
    """Plan-05b § M1d-1 out-of-scope: no new global public-id sequences."""
    from sqlalchemy import text

    rows = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT relname FROM pg_class WHERE relkind='S' AND relname LIKE 'pubid_%global%'")
    )
    assert rows.all() == []


@pytest.mark.asyncio
async def test_no_ix_runs_dedup_recent_index(_conn: object) -> None:
    """Plan-05b § M1d-1 out-of-scope: NOW() predicate index is forbidden."""
    from sqlalchemy import text

    rows = await _conn.execute(  # type: ignore[attr-defined]
        text("SELECT indexname FROM pg_indexes WHERE indexname='ix_runs_dedup_recent'")
    )
    assert rows.all() == []
