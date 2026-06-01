"""M3-4 LangGraph state-machine tests — driven by the deterministic MockProvider."""

from __future__ import annotations

import json

import pytest
from suitest_agent.graphs.conversation import build_conversation_graph
from suitest_agent.graphs.diagnosis import build_diagnosis_graph
from suitest_agent.graphs.execution import build_execution_graph
from suitest_agent.graphs.generation import build_generation_graph
from suitest_agent.providers.base import CompletionResult
from suitest_agent.providers.mock import MockProvider


def _scripted(*payloads: str) -> MockProvider:
    return MockProvider(scripted=[CompletionResult(content=p, model="mock-1") for p in payloads])


@pytest.mark.asyncio
async def test_generation_parses_drafts() -> None:
    cases = {
        "cases": [
            {"title": "Login happy path", "priority": "P0", "steps": []},
            {"title": "Login wrong password", "priority": "P1", "steps": []},
        ]
    }
    graph = build_generation_graph(_scripted(json.dumps(cases)))
    out = await graph.ainvoke({"input_text": "User can log in", "model": "mock-1"})
    assert len(out["draft_cases"]) == 2
    assert out["draft_cases"][0]["title"] == "Login happy path"
    assert out["error"] is None


@pytest.mark.asyncio
async def test_generation_empty_input_short_circuits() -> None:
    graph = build_generation_graph(MockProvider())
    out = await graph.ainvoke({"input_text": "   ", "model": "mock-1"})
    assert out["error"] == "EMPTY_INPUT"
    assert out["draft_cases"] == []


@pytest.mark.asyncio
async def test_execution_mixes_deterministic_and_translated() -> None:
    translate = json.dumps({"tool": "click", "arguments": {"selector": "#buy"}})
    graph = build_execution_graph(_scripted(translate))
    out = await graph.ainvoke(
        {
            "steps": [
                {"action": "seed db", "code": "await pg.exec('INSERT ...')"},
                {"action": "click buy", "code": None, "mcp_provider": "playwright-mcp"},
            ],
            "tier_has_llm": True,
            "model": "mock-1",
        }
    )
    plans = out["plans"]
    assert plans[0]["mode"] == "deterministic"
    assert plans[1]["mode"] == "agentic_translated"
    assert plans[1]["tool"] == "click"


@pytest.mark.asyncio
async def test_execution_zero_tier_blocks_agentic_step() -> None:
    graph = build_execution_graph(MockProvider())
    out = await graph.ainvoke(
        {
            "steps": [{"action": "click buy", "code": None}],
            "tier_has_llm": False,
            "model": "mock-1",
        }
    )
    assert out["plans"][0]["mode"] == "error"
    assert out["plans"][0]["error"] == "NO_LLM_FOR_AGENTIC_STEP"


@pytest.mark.asyncio
async def test_diagnosis_classifies_into_enum() -> None:
    payload = json.dumps(
        {
            "category": "REGRESSION",
            "confidence": 0.82,
            "root_cause": "Null check removed in commit abc123",
            "suggested_fix": "Restore guard",
            "rerun_recommended": False,
        }
    )
    graph = build_diagnosis_graph(_scripted(payload))
    out = await graph.ainvoke({"evidence": "step 3 failed: NPE", "model": "mock-1"})
    assert out["diagnosis"].category == "REGRESSION"
    assert out["diagnosis"].confidence == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_diagnosis_empty_evidence_falls_back() -> None:
    graph = build_diagnosis_graph(MockProvider())
    out = await graph.ainvoke({"evidence": "", "model": "mock-1"})
    assert out["diagnosis"].category == "MANUAL_TRIAGE"
    assert out["diagnosis"].confidence == 0.0


@pytest.mark.asyncio
async def test_conversation_direct_reply() -> None:
    graph = build_conversation_graph(_scripted("Here are your 3 failing cases."))
    out = await graph.ainvoke(
        {"messages": [{"role": "USER", "content": "what's failing?"}], "model": "mock-1"}
    )
    assert out["reply"] == "Here are your 3 failing cases."
    assert out["pending_tool"] is None


@pytest.mark.asyncio
async def test_conversation_tool_round_then_reply() -> None:
    calls: list[str] = []

    async def executor(tool: str, args: dict[str, object]) -> dict[str, object]:
        calls.append(tool)
        return {"count": 3}

    graph = build_conversation_graph(
        _scripted(json.dumps({"tool": "list_failing", "arguments": {}}), "You have 3 failing."),
        tool_executor=executor,
    )
    out = await graph.ainvoke(
        {"messages": [{"role": "USER", "content": "how many fail?"}], "model": "mock-1"}
    )
    assert calls == ["list_failing"]
    assert out["reply"] == "You have 3 failing."
    assert out["tool_rounds"] == 1


@pytest.mark.asyncio
async def test_translate_single_step_returns_envelope() -> None:
    from suitest_agent.graphs.execution import translate_single_step

    payload = json.dumps({"tool": "browser_click", "arguments": {"selector": "#buy"}})
    out = await translate_single_step(_scripted(payload), model="mock-1", action="click buy")
    assert out == {"tool": "browser_click", "arguments": {"selector": "#buy"}}


@pytest.mark.asyncio
async def test_translate_single_step_null_tool_returns_none() -> None:
    from suitest_agent.graphs.execution import translate_single_step

    out = await translate_single_step(MockProvider(), model="mock-1", action="vague action")
    assert out is None
