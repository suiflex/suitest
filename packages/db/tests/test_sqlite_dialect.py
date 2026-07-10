"""Dual-dialect: schema & types must work on SQLite (local mode) and PG."""

from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_portable_json_roundtrip_sqlite(tmp_path: Path) -> None:
    from suitest_db.types import PortableJSON

    metadata = MetaData()
    t = Table(
        "json_probe",
        metadata,
        Column("id", String(32), primary_key=True),
        Column("payload", PortableJSON),
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.execute(insert(t).values(id="x1", payload={"a": [1, 2], "b": {"c": True}}))
        row = (await conn.execute(select(t.c.payload).where(t.c.id == "x1"))).scalar_one()
    await engine.dispose()
    assert row == {"a": [1, 2], "b": {"c": True}}


@pytest.mark.asyncio
async def test_make_engine_sqlite_enforces_foreign_keys(tmp_path: Path) -> None:
    from sqlalchemy import text
    from suitest_db.engine import make_engine
    from suitest_db.settings import DbSettings

    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    engine = make_engine(settings)
    async with engine.connect() as conn:
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
    await engine.dispose()
    assert fk == 1


@pytest.mark.asyncio
async def test_create_local_schema_builds_full_schema(tmp_path: Path) -> None:
    from sqlalchemy import inspect
    from suitest_db.bootstrap import create_local_schema
    from suitest_db.engine import make_engine
    from suitest_db.settings import DbSettings

    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    await engine.dispose()

    # core lifecycle tables — if these exist, create_all succeeded end to end
    for expected in ("runs", "run_steps", "artifacts"):
        assert expected in tables, f"table {expected} missing; leftover PG-only DDL?"


@pytest.mark.asyncio
async def test_heatmap_cells_on_sqlite(tmp_path: Path) -> None:
    """Local mode: ``heatmap_cells`` must bucket by (day, hour) without PG-only SQL.

    Regression for the analytics heatmap 500 — ``sqlite3.OperationalError: no
    such function: date_trunc`` on the LOCAL/ZERO SQLite backend. The query now
    buckets in Python so it is engine-agnostic.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from suitest_db.bootstrap import create_local_schema
    from suitest_db.engine import make_engine
    from suitest_db.ids import new_id
    from suitest_db.models.project import Project
    from suitest_db.models.run import Run
    from suitest_db.models.workspace import Workspace
    from suitest_db.repositories.runs import RunRepo
    from suitest_db.settings import DbSettings
    from suitest_shared.domain.enums import RunStatus, RunTrigger, Tier

    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'hm.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        ws = Workspace(slug=f"ws-{new_id()}", name="WS")
        session.add(ws)
        await session.flush()
        project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
        session.add(project)
        await session.flush()

        base = datetime(2026, 7, 9, 21, 30, tzinfo=UTC)
        # two runs in the same day+hour, one the next day at a different hour
        for created in (base, base + timedelta(minutes=5), base + timedelta(days=1, hours=2)):
            session.add(
                Run(
                    public_id=f"R-{new_id()}",
                    project_id=project.id,
                    name="Run",
                    trigger=RunTrigger.MANUAL,
                    status=RunStatus.PASS,
                    tier_at_runtime=Tier.ZERO,
                    created_at=created,
                )
            )
        await session.flush()

        cells = await RunRepo(session).heatmap_cells(project.id, base - timedelta(days=2))
    await engine.dispose()

    counts = {(day.date().isoformat(), hour): count for day, hour, count in cells}
    assert counts == {("2026-07-09", 21): 2, ("2026-07-10", 23): 1}


@pytest.mark.asyncio
async def test_public_id_generated_on_sqlite(tmp_path: Path) -> None:
    """Local mode: the before_insert listener must not need the PG plpgsql function.

    Regression for the local-bundle publish 500 — ``sqlite3.OperationalError:
    no such function: generate_public_id`` on the first case insert.
    """
    from factories import make_project, make_suite, make_workspace
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from suitest_db.bootstrap import create_local_schema
    from suitest_db.engine import make_engine
    from suitest_db.models.case import TestCase
    from suitest_db.public_id import generate_public_id, set_workspace_id
    from suitest_db.settings import DbSettings
    from suitest_shared.domain.enums import CaseSource

    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'pubid.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        ws = await make_workspace(session)
        project = await make_project(session, workspace=ws)
        suite = await make_suite(session, project=project)

        pids = []
        for i in range(2):
            case = TestCase(
                suite_id=suite.id, workspace_id=ws.id, name=f"case-{i}", source=CaseSource.MANUAL
            )
            set_workspace_id(case, ws.id)
            session.add(case)
            await session.flush()
            pids.append(case.public_id)
        assert pids == ["TC-1000", "TC-1001"]

        # async service-layer wrapper takes the same SQLite branch
        assert await generate_public_id(session, "R", ws.id) == "R-1000"
        await session.commit()
    await engine.dispose()
