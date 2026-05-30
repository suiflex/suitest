"""Reusable contract test for :class:`IssueTrackerAdapter` implementations.

PR-12..15 each register a concrete adapter; the contract test below runs
``pytest.mark.parametrize`` over every adapter currently in
:data:`adapter_registry` and asserts that the basic CRUD round-trip works at
the Protocol surface.

With **zero adapters registered** (the M1d-11 baseline) the parametrize tuple
is empty and pytest reports the test as collected-but-skipped with no
failures, per the M1d-11 acceptance criterion "Contract test passes with zero
adapters" (``docs/superpowers/plans/2026-05-30-plan-05b-m1d-manual-tcm-writes.md
§Task M1d-11``).

Adapters land their own per-adapter tests in PR-12..15 — this module is the
**shared** contract every adapter must pass regardless of wire format.

Usage from a test module::

    from suitest_api.integrations.contract import IssueTrackerAdapterContract

    class TestJiraAdapter(IssueTrackerAdapterContract):
        pass  # auto-parametrized over the registry

Or call :func:`run_adapter_contract` directly with a pre-built adapter when
the test wants to inject mocked transport.
"""

from __future__ import annotations

from typing import Any

import pytest
from suitest_shared.domain.enums import DefectStatus, Severity

from suitest_api.integrations.base import (
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
    IssueTrackerAdapter,
)
from suitest_api.integrations.registry import adapter_registry


def _sample_input(defect_id: str = "defc_test_0001") -> ExternalIssueInput:
    """Stable sample payload reused across the contract assertions."""
    return ExternalIssueInput(
        defect_id=defect_id,
        title="contract-test defect title",
        description="contract-test defect description",
        severity=Severity.HIGH,
        labels=["contract", "auto-test"],
        assignee_external_id=None,
        run_id="run_test_0001",
        test_case_public_id="TC-0001",
    )


async def _assert_protocol_methods(adapter: IssueTrackerAdapter) -> None:
    """Sanity: ``@runtime_checkable`` Protocol membership + ``kind`` attribute."""
    assert isinstance(adapter, IssueTrackerAdapter), (
        f"{type(adapter).__name__} does not satisfy IssueTrackerAdapter Protocol"
    )
    # ``kind`` is part of the Protocol surface — IntegrationKind enum value.
    assert adapter.kind is not None, "adapter.kind must be set to an IntegrationKind"


async def _assert_test_connection(adapter: IssueTrackerAdapter) -> None:
    """``test_connection`` returns a typed :class:`ConnectionTestResult`."""
    result = await adapter.test_connection()
    assert isinstance(result, ConnectionTestResult)


async def _assert_create_issue(adapter: IssueTrackerAdapter) -> ExternalIssue:
    """``create_external_issue`` returns a non-empty :class:`ExternalIssue`."""
    issue = await adapter.create_external_issue(_sample_input())
    assert isinstance(issue, ExternalIssue)
    assert issue.external_id, "ExternalIssue.external_id must be non-empty"
    assert issue.external_url, "ExternalIssue.external_url must be non-empty"
    return issue


async def _assert_update_round_trip(adapter: IssueTrackerAdapter, key: str) -> None:
    """``update_external_issue`` accepts the prior key and returns the refreshed issue."""
    updated = await adapter.update_external_issue(key, _sample_input())
    assert isinstance(updated, ExternalIssue)
    # external_key / external_id should remain stable across update of same issue.
    assert updated.external_key == key or updated.external_id == key


async def _assert_fetch_round_trip(adapter: IssueTrackerAdapter, key: str) -> None:
    """``fetch_external_issue`` returns the live :class:`ExternalIssue` for ``key``."""
    fetched = await adapter.fetch_external_issue(key)
    assert isinstance(fetched, ExternalIssue)
    assert fetched.external_key == key or fetched.external_id == key


async def _assert_transition(adapter: IssueTrackerAdapter, key: str) -> None:
    """``transition_status`` runs without raising for a known :class:`DefectStatus`."""
    await adapter.transition_status(key, DefectStatus.IN_PROGRESS)


def _assert_status_map(adapter: IssueTrackerAdapter) -> None:
    """``map_external_status_to_defect_status`` returns DefectStatus or None — never raises."""
    result = adapter.map_external_status_to_defect_status("unknown-status-xyz")
    assert result is None or isinstance(result, DefectStatus)


async def run_adapter_contract(adapter: IssueTrackerAdapter) -> None:
    """Run the full contract suite against one adapter instance.

    Useful from per-adapter tests that want to inject mocks (mocked MCP session
    for Jira, ``respx`` cassette for Linear). The registry-parametrized class
    below dispatches here for each registered adapter.
    """
    await _assert_protocol_methods(adapter)
    await _assert_test_connection(adapter)
    issue = await _assert_create_issue(adapter)
    await _assert_update_round_trip(adapter, issue.external_key)
    await _assert_fetch_round_trip(adapter, issue.external_key)
    await _assert_transition(adapter, issue.external_key)
    _assert_status_map(adapter)


def _registered_adapters() -> list[Any]:
    """Snapshot the registry at collection time.

    Returns concrete adapters (not just kinds) so pytest's ``ids=`` can render
    the adapter class name. With zero registrations this returns ``[]`` and
    the parametrized test simply doesn't generate any test cases — pytest
    reports "no tests ran for this id" rather than failing.
    """
    return [adapter_registry.get(k) for k in adapter_registry.list_kinds()]


class IssueTrackerAdapterContract:
    """Reusable contract suite parametrized over every registered adapter.

    Concrete test modules inherit this class to auto-run the full contract for
    every adapter currently in :data:`adapter_registry`. With zero adapters
    registered (M1d-11 baseline) pytest collects the class but reports the
    parametrized test as having zero iterations — which is the expected
    M1d-11 DoD ("Contract test passes with zero adapters").
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "adapter",
        _registered_adapters(),
        ids=lambda a: type(a).__name__,
    )
    async def test_adapter_satisfies_contract(self, adapter: IssueTrackerAdapter) -> None:
        """Per-adapter end-to-end Protocol contract."""
        await run_adapter_contract(adapter)
