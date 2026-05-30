"""Issue-tracker integration adapter Protocol + DTOs.

This module defines the **contract surface** for every concrete issue-tracker
adapter (Jira / Linear / GitHub / Slack / …) shipped in subsequent M1d PRs
(PR-12..15). It is intentionally light and decoupled from any concrete HTTP /
MCP wire format:

* :class:`IssueTrackerAdapter` — ``@runtime_checkable`` :class:`typing.Protocol`
  the registry stores and the contract test runs ``isinstance(...)`` against.
* :class:`ExternalIssueInput` — Pydantic v2 DTO accepted by ``create_external_issue``
  / ``update_external_issue``.
* :class:`ExternalIssue` — Pydantic v2 DTO returned by the adapter, mirroring the
  ``external_issues`` table columns (see ``docs/DATA_MODEL.md §3.7``).
* :class:`ConnectionTestResult` — Pydantic v2 DTO returned by
  :func:`IssueTrackerAdapter.test_connection`, used by the "Test connection"
  button in the FE Integrations page (M1d-25).
* :class:`AdapterError` (+ subclasses) — base exception every adapter raises so
  callers (DefectAutoFiler, IntegrationService.sync_external) can catch one
  type and translate to the public error envelope.
* :class:`StatusMap` — bidirectional :class:`DefectStatus` ↔ external-status-name
  mapping each adapter constructs at init time. Lets the workspace override the
  defaults stored in ``Integration.config['status_map']`` (see ``docs/DATA_MODEL.md
  §3.8``).

**M1d-11 scope:** Protocol + DTOs + registry only. Concrete adapters land in
PR-12 (Jira / `jirac-mcp`), PR-13 (Linear / httpx GraphQL), PR-14
(GitHub / `github-mcp-server`), PR-15 (Slack / webhook).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity


class ExternalIssueInput(BaseModel):
    """Adapter-agnostic request body for issue create / update.

    Fields mirror the canonical Suitest defect shape (``docs/DATA_MODEL.md
    §3.7``) so adapters can build their wire-format from one source of truth.
    The ``defect_id`` / ``run_id`` / ``test_case_public_id`` fields let the
    adapter embed Suitest-side back-references (e.g. URLs, custom fields) in
    the created issue without round-tripping the DB.
    """

    model_config = ConfigDict(extra="forbid")

    defect_id: str = Field(description="Suitest internal defect id (cuid).")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    severity: Severity
    labels: list[str] = Field(default_factory=list)
    assignee_external_id: str | None = Field(
        default=None,
        description="External-system user id (e.g. Jira accountId, GitHub login).",
    )
    run_id: str | None = Field(
        default=None,
        description="Suitest run that triggered the defect (back-reference).",
    )
    test_case_public_id: str | None = Field(
        default=None,
        description="Public id of the failed test case (back-reference).",
    )


class ExternalIssue(BaseModel):
    """Adapter response after create / update / fetch.

    Maps 1:1 onto the ``external_issues`` table columns (``provider``,
    ``external_id``, ``external_url``) plus the live external status pulled
    from the remote system. ``raw_payload`` keeps the verbatim adapter
    response for debugging / replay; downstream code MUST NOT depend on its
    shape (it's adapter-specific).
    """

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(
        min_length=1, description="Wire id (e.g. Jira issue id, GitHub issue node id)."
    )
    external_key: str = Field(
        min_length=1,
        description="Human-readable key (e.g. 'PROJ-123', '#456'). Falls back to external_id if absent.",
    )
    external_url: str = Field(
        min_length=1, description="Browser-openable URL of the external issue."
    )
    external_status: str = Field(
        description="Raw external status string (e.g. 'In Progress', 'open'). Translated to DefectStatus via StatusMap.",
    )
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ConnectionTestResult(BaseModel):
    """Return shape for :meth:`IssueTrackerAdapter.test_connection`.

    On success, ``ok=True`` and the optional ``account_id`` / ``display_name``
    expose who the integration is authenticated as (Jira account, GitHub bot
    user, Slack workspace). On failure, ``ok=False`` and ``error`` carries the
    human-readable message the FE renders inline; ``account_id`` / ``display_name``
    stay None.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    account_id: str | None = None
    display_name: str | None = None
    error: str | None = None


class StatusMap:
    """Bidirectional :class:`DefectStatus` ↔ external-status-name lookup.

    Each adapter constructs one at init time from a Python-side default merged
    with the per-integration override stored in ``Integration.config['status_map']``
    (see ``docs/DATA_MODEL.md §3.8``). Lookups are case-insensitive on the
    external side because remote systems are inconsistent ("In Progress" vs
    "in progress" vs "InProgress").

    The mapping is **not necessarily bijective** — multiple external statuses
    can map to the same :class:`DefectStatus` (e.g. Jira "Done" and "Resolved"
    both → :attr:`DefectStatus.RESOLVED`). ``defect_to_external`` therefore
    returns the **canonical** external name for that DefectStatus (the one the
    adapter would use when transitioning).
    """

    def __init__(self, mapping: dict[DefectStatus, str]) -> None:
        # Canonical forward map (used by transition_status to pick the target name).
        self._forward: dict[DefectStatus, str] = dict(mapping)
        # Reverse map keyed by lowercase external name so "In Progress" and
        # "in progress" both resolve. The reverse direction is many-to-one in
        # practice but the adapter only ever supplies its canonical forward map
        # so we store every external→DefectStatus we know about under
        # case-folded keys.
        self._reverse: dict[str, DefectStatus] = {v.casefold(): k for k, v in mapping.items()}

    def defect_to_external(self, status: DefectStatus) -> str | None:
        """Canonical external status name for a :class:`DefectStatus`, or None if unmapped."""
        return self._forward.get(status)

    def external_to_defect(self, external_status: str) -> DefectStatus | None:
        """:class:`DefectStatus` for a remote status name (case-insensitive), or None if unknown."""
        return self._reverse.get(external_status.casefold())

    def register_alias(self, external_status: str, defect_status: DefectStatus) -> None:
        """Add a one-way alias on the external→DefectStatus side.

        Used to teach the map about extra remote statuses without making them
        the canonical forward name (e.g. Jira "To Do" → OPEN while keeping
        "Open" as the canonical forward target).
        """
        self._reverse[external_status.casefold()] = defect_status


class AdapterError(Exception):
    """Base exception for every adapter failure mode.

    Concrete adapters MUST raise either :class:`AdapterError` or one of the
    subclasses below — never bare ``Exception`` / ``httpx.HTTPError`` /
    ``McpError`` — so the call sites (``DefectAutoFiler.file_for_failed_step``
    and ``IntegrationService.sync_external``) can attach a single
    ``except AdapterError`` and translate to the public 502 / `integration.error`
    WS event.
    """


class AdapterAuthError(AdapterError):
    """Auth failed — token expired/revoked, 3LO needs re-auth, GitHub App not installed."""


class AdapterRateLimitError(AdapterError):
    """Remote system returned 429 / GraphQL `RATE_LIMITED` — ARQ retries with exp backoff."""


class AdapterTimeoutError(AdapterError):
    """Adapter exceeded its `timeout=10s` budget (httpx) or MCP `call_timeout_seconds`."""


class AdapterRemoteError(AdapterError):
    """Catch-all for 4xx/5xx from the remote that isn't auth / rate-limit / timeout."""


@runtime_checkable
class IssueTrackerAdapter(Protocol):
    """Contract every concrete issue-tracker adapter implements.

    Marked ``@runtime_checkable`` so the contract test
    (``apps/api/tests/test_adapter_registry.py``) can ``isinstance(adapter,
    IssueTrackerAdapter)`` over the registry without each adapter inheriting
    from the Protocol. The five methods are the union of operations the
    Suitest API surface (M1d-9 sync-external, M1d-10 auto-filer, M1d-19
    integration test) actually invokes.

    ``kind`` is the discriminator the registry uses; every adapter pins it to
    one of the :class:`IntegrationKind` values from
    :mod:`suitest_shared.domain.enums`.
    """

    kind: IntegrationKind

    async def test_connection(self) -> ConnectionTestResult:
        """Round-trip the remote API to confirm auth + reachability.

        Implementations call the cheapest authenticated endpoint they have
        (Jira ``/myself``, Linear ``viewer`` query, GitHub ``/user``, Slack
        ``auth.test``). On any failure return ``ConnectionTestResult(ok=False,
        error=<message>)`` rather than raising — the FE renders the message
        inline and the M1d-19 endpoint doesn't 500.
        """
        ...

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        """Create the issue in the remote system. Returns the canonical ExternalIssue."""
        ...

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        """Patch the issue identified by ``external_key`` and return the refreshed ExternalIssue."""
        ...

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        """Move the issue to the workflow state that maps to ``new_status``.

        Adapters resolve the target external status via their :class:`StatusMap`
        forward direction, then invoke the appropriate transition primitive
        (Jira transitions list, Linear state mutation, GitHub state field).
        Raises :class:`AdapterError` (or subclass) on failure; the caller
        translates to ``integration.error`` WS event.
        """
        ...

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        """Translate a remote status name (e.g. webhook payload) to :class:`DefectStatus`.

        Returns ``None`` for unknown / unmapped statuses; webhook receivers
        treat that as "no-op, log it" rather than 500-ing.
        """
        ...
