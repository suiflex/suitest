"""Demonstration and regression test using TC-6007 for Data-Driven Testing (DDT).

Validates:
1. TC-6007 step parameterization via batch replace & variable binding.
2. Retention of selectors (e.g. #login-username, #login-password).
3. Parameterization of assertions and expected outcomes.
4. Multi-role matrix resolution (Admin, Manager, Staff) via VariableResolver.
5. Export to pytest @pytest.mark.parametrize.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.schemas.test_case import (
    BulkAction,
    BulkBatchBindVariablePayload,
    BulkBatchBindVariableRequest,
    BulkBatchReplaceDataPayload,
    BulkBatchReplaceDataRequest,
    TestCaseUpdate,
)
from suitest_api.services.code_export_service import generate_export
from suitest_api.services.test_case_service import TestCaseService
from suitest_db.models.case import TestCase, TestStep
from suitest_runner.executors.variable_resolver import VariableResolver
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind


def _build_tc_6007() -> TestCase:
    now = datetime.now(UTC)
    case = TestCase(
        id="7801b9232c2942ce8c9b75ba6331fe56",
        suite_id="suite-auth-1",
        public_id="TC-6007",
        name="Auth Login - Manual Keystroke Entry (Admin Credentials)",
        title="Auth Login - Manual Keystroke Entry (Admin Credentials)",
        description="Verify user manually typing admin credentials into inputs and logging in.",
        source=CaseSource.MANUAL,
        status=CaseStatus.ACTIVE,
        priority=Priority.P1,
        created_at=now,
        updated_at=now,
    )
    case.steps = [
        TestStep(
            id="s1",
            case_id=case.id,
            order=1,
            action="Navigate to http://localhost:3000/auth",
            expected="Sanctuary Access Portal is loaded",
            code=json.dumps(
                {"tool": "browser_navigate", "arguments": {"url": "http://localhost:3000/auth"}}
            ),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
        TestStep(
            id="s2",
            case_id=case.id,
            order=2,
            action="Type admin username manually into #login-username",
            expected="Input username shows admin",
            code=json.dumps(
                {
                    "tool": "browser_type",
                    "arguments": {"target": "#login-username", "text": "admin"},
                }
            ),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
        TestStep(
            id="s3",
            case_id=case.id,
            order=3,
            action="Type vault123 password manually into #login-password",
            expected="Input password shows vault123",
            code=json.dumps(
                {
                    "tool": "browser_type",
                    "arguments": {"target": "#login-password", "text": "vault123"},
                }
            ),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
        TestStep(
            id="s4",
            case_id=case.id,
            order=4,
            action="Click SIGN IN TO BUNKER submit button",
            expected="Authentication succeeds and user is logged in",
            code=json.dumps(
                {"tool": "browser_click", "arguments": {"target": "#login-submit-button"}}
            ),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
        TestStep(
            id="s5",
            case_id=case.id,
            order=5,
            action="Wait for user display name to show admin",
            expected="Display name shows admin and role badge is visible",
            code=json.dumps({"tool": "browser_wait_for", "arguments": {"text": "admin"}}),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
        TestStep(
            id="s6",
            case_id=case.id,
            order=6,
            action="Capture screenshot of successful manual admin login",
            expected="Screenshot captures active session from manual credential entry",
            code=json.dumps({"tool": "browser_take_screenshot", "arguments": {}}),
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        ),
    ]
    return case


@pytest.mark.asyncio
async def test_tc_6007_flexible_test_data_transformation():
    """Verify TC-6007 can be made flexible with batch binding and replacement."""
    case = _build_tc_6007()

    ctx = AsyncMock(workspace_id="ws-1", user_id=None)
    repo = AsyncMock()
    repo.session = AsyncMock()
    repo.list_active_by_ids = AsyncMock(return_value=[case])
    repo.workspace_ids_for = AsyncMock(return_value={case.id: "ws-1"})
    suite_repo = AsyncMock()
    project_repo = AsyncMock()
    service = TestCaseService(ctx=ctx, repo=repo, suite_repo=suite_repo, project_repo=project_repo)

    # 1. Bind password to variable {{ADMIN_PASSWORD}}
    req_pwd = BulkBatchBindVariableRequest(
        action=BulkAction.BATCH_BIND_VARIABLE,
        ids=[case.id],
        payload=BulkBatchBindVariablePayload(
            targetField="password",
            variableKey="ADMIN_PASSWORD",
        ),
    )
    res_pwd = await service.bulk_update(req_pwd)
    assert res_pwd.affected_count == 1

    # Verify password step was parameterized while retaining selector and expected
    step3 = case.steps[2]
    parsed_s3 = json.loads(step3.code)
    assert parsed_s3["arguments"]["text"] == "{{ADMIN_PASSWORD}}"
    assert parsed_s3["arguments"]["target"] == "#login-password"
    assert "{{ADMIN_PASSWORD}}" in step3.action
    assert "{{ADMIN_PASSWORD}}" in step3.expected

    # 2. Bind URL to variable {{AUTH_URL}}
    req_url = BulkBatchBindVariableRequest(
        action=BulkAction.BATCH_BIND_VARIABLE,
        ids=[case.id],
        payload=BulkBatchBindVariablePayload(
            targetField="url",
            variableKey="AUTH_URL",
        ),
    )
    res_url = await service.bulk_update(req_url)
    assert res_url.affected_count == 1

    step1 = case.steps[0]
    parsed_s1 = json.loads(step1.code)
    assert parsed_s1["arguments"]["url"] == "{{AUTH_URL}}"
    assert step1.action == "Navigate to {{AUTH_URL}}"

    # 3. Replace hardcoded "admin" with "{{USER_ROLE}}"
    req_replace = BulkBatchReplaceDataRequest(
        action=BulkAction.BATCH_REPLACE_DATA,
        ids=[case.id],
        payload=BulkBatchReplaceDataPayload(
            findText="admin",
            replaceWith="{{USER_ROLE}}",
            targetField="all",
        ),
    )
    res_replace = await service.bulk_update(req_replace)
    assert res_replace.affected_count == 1

    step2 = case.steps[1]
    parsed_s2 = json.loads(step2.code)
    assert parsed_s2["arguments"]["text"] == "{{USER_ROLE}}"
    assert "{{USER_ROLE}}" in step2.action
    assert "{{USER_ROLE}}" in step2.expected

    step5 = case.steps[4]
    parsed_s5 = json.loads(step5.code)
    assert parsed_s5["arguments"]["text"] == "{{USER_ROLE}}"
    assert "{{USER_ROLE}}" in step5.action
    assert "{{USER_ROLE}}" in step5.expected

    # 4. Attach multi-role DDT matrix to TC-6007
    case.dataset_schema = ["AUTH_URL", "USER_ROLE", "ADMIN_PASSWORD"]
    case.dataset_rows = [
        {
            "id": "row-1",
            "name": "Admin Role",
            "enabled": True,
            "values": {
                "AUTH_URL": "http://localhost:3000/auth",
                "USER_ROLE": "admin",
                "ADMIN_PASSWORD": "vault123",
            },
        },
        {
            "id": "row-2",
            "name": "Manager Role",
            "enabled": True,
            "values": {
                "AUTH_URL": "http://localhost:3000/auth",
                "USER_ROLE": "manager",
                "ADMIN_PASSWORD": "mgr_password",
            },
        },
        {
            "id": "row-3",
            "name": "Staff Role",
            "enabled": True,
            "values": {
                "AUTH_URL": "http://localhost:3000/auth",
                "USER_ROLE": "staff",
                "ADMIN_PASSWORD": "staff_password",
            },
        },
    ]

    # 5. Verify VariableResolver resolves different rows without code changes
    resolver_admin = VariableResolver(dataset_row=case.dataset_rows[0])
    resolver_manager = VariableResolver(dataset_row=case.dataset_rows[1])
    resolver_staff = VariableResolver(dataset_row=case.dataset_rows[2])

    # Admin execution interpolation
    admin_s2_args = resolver_admin.interpolate_data(parsed_s2["arguments"])
    admin_s3_args = resolver_admin.interpolate_data(parsed_s3["arguments"])
    assert admin_s2_args["text"] == "admin"
    assert admin_s3_args["text"] == "vault123"

    # Manager execution interpolation
    manager_s2_args = resolver_manager.interpolate_data(parsed_s2["arguments"])
    manager_s3_args = resolver_manager.interpolate_data(parsed_s3["arguments"])
    assert manager_s2_args["text"] == "manager"
    assert manager_s3_args["text"] == "mgr_password"

    # Staff execution interpolation
    staff_s2_args = resolver_staff.interpolate_data(parsed_s2["arguments"])
    staff_s3_args = resolver_staff.interpolate_data(parsed_s3["arguments"])
    assert staff_s2_args["text"] == "staff"
    assert staff_s3_args["text"] == "staff_password"

    # 6. Verify Pytest export produces @pytest.mark.parametrize for TC-6007
    export_row = generate_export(case, case.steps, "selenium")
    code_text = export_row.exported_code_text

    assert '@pytest.mark.parametrize("AUTH_URL, USER_ROLE, ADMIN_PASSWORD"' in code_text
    assert "('http://localhost:3000/auth', 'admin', 'vault123')" in code_text
    assert "('http://localhost:3000/auth', 'manager', 'mgr_password')" in code_text
    assert "('http://localhost:3000/auth', 'staff', 'staff_password')" in code_text
    assert (
        "def test_auth_login_manual_keystroke_entry_admin_credentials(AUTH_URL, USER_ROLE, ADMIN_PASSWORD):"
        in code_text
    )


@pytest.mark.asyncio
async def test_tc_6007_service_update_persists_dataset() -> None:
    case = _build_tc_6007()
    ctx = AsyncMock(workspace_id="ws-1", user_id=None)
    repo = AsyncMock()
    repo.session = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=case)
    repo.get_steps = AsyncMock(return_value=case.steps)
    repo.get_tags = AsyncMock(return_value=[])
    suite_repo = AsyncMock()
    project_repo = AsyncMock()
    service = TestCaseService(ctx=ctx, repo=repo, suite_repo=suite_repo, project_repo=project_repo)
    service._suite_in_scope = AsyncMock(return_value=True)

    update_body = TestCaseUpdate(
        datasetSchema=["AUTH_URL", "USER_ROLE", "ADMIN_PASSWORD"],
        datasetRows=[
            {
                "id": "row-1",
                "name": "Admin Role",
                "enabled": True,
                "values": {
                    "AUTH_URL": "http://localhost:3000/auth",
                    "USER_ROLE": "admin",
                    "ADMIN_PASSWORD": "vault123",
                },
            },
            {
                "id": "row-2",
                "name": "Manager Role",
                "enabled": True,
                "values": {
                    "AUTH_URL": "http://localhost:3000/auth",
                    "USER_ROLE": "manager",
                    "ADMIN_PASSWORD": "mgr_password",
                },
            },
        ],
    )

    result = await service.update(case.id, update_body, if_unmodified_since=None)
    assert result is not None
    assert case.dataset_schema == ["AUTH_URL", "USER_ROLE", "ADMIN_PASSWORD"]
    assert len(case.dataset_rows) == 2
    assert result.detail.dataset_schema == ["AUTH_URL", "USER_ROLE", "ADMIN_PASSWORD"]
    assert len(result.detail.dataset_rows) == 2
