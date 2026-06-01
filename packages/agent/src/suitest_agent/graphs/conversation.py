"""CONVERSATION mode graph (M3-4, docs/AI_AGENT.md §4.6).

chat_turn ─(tool_call?)→ invoke_tool → chat_turn → END.

A turn either answers directly or requests a read-only tool. The tool executor is
injected by the caller (the API wires it to the MCP client); tests pass a stub.
The loop is bounded by ``max_tool_rounds`` to prevent runaway tool cycles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypedDict

from suitest_agent.graphs._util import parse_json_object
from suitest_agent.prompts.loader import load
from suitest_agent.providers.base import ChatMessage, ModelCall

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from suitest_agent.providers.base import LLMProvider

# Executes a tool call: (tool_name, arguments) -> result dict.
ToolExecutor = Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]


class ConversationState(TypedDict, total=False):
    messages: list[dict[str, str]]
    model: str
    seed: int | None
    reply: str
    tool_rounds: int
    pending_tool: dict[str, object] | None


def build_conversation_graph(
    provider: LLMProvider,
    *,
    tool_executor: ToolExecutor | None = None,
    max_tool_rounds: int = 3,
    prompt_version: str = "v1",
) -> CompiledStateGraph[ConversationState]:
    """Compile the CONVERSATION graph bound to ``provider`` (+ optional tools)."""
    from langgraph.graph import END, START, StateGraph

    system_prompt = load("converse", prompt_version)

    async def chat_turn(state: ConversationState) -> ConversationState:
        history = [ChatMessage(role="system", content=system_prompt)]
        for m in state.get("messages", []):
            history.append(ChatMessage(role=m["role"].lower(), content=m["content"]))
        result = await provider.complete(
            ModelCall(model=state.get("model", "default"), messages=history, seed=state.get("seed"))
        )
        obj = parse_json_object(result.content)
        # A turn requests a tool by replying with {"tool": "...", "arguments": {...}}.
        if tool_executor is not None and isinstance(obj.get("tool"), str):
            args = obj.get("arguments", {})
            return {"pending_tool": {"tool": obj["tool"], "arguments": args}, "reply": ""}
        return {"pending_tool": None, "reply": result.content}

    async def invoke_tool(state: ConversationState) -> ConversationState:
        pending = state.get("pending_tool")
        assert pending is not None and tool_executor is not None
        tool = str(pending["tool"])
        args = pending["arguments"] if isinstance(pending["arguments"], dict) else {}
        output = await tool_executor(tool, args)
        messages = list(state.get("messages", []))
        messages.append({"role": "TOOL", "content": f"{tool} -> {output}"})
        return {
            "messages": messages,
            "tool_rounds": state.get("tool_rounds", 0) + 1,
            "pending_tool": None,
        }

    def route(state: ConversationState) -> str:
        if state.get("pending_tool") and state.get("tool_rounds", 0) < max_tool_rounds:
            return "invoke_tool"
        return END

    graph: StateGraph[ConversationState] = StateGraph(ConversationState)
    graph.add_node("chat_turn", chat_turn)
    graph.add_node("invoke_tool", invoke_tool)
    graph.add_edge(START, "chat_turn")
    graph.add_conditional_edges("chat_turn", route, {"invoke_tool": "invoke_tool", END: END})
    graph.add_edge("invoke_tool", "chat_turn")
    return graph.compile()
