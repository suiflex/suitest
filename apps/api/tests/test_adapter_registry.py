"""Tests for the :class:`AdapterRegistry` + Protocol contract scaffold (M1d-11).

Coverage:

* Registry CRUD — register / get / list / duplicate-register (warn + replace).
* :class:`AdapterNotRegistered` raised on missing kind, catchable as :class:`KeyError`.
* Contract test runs with **zero adapters** registered → passes 0 iterations
  (M1d-11 DoD: "Contract test passes with zero adapters").
* Mock adapter implementing the Protocol passes the full contract.
* :class:`AdapterAuthError` (+ siblings) catchable as :class:`AdapterError`.
* :class:`StatusMap` bidirectional + case-insensitive lookup.
* DTO round-trip — :class:`ExternalIssue` / :class:`ExternalIssueInput` /
  :class:`ConnectionTestResult` `model_dump` → `model_validate` survives.
* Lifespan wires ``app.state.adapter_registry`` + the :func:`get_adapter_registry`
  Depends helper returns it.

The mock adapter lives in this module (not under ``conftest.py``) so the
contract surface stays one file for code review.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from suitest_api.deps.integrations import get_adapter_registry
from suitest_api.integrations import adapter_registry as singleton_registry
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
    IssueTrackerAdapter,
    StatusMap,
)
from suitest_api.integrations.contract import run_adapter_contract
from suitest_api.integrations.registry import AdapterNotRegistered, AdapterRegistry
from suitest_api.main import create_app
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity

# ---------------------------------------------------------------------------
# Mock adapter — implements the Protocol surface with in-memory bookkeeping.
# ---------------------------------------------------------------------------


class _MockAdapter:
    """Deterministic adapter used by the registry / contract tests.

    Records every call so assertions can verify the Protocol contract without
    a real HTTP / MCP transport. ``kind`` defaults to :attr:`IntegrationKind.JIRA`
    because Jira is the first concrete adapter that lands (PR-12).
    """

    def __init__(self, kind: IntegrationKind = IntegrationKind.JIRA) -> None:
        self.kind = kind
        self._issues: dict[str, ExternalIssue] = {}
        self._next_id = 1
        self.transitions: list[tuple[str, DefectStatus]] = []
        self._status_map = StatusMap(
            {
                DefectStatus.OPEN: "Open",
                DefectStatus.IN_PROGRESS: "In Progress",
                DefectStatus.RESOLVED: "Resolved",
                DefectStatus.CLOSED: "Closed",
                DefectStatus.WONT_FIX: "Won't Do",
            }
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, account_id="mock-acct", display_name="Mock Bot")

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        key = f"MOCK-{self._next_id}"
        self._next_id += 1
        issue = ExternalIssue(
            external_id=key,
            external_key=key,
            external_url=f"https://mock.example/{key}",
            external_status="Open",
            raw_payload={"title": body.title, "labels": list(body.labels)},
        )
        self._issues[key] = issue
        return issue

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        previous = self._issues.get(external_key)
        status = previous.external_status if previous is not None else "Open"
        updated = ExternalIssue(
            external_id=external_key,
            external_key=external_key,
            external_url=f"https://mock.example/{external_key}",
            external_status=status,
            raw_payload={"title": body.title, "labels": list(body.labels)},
        )
        self._issues[external_key] = updated
        return updated

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        self.transitions.append((external_key, new_status))
        ext_name = self._status_map.defect_to_external(new_status)
        if ext_name is not None and external_key in self._issues:
            prior = self._issues[external_key]
            self._issues[external_key] = prior.model_copy(update={"external_status": ext_name})

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        return self._status_map.external_to_defect(external_status)


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------


def test_registry_register_and_get_round_trip() -> None:
    registry = AdapterRegistry()
    adapter = _MockAdapter(IntegrationKind.JIRA)

    registry.register(adapter)

    assert registry.get(IntegrationKind.JIRA) is adapter
    assert IntegrationKind.JIRA in registry
    assert len(registry) == 1


def test_registry_list_kinds_returns_snapshot() -> None:
    registry = AdapterRegistry()
    registry.register(_MockAdapter(IntegrationKind.JIRA))
    registry.register(_MockAdapter(IntegrationKind.LINEAR))

    kinds = registry.list_kinds()

    assert set(kinds) == {IntegrationKind.JIRA, IntegrationKind.LINEAR}
    # Mutating the snapshot must not affect the registry.
    kinds.clear()
    assert len(registry) == 2


def test_registry_get_unknown_kind_raises_adapter_not_registered() -> None:
    registry = AdapterRegistry()

    with pytest.raises(AdapterNotRegistered) as exc_info:
        registry.get(IntegrationKind.GITHUB)

    # KeyError parent class is preserved so legacy ``except KeyError`` still catches.
    assert isinstance(exc_info.value, KeyError)
    assert IntegrationKind.GITHUB.value in str(exc_info.value)


def test_registry_duplicate_register_replaces_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = AdapterRegistry()
    first = _MockAdapter(IntegrationKind.JIRA)
    second = _MockAdapter(IntegrationKind.JIRA)

    registry.register(first)
    with caplog.at_level(logging.WARNING, logger="suitest_api.integrations.registry"):
        registry.register(second)

    assert registry.get(IntegrationKind.JIRA) is second
    assert any("adapter_registry.replace" in rec.message for rec in caplog.records), (
        f"expected replace warning, got: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Contract scaffold
# ---------------------------------------------------------------------------


def test_contract_zero_adapters_lists_empty() -> None:
    """M1d-11 DoD: contract test runs cleanly with zero adapters registered.

    The module-level singleton starts empty in a fresh process. We verify the
    invariant rather than re-running the parametrized contract class (which is
    auto-collected by pytest from contract.py).
    """
    registry = AdapterRegistry()
    assert registry.list_kinds() == []
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_contract_passes_for_mock_adapter() -> None:
    """A Protocol-satisfying mock adapter passes every contract assertion."""
    adapter = _MockAdapter()
    # ``isinstance`` against the @runtime_checkable Protocol.
    assert isinstance(adapter, IssueTrackerAdapter)
    await run_adapter_contract(adapter)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_adapter_auth_error_catchable_as_adapter_error() -> None:
    """All AdapterError subclasses must be catchable via the base type."""
    for cls in (AdapterAuthError, AdapterRateLimitError, AdapterTimeoutError, AdapterRemoteError):
        try:
            raise cls("boom")
        except AdapterError as exc:
            assert isinstance(exc, cls)
        else:  # pragma: no cover — fail loud if AdapterError isn't a parent
            pytest.fail(f"{cls.__name__} did not subclass AdapterError")


# ---------------------------------------------------------------------------
# StatusMap
# ---------------------------------------------------------------------------


def test_status_map_bidirectional_lookup() -> None:
    sm = StatusMap(
        {
            DefectStatus.OPEN: "Open",
            DefectStatus.IN_PROGRESS: "In Progress",
            DefectStatus.RESOLVED: "Resolved",
        }
    )

    assert sm.defect_to_external(DefectStatus.IN_PROGRESS) == "In Progress"
    # Case-insensitive on the external side.
    assert sm.external_to_defect("in progress") is DefectStatus.IN_PROGRESS
    assert sm.external_to_defect("IN PROGRESS") is DefectStatus.IN_PROGRESS
    # Unknown external status returns None instead of raising.
    assert sm.external_to_defect("nonexistent") is None
    # Unmapped DefectStatus returns None on forward direction too.
    assert sm.defect_to_external(DefectStatus.WONT_FIX) is None


def test_status_map_register_alias_widens_reverse_direction() -> None:
    sm = StatusMap({DefectStatus.OPEN: "Open"})
    # "To Do" should also map to OPEN without overriding the canonical "Open".
    sm.register_alias("To Do", DefectStatus.OPEN)

    assert sm.external_to_defect("to do") is DefectStatus.OPEN
    # Canonical forward direction unchanged.
    assert sm.defect_to_external(DefectStatus.OPEN) == "Open"


# ---------------------------------------------------------------------------
# DTO round-trip
# ---------------------------------------------------------------------------


def test_external_issue_pydantic_round_trip() -> None:
    issue = ExternalIssue(
        external_id="abc-123",
        external_key="PROJ-1",
        external_url="https://example/PROJ-1",
        external_status="In Progress",
        raw_payload={"foo": "bar"},
    )

    payload = issue.model_dump()
    rehydrated = ExternalIssue.model_validate(payload)

    assert rehydrated == issue
    assert rehydrated.raw_payload == {"foo": "bar"}


def test_external_issue_input_pydantic_round_trip() -> None:
    body = ExternalIssueInput(
        defect_id="defc_1",
        title="defect title",
        description="long description",
        severity=Severity.CRITICAL,
        labels=["bug", "auto"],
        assignee_external_id="user-1",
        run_id="run_1",
        test_case_public_id="TC-1",
    )

    payload = body.model_dump()
    rehydrated = ExternalIssueInput.model_validate(payload)

    assert rehydrated == body


def test_connection_test_result_defaults_to_none_metadata() -> None:
    failure = ConnectionTestResult(ok=False, error="auth failed")
    assert failure.account_id is None and failure.display_name is None
    success = ConnectionTestResult(ok=True, account_id="u1", display_name="Bot")
    assert success.error is None


# ---------------------------------------------------------------------------
# Lifespan wiring + Depends helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_wires_app_state_adapter_registry() -> None:
    app = create_app()
    async with LifespanManager(app):
        registry = app.state.adapter_registry
        assert isinstance(registry, AdapterRegistry)
        # Lifespan must hand back the process singleton — not a per-app copy —
        # so PR-12..15 import-time registrations land where requests can see them.
        assert registry is singleton_registry


@pytest.mark.asyncio
async def test_get_adapter_registry_dependency_returns_app_state_instance() -> None:
    app = FastAPI()
    test_registry = AdapterRegistry()
    test_registry.register(_MockAdapter(IntegrationKind.JIRA))
    app.state.adapter_registry = test_registry

    # FastAPI's ``Depends(...)`` in argument defaults is the canonical DI
    # idiom (see ``pyproject.toml`` per-file-ignores for routers/deps); tests
    # rarely use it so the lint exemption is local here.
    @app.get("/__kinds")
    async def list_kinds(
        registry: AdapterRegistry = Depends(get_adapter_registry),  # noqa: B008
    ) -> dict[str, Any]:
        return {"kinds": [k.value for k in registry.list_kinds()]}

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/__kinds")
    assert response.status_code == 200
    assert response.json() == {"kinds": [IntegrationKind.JIRA.value]}
