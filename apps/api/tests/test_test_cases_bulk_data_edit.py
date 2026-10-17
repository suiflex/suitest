"""Tests for bulk test case data replacement and variable binding."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, Role, TargetKind

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _seed_case_with_steps(
    api_db: ApiDb,
    suite_id: str,
    *,
    public_id: str,
    steps_data: list[tuple[str, str, dict[str, object]]],
    dataset_rows: list[dict[str, object]] | None = None,
) -> TestCase:
    case = TestCase(
        suite_id=suite_id,
        public_id=public_id,
        name=f"Case {public_id}",
        source=CaseSource.MANUAL,
        dataset_rows=dataset_rows,
    )
    await api_db.add_all([case])
    steps: list[TestStep] = []
    for idx, (action, code_str, data_dict) in enumerate(steps_data, start=1):
        step = TestStep(
            case_id=case.id,
            order=idx,
            action=action,
            expected="Element responds",
            code=code_str,
            data=data_dict,
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        )
        steps.append(step)
    await api_db.add_all(steps)
    return case


@pytest.mark.asyncio
async def test_bulk_batch_replace_data(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="replace-data@example.com")
    ws = await api_db.member_workspace(user, slug="replace-data-ws", role=Role.QA)
    proj = Project(workspace_id=ws.id, slug="p-data", name="Data Proj")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="Data Suite", order=0)
    await api_db.add_all([suite])

    case1 = await _seed_case_with_steps(
        api_db,
        suite.id,
        public_id="TC-REP-1",
        steps_data=[
            (
                "Navigate to https://old-app.test",
                json.dumps(
                    {"tool": "browser_navigate", "arguments": {"url": "https://old-app.test"}}
                ),
                {"url": "https://old-app.test"},
            ),
            (
                "Type into input#user",
                json.dumps({"tool": "browser_type", "arguments": {"text": "alice@old.com"}}),
                {"raw_value": "alice@old.com"},
            ),
        ],
    )
    case2 = await _seed_case_with_steps(
        api_db,
        suite.id,
        public_id="TC-REP-2",
        steps_data=[
            (
                "Type into input#email",
                json.dumps({"tool": "browser_type", "arguments": {"text": "bob@old.com"}}),
                {"raw_value": "bob@old.com"},
            ),
        ],
        dataset_rows=[{"values": {"login": "alice@old.com"}}],
    )

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [case1.id, case2.id],
                "action": "batch_replace_data",
                "payload": {
                    "findText": "old.com",
                    "replaceWith": "new.com",
                    "targetField": "all",
                },
            },
            headers={"X-Workspace-Id": ws.id},
        )
        assert resp.status_code == 200, resp.text
        res_data = resp.json()
        assert res_data["updated"] == 2

        # Verify case 1 updated
        detail1 = (
            await c.get(f"/api/v1/test-cases/{case1.id}", headers={"X-Workspace-Id": ws.id})
        ).json()
        assert (
            "https://new.com" in detail1["steps"][0]["action"]
            or "old.com" not in detail1["steps"][1]["action"]
        )
        assert "alice@new.com" in detail1["steps"][1]["code"]

        # Verify case 2 updated including dataset_rows
        detail2 = (
            await c.get(f"/api/v1/test-cases/{case2.id}", headers={"X-Workspace-Id": ws.id})
        ).json()
        assert "bob@new.com" in detail2["steps"][0]["code"]
        assert detail2["datasetRows"][0]["values"]["login"] == "alice@new.com"


@pytest.mark.asyncio
async def test_bulk_batch_bind_variable(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="bind-var@example.com")
    ws = await api_db.member_workspace(user, slug="bind-var-ws", role=Role.QA)
    proj = Project(workspace_id=ws.id, slug="p-bind", name="Bind Proj")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="Bind Suite", order=0)
    await api_db.add_all([suite])

    case1 = await _seed_case_with_steps(
        api_db,
        suite.id,
        public_id="TC-BND-1",
        steps_data=[
            (
                "Type into input[name='password']",
                json.dumps(
                    {
                        "tool": "browser_type",
                        "arguments": {"target": "input[name='password']", "text": "Secret1"},
                    }
                ),
                {"selector": "input[name='password']", "masked": True},
            ),
        ],
    )
    case2 = await _seed_case_with_steps(
        api_db,
        suite.id,
        public_id="TC-BND-2",
        steps_data=[
            (
                "Type into input#pwd",
                json.dumps(
                    {
                        "tool": "browser_type",
                        "arguments": {"target": "input#pwd", "text": "Secret2"},
                    }
                ),
                {"selector": "input#pwd", "masked": True},
            ),
        ],
    )

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [case1.id, case2.id],
                "action": "batch_bind_variable",
                "payload": {
                    "targetField": "password",
                    "variableKey": "admin_pwd",
                },
            },
            headers={"X-Workspace-Id": ws.id},
        )
        assert resp.status_code == 200, resp.text
        res_data = resp.json()
        assert res_data["updated"] == 2

        # Check that both cases now have {{admin_pwd}}
        detail1 = (
            await c.get(f"/api/v1/test-cases/{case1.id}", headers={"X-Workspace-Id": ws.id})
        ).json()
        code1 = json.loads(detail1["steps"][0]["code"])
        assert code1["arguments"]["text"] == "{{admin_pwd}}"

        detail2 = (
            await c.get(f"/api/v1/test-cases/{case2.id}", headers={"X-Workspace-Id": ws.id})
        ).json()
        code2 = json.loads(detail2["steps"][0]["code"])
        assert code2["arguments"]["text"] == "{{admin_pwd}}"
