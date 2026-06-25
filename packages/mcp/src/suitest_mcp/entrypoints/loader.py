"""Discover custom MCP providers via importlib.metadata entry_points (M9-1).

Third-party packages register providers under the ``suitest.mcp_providers``
entry_points group.  :func:`discover_custom_mcp_providers` iterates that group,
imports each class, validates it extends :class:`CustomMcpProviderBase` and
carries a :class:`CustomMcpSpec`, and returns the collected list.

Errors for individual entry points are logged and skipped — a broken plugin
must not prevent the rest of the application from starting.
"""

from __future__ import annotations

import importlib
import importlib.metadata

import structlog

from suitest_mcp.entrypoints.base import CustomMcpProviderBase, CustomMcpSpec

log = structlog.get_logger(__name__)

ENTRY_POINTS_GROUP = "suitest.mcp_providers"


def discover_custom_mcp_providers() -> list[type[CustomMcpProviderBase]]:
    """Return all valid custom MCP provider classes registered via entry_points.

    Iterates ``suitest.mcp_providers`` entry_points, loads each target class,
    and validates:

    * The class is a subclass of :class:`CustomMcpProviderBase`.
    * It carries a class-level ``spec`` attribute that is a
      :class:`CustomMcpSpec` instance.

    Invalid or unloadable entry points are skipped with a warning log.

    :returns: List of valid provider *classes* (not instances).
    """
    eps = importlib.metadata.entry_points(group=ENTRY_POINTS_GROUP)
    discovered: list[type[CustomMcpProviderBase]] = []

    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:
            log.warning(
                "mcp.entrypoint.load_failed",
                entry_point=ep.name,
                value=ep.value,
                error=str(exc),
            )
            continue

        if not (isinstance(cls, type) and issubclass(cls, CustomMcpProviderBase)):
            log.warning(
                "mcp.entrypoint.not_subclass",
                entry_point=ep.name,
                cls=repr(cls),
            )
            continue

        spec = getattr(cls, "spec", None)
        if not isinstance(spec, CustomMcpSpec):
            log.warning(
                "mcp.entrypoint.missing_spec",
                entry_point=ep.name,
                cls=cls.__qualname__,
            )
            continue

        log.info(
            "mcp.entrypoint.discovered",
            entry_point=ep.name,
            provider=spec.name,
            version=spec.version,
        )
        discovered.append(cls)

    return discovered


def _import_class(dotted_path: str) -> type[object]:
    """Import a class from a dotted module path (``module.path:ClassName``).

    Used internally and by tests to load providers without the entry_points
    registry.
    """
    if ":" not in dotted_path:
        raise ValueError(f"Expected 'module.path:ClassName', got {dotted_path!r}")
    module_path, class_name = dotted_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls: type[object] = getattr(module, class_name)
    return cls
