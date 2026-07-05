"""Dual-dialect: schema & types must work on SQLite (local mode) and PG."""

import pytest
from sqlalchemy import Column, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_portable_json_roundtrip_sqlite(tmp_path) -> None:
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
async def test_make_engine_sqlite_enforces_foreign_keys(tmp_path) -> None:
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
async def test_create_local_schema_builds_full_schema(tmp_path) -> None:
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
