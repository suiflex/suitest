"""ReporterRegistry singleton (M9-2).

Holds one instance per reporter name.  XRayReporter and QTestReporter are
pre-registered at import time so the API router can list and dispatch them
without additional wiring.

Usage::

    from suitest_api.services.reporter_registry import reporter_registry

    names = reporter_registry.list_all()           # ["xray", "qtest"]
    reporter = reporter_registry.get("xray")       # XRayReporter instance
"""

from __future__ import annotations

import structlog

from suitest_api.services.reporter_service import (
    QTestReporter,
    ReporterBase,
    XRayReporter,
)

log = structlog.get_logger(__name__)


class ReporterRegistry:
    """In-process registry of :class:`ReporterBase` instances."""

    def __init__(self) -> None:
        self._reporters: dict[str, ReporterBase] = {}

    def register(self, reporter: ReporterBase) -> None:
        """Register a reporter instance.  Overwrites any existing entry with the same name."""
        self._reporters[reporter.name] = reporter
        log.debug("reporter_registry.registered", name=reporter.name)

    def get(self, name: str) -> ReporterBase:
        """Return the reporter for *name*.

        :raises KeyError: When no reporter is registered under *name*.
        """
        try:
            return self._reporters[name]
        except KeyError:
            raise KeyError(f"No reporter registered with name {name!r}") from None

    def list_all(self) -> list[str]:
        """Return sorted list of registered reporter names."""
        return sorted(self._reporters)


# Module-level singleton — pre-populated with bundled reporters.
reporter_registry = ReporterRegistry()
reporter_registry.register(XRayReporter())
reporter_registry.register(QTestReporter())
