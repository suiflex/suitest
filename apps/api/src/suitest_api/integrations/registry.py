"""Adapter registry — maps :class:`IntegrationKind` to a concrete adapter.

One process-wide :class:`AdapterRegistry` is constructed inside the FastAPI
``lifespan`` (``apps/api/src/suitest_api/main.py``) and stashed on
``app.state.adapter_registry``. PR-12..15 each add a single
``adapter_registry.register(...)`` line for their concrete adapter; the
contract test (``apps/api/tests/test_adapter_registry.py``) iterates the
registry to confirm every registered adapter satisfies
:class:`IssueTrackerAdapter`.

The registry is intentionally minimal — no DI graph, no lazy loading. M1d-19's
``IntegrationService.sync_external`` looks up the adapter once per request via
:meth:`AdapterRegistry.get` and then calls it directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
    from suitest_db.models.integration import Integration
    from suitest_shared.domain.enums import IntegrationKind

    from suitest_api.integrations.base import IssueTrackerAdapter, NotifierAdapter

logger = logging.getLogger(__name__)


class AdapterNotRegistered(KeyError):
    """No adapter registered for the requested :class:`IntegrationKind`.

    Raised by :meth:`AdapterRegistry.get`. Caught by
    ``IntegrationService.sync_external`` and translated to a 400 with code
    ``INTEGRATION_KIND_UNSUPPORTED`` — the public envelope makes the missing
    adapter explicit (e.g. "Slack-only workspace tried to sync_external on a
    Linear integration with no LinearAdapter compiled in").

    Inherits :class:`KeyError` so existing callers that do ``except KeyError``
    on ``registry.get`` keep working.
    """


class AdapterRegistry:
    """In-process :class:`IntegrationKind` → :class:`IssueTrackerAdapter` map.

    Not thread-safe — registration happens inside the synchronous lifespan
    startup hook before the event loop accepts requests, so all reads
    afterwards are concurrent-safe by construction.

    Duplicate registrations log a warning and REPLACE the previous adapter
    (rather than raising). This intentional choice lets tests instantiate a
    fresh ``MockAdapter`` per case without first un-registering the production
    one shipped from lifespan. Production code paths never re-register at
    runtime, so the warning is sufficient signal.
    """

    def __init__(self) -> None:
        self._by_kind: dict[IntegrationKind, IssueTrackerAdapter] = {}

    def register(self, adapter: IssueTrackerAdapter) -> None:
        """Register ``adapter`` under its declared :attr:`IssueTrackerAdapter.kind`.

        Replaces any prior registration for the same kind and emits a warning
        log so duplicate registrations from a botched test-fixture stay visible.
        """
        kind = adapter.kind
        if kind in self._by_kind:
            logger.warning(
                "adapter_registry.replace",
                extra={
                    "kind": kind.value,
                    "existing": type(self._by_kind[kind]).__name__,
                    "new": type(adapter).__name__,
                },
            )
        self._by_kind[kind] = adapter

    def get(self, kind: IntegrationKind) -> IssueTrackerAdapter:
        """Return the adapter registered for ``kind`` or raise :class:`AdapterNotRegistered`."""
        try:
            return self._by_kind[kind]
        except KeyError as exc:
            raise AdapterNotRegistered(kind.value) from exc

    def list_kinds(self) -> list[IntegrationKind]:
        """Snapshot of all registered :class:`IntegrationKind` values.

        Used by the contract test to parametrize over every concrete adapter
        currently registered (zero on a fresh M1d-11 build, one after PR-12,
        etc.).
        """
        return list(self._by_kind.keys())

    def __contains__(self, kind: object) -> bool:
        """``kind in registry`` shorthand for :meth:`AdapterRegistry.get` without try/except."""
        return kind in self._by_kind

    def __len__(self) -> int:
        """Number of currently registered adapters (0 in M1d-11, ≥1 after PR-12)."""
        return len(self._by_kind)


# Process-wide singleton. Tests should NOT mutate this directly — instead
# construct a fresh ``AdapterRegistry()`` and attach it to ``app.state``
# inside the test fixture. The lifespan in :mod:`suitest_api.main` always
# overwrites ``app.state.adapter_registry`` with this singleton at startup so
# production code keeps a single canonical instance.
adapter_registry = AdapterRegistry()


# ---------------------------------------------------------------------------
# Notifier factories (M1d-15)
# ---------------------------------------------------------------------------

# Callable that builds a :class:`NotifierAdapter` for one :class:`Integration`
# row. Notifier adapters (Slack today) are constructed per-row because each
# row carries its own secrets (webhook URL) and config, so the map below
# stores factories rather than singleton instances.
NotifierFactory = Callable[["Integration", "httpx.AsyncClient"], "NotifierAdapter"]


class NotifierFactoryNotRegistered(KeyError):
    """No notifier factory registered for the requested :class:`IntegrationKind`."""


# Process-wide :class:`IntegrationKind` → factory map. The lifespan in
# :mod:`suitest_api.main` registers the Slack factory (the only notifier kind
# today) and stashes the same dict on ``app.state`` so request handlers and
# the ARQ jobs both resolve adapters via one map.
notifier_factories: dict[IntegrationKind, NotifierFactory] = {}


def get_notifier_factory(kind: IntegrationKind) -> NotifierFactory:
    """Return the factory for ``kind`` or raise :class:`NotifierFactoryNotRegistered`."""
    try:
        return notifier_factories[kind]
    except KeyError as exc:
        raise NotifierFactoryNotRegistered(kind.value) from exc
