"""In-process registry of loaded agent plugins (M8-3).

Populated at application startup by calling :func:`discover_plugins` and then
:meth:`PluginRegistry.register` for each discovered class.  The module-level
singleton :data:`PLUGIN_REGISTRY` is the canonical lookup point.

Usage::

    from suitest_agent.plugin_sdk.registry import PLUGIN_REGISTRY

    cls = PLUGIN_REGISTRY.get("security-agent")
    if cls is not None:
        instance = cls()
"""

from __future__ import annotations

import logging

from suitest_agent.plugin_sdk.base import AgentPluginBase, AgentPluginSpec

_log = logging.getLogger(__name__)


class PluginRegistry:
    """Thread-safe in-process registry mapping plugin name → plugin class.

    Duplicate registrations (same ``spec.name``) replace the previous entry and
    emit a warning — this lets re-loadable environments (test suites, hot-reload)
    update plugins without restarting the process.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, type[AgentPluginBase]] = {}

    def register(self, plugin_cls: type[AgentPluginBase]) -> None:
        """Register a plugin class.

        Raises :class:`TypeError` when ``plugin_cls`` lacks a valid ``spec``
        attribute.  Overwrites any previously registered plugin with the same
        name (with a warning).
        """
        if not hasattr(plugin_cls, "spec") or not isinstance(plugin_cls.spec, AgentPluginSpec):
            raise TypeError(
                f"Plugin class {plugin_cls!r} must have a class-level "
                f"'spec: AgentPluginSpec' attribute"
            )
        name = plugin_cls.spec.name
        if name in self._plugins:
            _log.warning(
                "PluginRegistry: replacing existing plugin %r with %r",
                name,
                plugin_cls.__qualname__,
            )
        self._plugins[name] = plugin_cls
        _log.debug("PluginRegistry: registered plugin %r", name)

    def get(self, name: str) -> type[AgentPluginBase] | None:
        """Return the plugin class for ``name``, or ``None`` if not registered."""
        return self._plugins.get(name)

    def list_all(self) -> list[AgentPluginSpec]:
        """Return specs for every registered plugin, sorted by name."""
        return [cls.spec for cls in sorted(self._plugins.values(), key=lambda c: c.spec.name)]

    def unregister(self, name: str) -> bool:
        """Remove plugin ``name`` from the registry.  Returns ``True`` iff it existed."""
        existed = name in self._plugins
        self._plugins.pop(name, None)
        return existed

    def clear(self) -> None:
        """Remove all registered plugins (used in tests for isolation)."""
        self._plugins.clear()

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins


# Module-level singleton populated at application startup.
PLUGIN_REGISTRY = PluginRegistry()
