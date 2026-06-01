"""LangGraph state machines for the 4 agent modes (M3-4, docs/AI_AGENT.md §4).

generation · execution · diagnosis · conversation. Each module exposes a
``build_*_graph(provider, ...)`` factory returning a compiled LangGraph that runs
against any :class:`suitest_agent.providers.base.LLMProvider` (mock in tests,
LiteLLM in CLOUD/LOCAL). ``langgraph`` is imported lazily inside the builders so
ZERO tier never loads it.
"""
