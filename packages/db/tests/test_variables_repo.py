"""Tests for WorkspaceVariable, SuiteVariable, and TestCase dataset support."""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from factories import make_project, make_suite, make_workspace
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_db.bootstrap import create_local_schema
from suitest_db.engine import make_engine
from suitest_db.models.case import TestCase
from suitest_db.repositories.variables import (
    SuiteVariableCreate,
    SuiteVariableRepo,
    WorkspaceVariableCreate,
    WorkspaceVariableRepo,
    WorkspaceVariableUpdate,
)
from suitest_db.settings import DbSettings
from suitest_shared.domain.enums import CaseSource


@pytest_asyncio.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'test_var.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_workspace_variable_crud_and_encryption(db_session: AsyncSession) -> None:
    ws = await make_workspace(db_session)
    repo = WorkspaceVariableRepo(db_session)

    # 1. Plain text variable
    plain_var = await repo.create(
        WorkspaceVariableCreate(
            workspace_id=ws.id,
            key="base_url",
            value="https://staging.suitest.dev",
            is_secret=False,
            description="Base target app URL",
        )
    )
    assert plain_var.id is not None
    assert plain_var.key == "base_url"
    assert plain_var.value == "https://staging.suitest.dev"
    assert plain_var.is_secret is False
    assert plain_var.secret_encrypted is None

    # 2. Secret variable (AES-GCM encrypted via EncryptedBytes)
    secret_var = await repo.create(
        WorkspaceVariableCreate(
            workspace_id=ws.id,
            key="admin_password",
            value="SuperSecret123!",
            is_secret=True,
            description="Admin test password",
        )
    )
    assert secret_var.id is not None
    assert secret_var.key == "admin_password"
    assert secret_var.is_secret is True
    assert secret_var.value == "SuperSecret123!"

    # 3. List by workspace
    vars_list = await repo.list_by_workspace(ws.id)
    assert len(vars_list) == 2
    keys = {v.key for v in vars_list}
    assert keys == {"base_url", "admin_password"}

    # 4. Update variable value
    updated = await repo.update(
        plain_var.id,
        WorkspaceVariableUpdate(value="https://test.suitest.dev"),
    )
    assert updated is not None
    assert updated.value == "https://test.suitest.dev"

    # 5. Delete variable
    deleted = await repo.delete(plain_var.id)
    assert deleted is True
    remaining = await repo.list_by_workspace(ws.id)
    assert len(remaining) == 1
    assert remaining[0].key == "admin_password"


@pytest.mark.asyncio
async def test_workspace_variable_unique_key_per_workspace(db_session: AsyncSession) -> None:
    ws = await make_workspace(db_session)
    repo = WorkspaceVariableRepo(db_session)

    await repo.create(
        WorkspaceVariableCreate(
            workspace_id=ws.id,
            key="api_token",
            value="token-1",
            is_secret=False,
        )
    )

    with pytest.raises(IntegrityError):
        await repo.create(
            WorkspaceVariableCreate(
                workspace_id=ws.id,
                key="api_token",
                value="token-2",
                is_secret=False,
            )
        )


@pytest.mark.asyncio
async def test_suite_variable_crud_and_override(db_session: AsyncSession) -> None:
    ws = await make_workspace(db_session)
    proj = await make_project(db_session, workspace=ws)
    ste = await make_suite(db_session, project=proj)
    repo = SuiteVariableRepo(db_session)

    suite_var = await repo.create(
        SuiteVariableCreate(
            suite_id=ste.id,
            key="base_url",
            value="https://custom-suite.suitest.dev",
            is_secret=False,
            description="Suite-level override",
        )
    )
    assert suite_var.id is not None
    assert suite_var.suite_id == ste.id
    assert suite_var.key == "base_url"
    assert suite_var.value == "https://custom-suite.suitest.dev"

    by_suite = await repo.list_by_suite(ste.id)
    assert len(by_suite) == 1
    assert by_suite[0].key == "base_url"

    # Unique constraint per suite
    with pytest.raises(IntegrityError):
        await repo.create(
            SuiteVariableCreate(
                suite_id=ste.id,
                key="base_url",
                value="https://duplicate.suitest.dev",
                is_secret=False,
            )
        )


@pytest.mark.asyncio
async def test_test_case_dataset_schema_and_rows(db_session: AsyncSession) -> None:
    ws = await make_workspace(db_session)
    proj = await make_project(db_session, workspace=ws)
    ste = await make_suite(db_session, project=proj)

    schema = ["username", "password", "role"]
    rows = [
        {
            "id": "row_admin",
            "name": "Admin Role",
            "is_default": True,
            "enabled": True,
            "values": {
                "username": "admin@suitest.dev",
                "password": "{{admin_password}}",
                "role": "Administrator",
            },
        },
        {
            "id": "row_staff",
            "name": "Staff Role",
            "is_default": False,
            "enabled": True,
            "values": {
                "username": "staff@suitest.dev",
                "password": "{{staff_password}}",
                "role": "Staff",
            },
        },
    ]

    case = TestCase(
        workspace_id=ws.id,
        suite_id=ste.id,
        public_id="TC-DDT-1",
        name="Multi Role Login Test",
        source=CaseSource.MANUAL,
        dataset_schema=schema,
        dataset_rows=rows,
    )
    db_session.add(case)
    await db_session.flush()

    retrieved = await db_session.get(TestCase, case.id)
    assert retrieved is not None
    assert retrieved.dataset_schema == schema
    assert retrieved.dataset_rows == rows
    assert len(retrieved.dataset_rows) == 2
    assert retrieved.dataset_rows[0]["name"] == "Admin Role"
