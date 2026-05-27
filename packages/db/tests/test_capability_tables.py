"""Tests for LLM config / capability / MCP / generator / prompt / eval / code-export (Task 2k)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.ids import new_id
from suitest_db.models.agent import AgentSession
from suitest_db.models.case import TestCase
from suitest_db.models.code_export import CodeExport
from suitest_db.models.eval_run import EvalRun
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_db.models.prompt_version import PromptVersion
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import (
    AgentSessionKind,
    AutonomyLevel,
    CaseSource,
    McpTransport,
    Tier,
)


async def _workspace(session: AsyncSession) -> Workspace:
    ws = Workspace(slug=f"ws-{new_id()}", name="WS")
    session.add(ws)
    await session.flush()
    return ws


@pytest.mark.asyncio
async def test_workspace_capability_one_per_workspace(session: AsyncSession) -> None:
    ws = await _workspace(session)
    session.add(
        WorkspaceCapability(workspace_id=ws.id, tier=Tier.ZERO, autonomy_level=AutonomyLevel.MANUAL)
    )
    await session.flush()
    session.add(
        WorkspaceCapability(
            workspace_id=ws.id, tier=Tier.CLOUD, autonomy_level=AutonomyLevel.ASSIST
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_llm_config_api_key_roundtrip(session: AsyncSession) -> None:
    ws = await _workspace(session)
    cfg = LLMConfig(
        workspace_id=ws.id, provider="anthropic", model="claude-3", api_key_encrypted="sk-secret"
    )
    session.add(cfg)
    await session.flush()
    cid = cfg.id
    session.expunge_all()

    fetched = await session.scalar(select(LLMConfig).where(LLMConfig.id == cid))
    assert fetched is not None
    assert fetched.api_key_encrypted == "sk-secret"
    assert fetched.is_active is False
    assert fetched.config_json == {}

    raw = await session.scalar(
        text("SELECT api_key_encrypted FROM llm_configs WHERE id = :id").bindparams(id=cid)
    )
    assert raw is not None
    assert b"sk-secret" not in bytes(raw)


@pytest.mark.asyncio
async def test_mcp_provider_unique_name_per_workspace(session: AsyncSession) -> None:
    ws = await _workspace(session)
    session.add(
        McpProvider(
            workspace_id=ws.id,
            name="playwright-mcp",
            kind="playwright",
            endpoint="stdio://playwright",
            transport=McpTransport.STDIO,
        )
    )
    await session.flush()
    session.add(
        McpProvider(
            workspace_id=ws.id,
            name="playwright-mcp",
            kind="playwright",
            endpoint="stdio://other",
            transport=McpTransport.STDIO,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_mcp_provider_secrets_roundtrip(session: AsyncSession) -> None:
    ws = await _workspace(session)
    mcp = McpProvider(
        workspace_id=ws.id,
        name=f"api-{new_id()}",
        kind="api",
        endpoint="sse://api",
        transport=McpTransport.SSE,
        secrets_json_encrypted="token-abc",
    )
    session.add(mcp)
    await session.flush()
    mid = mcp.id
    session.expunge_all()
    fetched = await session.scalar(select(McpProvider).where(McpProvider.id == mid))
    assert fetched is not None
    assert fetched.secrets_json_encrypted == "token-abc"
    assert fetched.health_status == "unknown"


@pytest.mark.asyncio
async def test_prompt_version_unique_name_version(session: AsyncSession) -> None:
    session.add(PromptVersion(name="v1/generate-from-prd", version="1.0.0", content="x", hash="h"))
    await session.flush()
    session.add(PromptVersion(name="v1/generate-from-prd", version="1.0.0", content="y", hash="h2"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_generator_run_default_jsonb_empty(session: AsyncSession) -> None:
    ws = await _workspace(session)
    gen = GeneratorRun(workspace_id=ws.id, source="openapi")
    session.add(gen)
    await session.flush()
    fetched = await session.scalar(select(GeneratorRun).where(GeneratorRun.id == gen.id))
    assert fetched is not None
    assert fetched.input_meta_json == {}
    assert fetched.output_case_ids_json == []


@pytest.mark.asyncio
async def test_eval_run_optional_prompt_version(session: AsyncSession) -> None:
    ws = await _workspace(session)
    ev = EvalRun(workspace_id=ws.id, eval_suite_name="smoke", fixtures_count=5, model_id="claude-3")
    session.add(ev)
    await session.flush()
    fetched = await session.scalar(select(EvalRun).where(EvalRun.id == ev.id))
    assert fetched is not None
    assert fetched.results_json == {}
    assert fetched.prompt_version_id is None


@pytest.mark.asyncio
async def test_code_export_basic(session: AsyncSession) -> None:
    ws = await _workspace(session)
    project = Project(workspace_id=ws.id, slug=f"p-{new_id()}", name="P")
    session.add(project)
    await session.flush()
    suite = Suite(project_id=project.id, name="S")
    session.add(suite)
    await session.flush()
    case = TestCase(
        suite_id=suite.id, public_id=f"TC-{new_id()}", name="C", source=CaseSource.MANUAL
    )
    session.add(case)
    await session.flush()
    ce = CodeExport(case_id=case.id, target="playwright", exported_code_text="await page.goto()")
    session.add(ce)
    await session.flush()
    assert ce.id is not None


@pytest.mark.asyncio
async def test_agent_session_prompt_version_fk(session: AsyncSession) -> None:
    ws = await _workspace(session)
    pv = PromptVersion(name=f"v1/{new_id()}", version="1.0.0", content="x", hash=new_id())
    session.add(pv)
    await session.flush()
    a = AgentSession(
        workspace_id=ws.id,
        kind=AgentSessionKind.GENERATION,
        model_id="claude-3",
        provider="anthropic",
        prompt_version_id=pv.id,
    )
    session.add(a)
    await session.flush()
    aid = a.id
    session.expunge_all()

    fetched = await session.scalar(select(AgentSession).where(AgentSession.id == aid))
    assert fetched is not None
    assert fetched.prompt_version_id == pv.id

    # FK enforced: a bogus prompt_version_id must fail.
    bad = AgentSession(
        workspace_id=ws.id,
        kind=AgentSessionKind.GENERATION,
        model_id="claude-3",
        provider="anthropic",
        prompt_version_id="does-not-exist",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.flush()
