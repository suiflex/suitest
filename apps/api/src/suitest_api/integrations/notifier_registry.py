"""Per-:class:`IntegrationKind` factory registry for notifier adapters.

Notifier adapters (Slack today; PagerDuty / Teams in M2+) need to be
constructed *per integration row* because each row carries its own secrets
(webhook URL) and config. The :class:`AdapterRegistry` for issue trackers
stores a singleton-per-kind because Jira / Linear / GitHub adapters share
state safely; notifiers don't, so they get their own registry typed as
``IntegrationKind → factory callable``.

The factory takes a fully-loaded :class:`Integration` ORM row plus the shared
:class:`httpx.AsyncClient` from app state and returns a :class:`NotifierAdapter`
instance ready to invoke. The ARQ job that owns the lifecycle calls the
factory inside a request-scoped session so each notification has its own
adapter (no cross-workspace state leakage).

PR-15 ships :class:`~suitest_api.integrations.slack_adapter.SlackAdapter` and
registers it in :mod:`suitest_api.main` lifespan. Future notifier adapters
(PagerDuty, Teams) follow the same pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import httpx
    from suitest_db.models.integration import Integration
    from suitest_shared.domain.enums import IntegrationKind

    from suitest_api.integrations.base import NotifierAdapter


class NotifierAdapterFactory(Protocol):
    """Callable that builds a :class:`NotifierAdapter` for one integration row.

    Declared as a Protocol (not a concrete callable type alias) so future
    factories can take additional kwargs (e.g. a per-tenant secret cache)
    without breaking the registry signature.
    """

    def __call__(
        self,
        integration: Integration,
        http_client: httpx.AsyncClient,
    ) -> NotifierAdapter: ...


class NotifierFactoryNotRegistered(KeyError):
    """No notifier factory registered for the requested :class:`IntegrationKind`."""


class NotifierFactoryRegistry:
    """In-process :class:`IntegrationKind` → factory map.

    Mirrors the shape of :class:`AdapterRegistry` (the issue-tracker registry)
    so the two read the same way at call sites. Not thread-safe: registrations
    happen in :func:`suitest_api.main.lifespan` startup before the event loop
    accepts requests.
    """

    def __init__(self) -> None:
        self._by_kind: dict[IntegrationKind, NotifierAdapterFactory] = {}

    def register(self, kind: IntegrationKind, factory: NotifierAdapterFactory) -> None:
        """Register ``factory`` under ``kind``. Replaces any prior registration."""
        self._by_kind[kind] = factory

    def get(self, kind: IntegrationKind) -> NotifierAdapterFactory:
        """Return the factory for ``kind`` or raise :class:`NotifierFactoryNotRegistered`."""
        try:
            return self._by_kind[kind]
        except KeyError as exc:
            raise NotifierFactoryNotRegistered(kind.value) from exc

    def __contains__(self, kind: object) -> bool:
        return kind in self._by_kind

    def __len__(self) -> int:
        return len(self._by_kind)


# Process-wide singleton. Lifespan attaches the same instance to ``app.state``
# so request handlers + the ARQ job both resolve adapters via one map.
notifier_factory_registry = NotifierFactoryRegistry()
