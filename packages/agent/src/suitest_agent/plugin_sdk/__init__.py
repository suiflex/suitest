"""suitest_agent.plugin_sdk — M8 custom agent plugin SDK.

Public surface::

    from suitest_agent.plugin_sdk import AgentPluginBase, AgentPluginSpec
    from suitest_agent.plugin_sdk import PLUGIN_REGISTRY, discover_plugins

All other symbols are internal.
"""

from suitest_agent.plugin_sdk.base import AgentPluginBase, AgentPluginSpec
from suitest_agent.plugin_sdk.loader import ENTRY_POINT_GROUP, discover_plugins
from suitest_agent.plugin_sdk.registry import PLUGIN_REGISTRY

__all__ = [
    "ENTRY_POINT_GROUP",
    "PLUGIN_REGISTRY",
    "AgentPluginBase",
    "AgentPluginSpec",
    "discover_plugins",
]
