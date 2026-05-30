"""FastAPI dependencies: shared adapter + notifier-factory registries + pre-save factories.

Two registries:

* :func:`get_adapter_registry` — issue-tracker singletons (Jira / Linear /
  GitHub), constructed once per process and stashed on
  ``app.state.adapter_registry``.
* :func:`get_notifier_factory_registry` — per-row notifier factories (Slack),
  stashed on ``app.state.notifier_factory_registry``.

Plus a pair of OPTIONAL pre-save factories used by the M1d-19
``/integrations/jira|github/test-connection`` endpoints:

* :func:`get_pre_save_jira_factory` / :func:`get_pre_save_github_factory` —
  callables that take the request body's credential dict and return an
  ephemeral :class:`IssueTrackerAdapter` instance. The wire-up of the real
  ``jirac-mcp`` / ``github-mcp-server`` adapters lands in PR-12 / PR-14; until
  then these resolve to ``None`` (router returns 501) unless a test injects
  one via ``app.dependency_overrides``.

The DI helpers return ``app.state.*`` when populated (lifespan ran) and fall
back to the import-time singletons / ``None`` so tests that build the app
without entering the lifespan still work.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import Request

from suitest_api.integrations.base import IssueTrackerAdapter
from suitest_api.integrations.notifier_registry import (
    NotifierFactoryRegistry,
    notifier_factory_registry,
)
from suitest_api.integrations.registry import AdapterRegistry, adapter_registry


def get_adapter_registry(request: Request) -> AdapterRegistry:
    """Return the :class:`AdapterRegistry` stashed on ``app.state.adapter_registry``.

    Falls back to the module-level singleton if the lifespan hasn't populated
    ``app.state`` yet (e.g. tests that construct the app without entering the
    lifespan). The singleton is always safe to return because registrations
    happen at startup before any request lands.
    """
    stashed = getattr(request.app.state, "adapter_registry", None)
    if isinstance(stashed, AdapterRegistry):
        return stashed
    return adapter_registry


def get_notifier_factory_registry(request: Request) -> NotifierFactoryRegistry:
    """Return the :class:`NotifierFactoryRegistry` stashed on app.state.

    Mirrors :func:`get_adapter_registry` semantics — falls back to the
    import-time singleton when the lifespan hasn't run. Slack is the only
    notifier kind registered today (M1d-15); PR-17+ will add PagerDuty / Teams.
    """
    stashed = getattr(request.app.state, "notifier_factory_registry", None)
    if isinstance(stashed, NotifierFactoryRegistry):
        return stashed
    return notifier_factory_registry


class PreSaveTestFactory(Protocol):
    """Callable that builds an ephemeral :class:`IssueTrackerAdapter` from raw creds.

    Used by ``POST /integrations/jira|github/test-connection`` to validate
    credentials BEFORE persisting an integration row. The factory takes a
    ``dict[str, str]`` of the request body fields (e.g. ``jira_url`` /
    ``jira_email`` / ``jira_token``) and returns an adapter instance with
    ``test_connection`` wired against the supplied creds. The factory is
    responsible for spawning + tearing down whatever transport it uses
    (MCP subprocess, httpx client) — the router only calls
    ``test_connection`` and discards.
    """

    def __call__(self, body: dict[str, str]) -> IssueTrackerAdapter: ...


def get_pre_save_jira_factory(request: Request) -> PreSaveTestFactory | None:
    """Return the Jira pre-save test factory from ``app.state.pre_save_jira_factory``.

    Returns ``None`` when not wired (router → 501 INTEGRATION_KIND_UNSUPPORTED).
    PR-12 (M1d-12 JiraAdapter) wires this in the lifespan; tests inject via
    ``app.dependency_overrides`` directly.
    """
    return getattr(request.app.state, "pre_save_jira_factory", None)


def get_pre_save_github_factory(request: Request) -> PreSaveTestFactory | None:
    """Return the GitHub pre-save test factory from ``app.state.pre_save_github_factory``.

    Returns ``None`` when not wired (router → 501). PR-14 (M1d-14
    GitHubAdapter) wires this in the lifespan; tests inject directly.
    """
    return getattr(request.app.state, "pre_save_github_factory", None)
