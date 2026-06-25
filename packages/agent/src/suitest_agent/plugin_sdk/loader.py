"""Plugin discovery via Python entry points (M8-3).

Scans installed packages for the ``suitest.plugins`` entry-point group.  Each
entry point value must be a dotted path to an :class:`AgentPluginBase` subclass.
Malformed entries are skipped with a ``logging.warning``.

Usage::

    from suitest_agent.plugin_sdk.loader import discover_plugins
    from suitest_agent.plugin_sdk.registry import PLUGIN_REGISTRY

    for cls in discover_plugins():
        PLUGIN_REGISTRY.register(cls)
"""

from __future__ import annotations

import importlib
import logging
from importlib.metadata import entry_points

from suitest_agent.plugin_sdk.base import AgentPluginBase

ENTRY_POINT_GROUP = "suitest.plugins"

_log = logging.getLogger(__name__)


def discover_plugins() -> list[type[AgentPluginBase]]:
    """Scan installed packages for ``suitest.plugins`` entry points.

    Each entry point value is a dotted import path to an
    :class:`~suitest_agent.plugin_sdk.base.AgentPluginBase` subclass,
    e.g. ``my_package.agents:SecurityAgent``.

    Returns a list of the successfully loaded plugin classes.  Entries that
    cannot be imported, are not subclasses of :class:`AgentPluginBase`, or
    lack a valid ``spec`` attribute are skipped with a warning.
    """
    discovered: list[type[AgentPluginBase]] = []

    eps = entry_points(group=ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            obj = ep.load()
        except Exception as exc:
            _log.warning(
                "suitest.plugins: failed to load entry point %r from %r — %s",
                ep.name,
                ep.value,
                exc,
            )
            continue

        if not (isinstance(obj, type) and issubclass(obj, AgentPluginBase)):
            _log.warning(
                "suitest.plugins: entry point %r → %r is not an AgentPluginBase subclass; skipping",
                ep.name,
                obj,
            )
            continue

        if not hasattr(obj, "spec"):
            _log.warning(
                "suitest.plugins: plugin class %r has no 'spec' attribute; skipping",
                obj.__qualname__,
            )
            continue

        from suitest_agent.plugin_sdk.base import AgentPluginSpec

        if not isinstance(obj.spec, AgentPluginSpec):
            _log.warning(
                "suitest.plugins: plugin class %r has 'spec' that is not AgentPluginSpec; skipping",
                obj.__qualname__,
            )
            continue

        discovered.append(obj)
        _log.info(
            "suitest.plugins: discovered plugin %r v%s from %r",
            obj.spec.name,
            obj.spec.version,
            ep.value,
        )

    return discovered


def load_plugin_from_dotted_path(dotted_path: str) -> type[AgentPluginBase] | None:
    """Import a plugin class from a dotted path (``module:ClassName`` or ``module.ClassName``).

    Used by the service layer to load workspace-registered plugins that aren't
    installed as entry points (e.g. loaded from a stored YAML definition).

    Returns ``None`` on any import / validation failure after logging a warning.
    """
    try:
        if ":" in dotted_path:
            module_path, cls_name = dotted_path.rsplit(":", 1)
        else:
            module_path, cls_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        obj = getattr(module, cls_name)
    except Exception as exc:
        _log.warning("suitest.plugins: failed to import %r — %s", dotted_path, exc)
        return None

    if not (isinstance(obj, type) and issubclass(obj, AgentPluginBase)):
        _log.warning("suitest.plugins: %r is not an AgentPluginBase subclass", dotted_path)
        return None

    return obj
