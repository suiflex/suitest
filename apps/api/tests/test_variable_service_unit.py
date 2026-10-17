"""Unit tests for VariableService and bulk data update logic using SQLite."""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from suitest_api.deps.scope import TenantContext
from suitest_api.schemas.test_case import (
    BulkAction,
    BulkBatchBindVariableRequest,
    BulkBatchReplaceDataRequest,
    _BulkBatchBindVariablePayload,
    _BulkBatchReplaceDataPayload,
)
from suitest_api.schemas.variable import VariableCreate, VariableUpdate
from suitest_api.services.test_case_service import TestCaseService
from suitest_api.services.variable_service import VariableService
from suitest_db.bootstrap import create_local_schema
from suitest_db.engine import make_engine
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_db.settings import DbSettings
from suitest_shared.domain.enums import CaseSource, Role, TargetKind


@pytest_asyncio.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    os.environ["SUITEST_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
    settings = DbSettings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'test_api_var.db'}")
    engine = make_engine(settings)
    await create_local_schema(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess
    await engine.dispose()


async def _make_ws(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{uuid.uuid4().hex[:8]}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


async def _make_proj(session: AsyncSession, ws: Workspace) -> Project:
    p = Project(workspace_id=ws.id, slug=f"p-{uuid.uuid4().hex[:8]}", name="P")
    session.add(p)
    await session.flush()
    return p


async def _make_suite(session: AsyncSession, proj: Project) -> Suite:
    s = Suite(project_id=proj.id, name="S", order=0)
    session.add(s)
    await session.flush()
    return s


async def _make_user(session: AsyncSession) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        name="U",
        hashed_password="x",
    )
    session.add(u)
    await session.flush()
    return u


@pytest.mark.asyncio
async def test_variable_service_resolution(db_session: AsyncSession) -> None:
    ws = await _make_ws(db_session)
    proj = await _make_proj(db_session, ws=ws)
    suite = await _make_suite(db_session, proj=proj)

    svc = VariableService(db_session)

    # 1. Create workspace variables
    w_plain = await svc.create_workspace_variable(
        ws.id, VariableCreate(key="base_url", value="https://ws.test", isSecret=False)
    )
    assert w_plain.value == "https://ws.test"
    assert w_plain.has_value is True

    w_sec = await svc.create_workspace_variable(
        ws.id, VariableCreate(key="api_key", value="secret-xyz", isSecret=True)
    )
    assert w_sec.value is None  # masked
    assert w_sec.has_value is True

    # 2. Create suite override for base_url
    s_plain = await svc.create_suite_variable(
        suite.id, VariableCreate(key="base_url", value="https://suite.test", isSecret=False)
    )
    assert s_plain.value == "https://suite.test"

    # 3. Resolve hierarchy without secrets (for UI)
    resolved_ui = await svc.resolve_hierarchy(ws.id, suite.id, include_secrets=False)
    ui_map = {item.key: item for item in resolved_ui}
    assert ui_map["base_url"].value == "https://suite.test"
    assert ui_map["base_url"].source_scope == "suite"
    assert ui_map["api_key"].value is None
    assert ui_map["api_key"].is_secret is True
    assert ui_map["api_key"].source_scope == "workspace"

    # 4. Resolve hierarchy with secrets (for runner)
    resolved_runner = await svc.resolve_hierarchy(ws.id, suite.id, include_secrets=True)
    runner_map = {item.key: item for item in resolved_runner}
    assert runner_map["api_key"].value == "secret-xyz"

    # 5. Update workspace variable (verifies refresh and updated_at access)
    updated_ws = await svc.update_workspace_variable(
        ws.id, w_sec.id, VariableUpdate(description="Updated token description")
    )
    assert updated_ws is not None
    assert updated_ws.description == "Updated token description"
    assert updated_ws.updated_at is not None

    # 6. Update suite variable
    updated_suite = await svc.update_suite_variable(
        suite.id, s_plain.id, VariableUpdate(value="https://suite-updated.test")
    )
    assert updated_suite is not None
    assert updated_suite.value == "https://suite-updated.test"
    assert updated_suite.updated_at is not None


@pytest.mark.asyncio
async def test_test_case_service_bulk_batch_replace_and_bind(db_session: AsyncSession) -> None:
    _ = await _make_user(db_session)
    ws = await _make_ws(db_session)
    proj = await _make_proj(db_session, ws=ws)
    suite = await _make_suite(db_session, proj=proj)

    # Seed 2 cases
    case1 = TestCase(
        workspace_id=ws.id,
        suite_id=suite.id,
        public_id="TC-B1",
        name="Case 1",
        source=CaseSource.MANUAL,
    )
    case2 = TestCase(
        workspace_id=ws.id,
        suite_id=suite.id,
        public_id="TC-B2",
        name="Case 2",
        source=CaseSource.MANUAL,
        dataset_rows=[{"values": {"login": "old.corp.com"}}],
    )
    db_session.add_all([case1, case2])
    await db_session.flush()

    step1 = TestStep(
        case_id=case1.id,
        order=1,
        action="Type into input#pass",
        expected="Typed",
        code=json.dumps(
            {"tool": "browser_type", "arguments": {"target": "input#pass", "text": "secret-1"}}
        ),
        data={"selector": "input#pass", "masked": True},
        mcp_provider="playwright-mcp",
        target_kind=TargetKind.FE_WEB,
    )
    step2 = TestStep(
        case_id=case2.id,
        order=1,
        action="Navigate to https://old.corp.com",
        expected="Loaded",
        code=json.dumps({"tool": "browser_navigate", "arguments": {"url": "https://old.corp.com"}}),
        data={"url": "https://old.corp.com"},
        mcp_provider="playwright-mcp",
        target_kind=TargetKind.FE_WEB,
    )
    db_session.add_all([step1, step2])
    await db_session.flush()

    ctx = TenantContext(workspace_id=ws.id, user_id=None, role=Role.QA)
    tc_service = TestCaseService(
        ctx,
        TestCaseRepo(db_session),
        SuiteRepo(db_session),
        ProjectRepo(db_session),
    )

    # 1. Test BATCH_REPLACE_DATA
    replace_req = BulkBatchReplaceDataRequest(
        action=BulkAction.BATCH_REPLACE_DATA,
        ids=[case1.id, case2.id],
        payload=_BulkBatchReplaceDataPayload(
            find_text="old.corp.com",
            replace_with="new.corp.com",
            target_field="all",
        ),
    )
    res_replace = await tc_service.bulk_update(replace_req)
    assert res_replace.affected_count == 1  # Only case2 had old.corp.com
    assert "new.corp.com" in step2.action
    assert case2.dataset_rows[0]["values"]["login"] == "new.corp.com"

    # 2. Test BATCH_BIND_VARIABLE for password
    bind_req = BulkBatchBindVariableRequest(
        action=BulkAction.BATCH_BIND_VARIABLE,
        ids=[case1.id, case2.id],
        payload=_BulkBatchBindVariablePayload(
            target_field="password",
            variable_key="admin_pwd",
        ),
    )
    res_bind = await tc_service.bulk_update(bind_req)
    assert res_bind.affected_count == 1  # Only case1 had password step
    code_parsed = json.loads(step1.code)
    assert code_parsed["arguments"]["text"] == "{{admin_pwd}}"
