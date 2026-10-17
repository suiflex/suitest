"""Unit & integration tests for Workspace & Suite Variables API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb


@pytest.mark.asyncio
async def test_workspace_variables_crud_and_secret_masking(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="vars-qa@example.com")
    ws = await api_db.member_workspace(user, slug="vars-ws", role=Role.QA)

    async with api_db.client(user) as c:
        # 1. Create plain variable
        res_plain = await c.post(
            f"/api/v1/workspaces/{ws.id}/variables",
            json={
                "key": "app_url",
                "value": "https://staging.app.test",
                "isSecret": False,
                "description": "Staging base URL",
            },
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_plain.status_code == 201, res_plain.text
        plain_data = res_plain.json()
        assert plain_data["key"] == "app_url"
        assert plain_data["value"] == "https://staging.app.test"
        assert plain_data["isSecret"] is False
        assert plain_data["hasValue"] is True

        # 2. Create secret variable
        res_sec = await c.post(
            f"/api/v1/workspaces/{ws.id}/variables",
            json={
                "key": "secret_token",
                "value": "my-secret-token-xyz",
                "isSecret": True,
                "description": "Auth bearer token",
            },
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_sec.status_code == 201, res_sec.text
        sec_data = res_sec.json()
        assert sec_data["key"] == "secret_token"
        assert sec_data["isSecret"] is True
        assert sec_data["value"] is None  # Never leak plaintext in public schema
        assert sec_data["hasValue"] is True
        sec_id = sec_data["id"]

        # 3. List workspace variables
        res_list = await c.get(
            f"/api/v1/workspaces/{ws.id}/variables",
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_list.status_code == 200
        items = res_list.json()
        assert len(items) == 2
        sec_item = next(i for i in items if i["key"] == "secret_token")
        assert sec_item["value"] is None
        assert sec_item["hasValue"] is True

        # 4. Update secret variable description
        res_patch = await c.patch(
            f"/api/v1/workspaces/{ws.id}/variables/{sec_id}",
            json={"description": "Updated token description"},
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["description"] == "Updated token description"

        # 5. Delete variable
        res_del = await c.delete(
            f"/api/v1/workspaces/{ws.id}/variables/{plain_data['id']}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_del.status_code == 204

        res_list2 = await c.get(
            f"/api/v1/workspaces/{ws.id}/variables",
            headers={"X-Workspace-Id": ws.id},
        )
        assert len(res_list2.json()) == 1


@pytest.mark.asyncio
async def test_suite_variables_and_hierarchical_resolution(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="suite-vars@example.com")
    ws = await api_db.member_workspace(user, slug="suite-vars-ws", role=Role.ADMIN)

    proj = Project(workspace_id=ws.id, slug="p-var", name="Var Project")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="Regression Suite", order=0)
    await api_db.add_all([suite])

    async with api_db.client(user) as c:
        # Create workspace default variable
        await c.post(
            f"/api/v1/workspaces/{ws.id}/variables",
            json={"key": "base_url", "value": "https://workspace-default.test", "isSecret": False},
            headers={"X-Workspace-Id": ws.id},
        )
        await c.post(
            f"/api/v1/workspaces/{ws.id}/variables",
            json={"key": "admin_user", "value": "global_admin@test.com", "isSecret": False},
            headers={"X-Workspace-Id": ws.id},
        )

        # Create suite override for base_url
        res_suite_var = await c.post(
            f"/api/v1/suites/{suite.id}/variables",
            json={"key": "base_url", "value": "https://suite-override.test", "isSecret": False},
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_suite_var.status_code == 201

        # Fetch resolved hierarchy
        res_resolved = await c.get(
            f"/api/v1/suites/{suite.id}/variables/resolved",
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_resolved.status_code == 200
        resolved_items = {i["key"]: i for i in res_resolved.json()}

        # base_url must come from suite override
        assert resolved_items["base_url"]["value"] == "https://suite-override.test"
        assert resolved_items["base_url"]["sourceScope"] == "suite"
        assert resolved_items["base_url"]["sourceId"] == suite.id

        # admin_user must come from workspace default
        assert resolved_items["admin_user"]["value"] == "global_admin@test.com"
        assert resolved_items["admin_user"]["sourceScope"] == "workspace"
        assert resolved_items["admin_user"]["sourceId"] == ws.id


@pytest.mark.asyncio
async def test_variables_role_gating_viewer_forbidden(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="viewer-vars@example.com")
    ws = await api_db.member_workspace(user, slug="viewer-ws", role=Role.VIEWER)

    async with api_db.client(user) as c:
        # Read is allowed
        res_get = await c.get(
            f"/api/v1/workspaces/{ws.id}/variables",
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_get.status_code == 200

        # Create is forbidden for VIEWER
        res_post = await c.post(
            f"/api/v1/workspaces/{ws.id}/variables",
            json={"key": "test_var", "value": "val", "isSecret": False},
            headers={"X-Workspace-Id": ws.id},
        )
        assert res_post.status_code == 403
