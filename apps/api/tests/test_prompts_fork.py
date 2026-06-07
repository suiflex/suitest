"""Tests for the M5-3 workspace prompt-fork override layer.

Pure: ``loader.list_prompts`` enumerates the bundled defaults. Endpoint: an
ADMIN creates a fork, it shows as the active override, the resolver returns the
forked content (proving the override layer sits on top of the file default), and
deleting it reverts to the default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_agent.prompts.loader import list_prompts, read_prompt
from suitest_api.services.prompt_resolver import resolve_prompt
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from api_harness import ApiDb


def test_list_prompts_includes_known_defaults() -> None:
    names = list_prompts("v1")
    assert "generate-from-prd" in names
    assert "converse" in names
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_fork_overrides_then_delete_reverts(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prompt-admin@example.com")
    ws = await api_db.seed_workspace(slug="prompt-ws", name="Prompt WS")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.ADMIN)
    headers = {"X-Workspace-Id": ws.id}
    forked = "You are a FORKED prompt for this workspace.\n"

    async with api_db.client(user) as c:
        # No fork yet → list reports the default is not overridden.
        before = await c.get("/api/v1/prompts", headers=headers)
        assert before.status_code == 200
        prd_row = next(p for p in before.json()["items"] if p["name"] == "generate-from-prd")
        assert prd_row["hasActiveFork"] is False

        created = await c.post(
            "/api/v1/prompts/generate-from-prd/forks",
            json={"content": forked, "label": "experiment"},
            headers=headers,
        )
        assert created.status_code == 201
        assert created.json()["isActive"] is True
        assert created.json()["forkVersion"] == 1

        after = await c.get("/api/v1/prompts", headers=headers)
        prd_after = next(p for p in after.json()["items"] if p["name"] == "generate-from-prd")
        assert prd_after["hasActiveFork"] is True
        assert prd_after["activeForkVersion"] == 1

    # Resolver returns the forked content (override layer on top of file default).
    async with api_db.maker() as session:
        content, source = await resolve_prompt(
            session, workspace_id=ws.id, prompt_name="generate-from-prd"
        )
        assert content == forked
        assert source == "fork:v1"

    async with api_db.client(user) as c:
        detail = await c.get("/api/v1/prompts/generate-from-prd", headers=headers)
        override_id = detail.json()["forks"][0]["id"]
        deleted = await c.delete(f"/api/v1/prompts/forks/{override_id}", headers=headers)
        assert deleted.status_code == 204

    # After delete, the resolver falls back to the file default.
    async with api_db.maker() as session:
        content, source = await resolve_prompt(
            session, workspace_id=ws.id, prompt_name="generate-from-prd"
        )
        assert content == read_prompt("generate-from-prd", "v1")
        assert source == "file:v1"


@pytest.mark.asyncio
async def test_fork_forbidden_for_qa(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="prompt-qa@example.com")
    ws = await api_db.member_workspace(user, slug="prompt-qa-ws")  # QA default

    async with api_db.client(user) as c:
        res = await c.post(
            "/api/v1/prompts/converse/forks",
            json={"content": "x"},
            headers={"X-Workspace-Id": ws.id},
        )

    assert res.status_code == 403
