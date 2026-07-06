"""Lock-in test: agent modules must import at ZERO tier without litellm/langgraph.

All four graph modules use langgraph only inside function bodies (lazy) or under
TYPE_CHECKING (annotation-only), and litellm_router uses litellm only inside
methods — so module-level import of any of these must succeed even when the
'cloud' optional-dependencies extra is absent.
"""

from __future__ import annotations

import importlib


def test_agent_package_imports_without_cloud_deps() -> None:
    # These modules must import at ZERO tier without litellm/langgraph installed.
    for mod in (
        "suitest_agent.providers.base",
        "suitest_agent.providers.litellm_router",
        "suitest_agent.graphs.execution",
        "suitest_agent.graphs.generation",
        "suitest_agent.graphs.conversation",
        "suitest_agent.graphs.diagnosis",
    ):
        importlib.import_module(mod)
