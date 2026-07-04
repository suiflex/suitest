"""Linear issue-tracker adapter — `httpx` against the Linear GraphQL API (M1d-13).

Linear ships no self-hostable MCP server (the official one is hosted-only,
breaks our ZERO/air-gap promise), so this adapter talks to
``https://api.linear.app/graphql`` directly via a shared
:class:`httpx.AsyncClient` injected from the FastAPI lifespan. Stays a thin
GraphQL client — re-implementable as an MCP wrapper in M2 if Linear publishes
a self-host build.

**Auth.** Personal Access Token (PAT) only for v1.0. Linear's docs require the
raw PAT in the ``Authorization`` header **without** a ``Bearer`` prefix; the
adapter intentionally does NOT prepend ``Bearer ``. OAuth lands with M5.

**Wire shape.** All five Protocol methods funnel through one ``_gql`` helper
that POSTs ``{"query", "variables"}`` JSON and unpacks ``data`` / ``errors``.
HTTP errors are translated to the :class:`AdapterError` hierarchy so
``DefectAutoFiler`` / ``IntegrationService.sync_external`` only ever ``except
AdapterError``.

**Mappings.**

* :class:`Severity` → Linear priority enum: ``LOW=4, MEDIUM=3, HIGH=2,
  CRITICAL=1`` (Linear: 1=Urgent .. 4=Low, 0=No priority).
* :class:`DefectStatus` → Linear workflow state **name** (resolved per-team
  via the ``workflowStates`` query, then ``issueUpdate(input: { stateId })``).
  Default map: ``OPEN→Backlog, IN_PROGRESS→In Progress, RESOLVED→Done,
  CLOSED→Done, WONT_FIX→Canceled``. Overridable via
  ``integration.config['status_map']``.

**Out of scope (deferred to M5/M2).** Linear OAuth, webhook sync-back,
project / cycle assignment, MCP wrapping.

"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity

from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterRateLimitError,
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
    StatusMap,
)

if TYPE_CHECKING:
    from suitest_db.models.integration import Integration

logger = logging.getLogger(__name__)

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
LINEAR_HTTP_TIMEOUT_SECONDS = 10.0

# Default :class:`DefectStatus` → Linear workflow state **name** map.
# CLOSED collapses onto "Done" because Linear's "completed" terminal state has
# no separate "Closed" — Suitest distinguishes RESOLVED vs CLOSED for its own
# audit trail but Linear users see both as Done.
DEFAULT_STATUS_MAP: dict[DefectStatus, str] = {
    DefectStatus.OPEN: "Backlog",
    DefectStatus.IN_PROGRESS: "In Progress",
    DefectStatus.RESOLVED: "Done",
    DefectStatus.CLOSED: "Done",
    DefectStatus.WONT_FIX: "Canceled",
}

# Reverse aliases learned at init time so webhook payloads / inbound status
# names also map back cleanly. "Triage" is Linear's pre-Backlog state and
# folds into OPEN; "Todo" is the explicit non-default name for backlog work.
_DEFAULT_REVERSE_ALIASES: dict[str, DefectStatus] = {
    "Triage": DefectStatus.OPEN,
    "Todo": DefectStatus.OPEN,
    "In Review": DefectStatus.IN_PROGRESS,
    "Duplicate": DefectStatus.WONT_FIX,
}

# :class:`Severity` → Linear priority enum (Linear: 0=No priority, 1=Urgent,
# 2=High, 3=Medium, 4=Low).
SEVERITY_TO_PRIORITY: dict[Severity, int] = {
    Severity.CRITICAL: 1,
    Severity.HIGH: 2,
    Severity.MEDIUM: 3,
    Severity.LOW: 4,
}


class CryptoService(Protocol):
    """Minimal Protocol the adapter needs to decrypt the integration secret blob.

    The production wiring uses :class:`suitest_core.crypto.EncryptedBytes` which
    auto-decrypts the column to a JSON-encoded plaintext string at SQLAlchemy
    load time — so the default impl in
    :class:`DefaultCryptoService` just ``json.loads`` whatever the column
    returns. Tests can swap in a mock that pulls from an in-memory map without
    touching the AES key fixture.
    """

    def decrypt(self, blob: str) -> dict[str, str]:
        """Decrypt ``blob`` to a ``{ "LINEAR_API_KEY": ... }`` shape dict."""
        ...


class DefaultCryptoService:
    """Default :class:`CryptoService` impl over the auto-decrypted column.

    ``Integration.secrets_encrypted`` is exposed as ``str | None`` by the
    ``EncryptedBytes`` SQLAlchemy column type — the AES-GCM decryption already
    happened in ``process_result_value``. The plaintext is a JSON string
    encoding ``{ "LINEAR_API_KEY": "lin_api_..." }``; this impl parses it.
    """

    def decrypt(self, blob: str) -> dict[str, str]:
        """JSON-decode the already-decrypted secrets payload."""
        parsed = json.loads(blob)
        if not isinstance(parsed, dict):
            raise ValueError("Linear secrets payload must be a JSON object")
        # Force value type to str so callers get a typed dict (mypy strict).
        return {str(k): str(v) for k, v in parsed.items()}


def _build_status_map(override: dict[str, str] | None) -> StatusMap:
    """Merge :data:`DEFAULT_STATUS_MAP` with the per-integration override.

    Override keys are :class:`DefectStatus` ``str`` values (``"OPEN"`` etc),
    values are external Linear state names. Unknown keys log a warning and are
    skipped so a typo in ``integration.config`` can't 500 the adapter.
    """
    merged: dict[DefectStatus, str] = dict(DEFAULT_STATUS_MAP)
    if override:
        for raw_key, raw_value in override.items():
            try:
                key = DefectStatus(raw_key)
            except ValueError:
                logger.warning(
                    "linear_adapter.status_map.unknown_key",
                    extra={"key": raw_key},
                )
                continue
            merged[key] = str(raw_value)
    sm = StatusMap(merged)
    for ext_name, ds in _DEFAULT_REVERSE_ALIASES.items():
        sm.register_alias(ext_name, ds)
    return sm


class LinearAdapter:
    """:class:`IssueTrackerAdapter` impl backed by Linear's GraphQL API.

    Constructor injects:

    * ``integration`` — the :class:`Integration` row carrying ``config`` (must
      contain ``team_id``; optionally ``status_map``) and ``secrets_encrypted``
      (JSON ``{ "LINEAR_API_KEY": "lin_api_..." }``).
    * ``http_client`` — shared :class:`httpx.AsyncClient` from the FastAPI
      lifespan so the TLS pool is reused across requests / adapters.
    * ``crypto`` — :class:`CryptoService` Protocol; default is
      :class:`DefaultCryptoService` which just JSON-decodes the auto-decrypted
      column blob.

    Stateless on the wire: no token cache, no project lookup memoisation. The
    workflow-states list IS cached for the life of the adapter instance
    because it changes rarely and resolving the state-id per ``transition_status``
    is otherwise a double round-trip.
    """

    kind: IntegrationKind = IntegrationKind.LINEAR

    def __init__(
        self,
        *,
        integration: Integration,
        http_client: httpx.AsyncClient,
        crypto: CryptoService | None = None,
    ) -> None:
        self._integration = integration
        self._http = http_client
        self._crypto: CryptoService = crypto if crypto is not None else DefaultCryptoService()
        self._team_id = self._read_team_id()
        self._status_map = _build_status_map(self._read_status_map_override())
        # Cached workflow-state name → id map (lazy, per-adapter). Populated
        # by ``_resolve_state_id`` on first ``transition_status`` call. Kept
        # in-process to keep ``transition_status`` to a single mutation when
        # the cache is warm.
        self._workflow_states_cache: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _read_team_id(self) -> str:
        team_id = self._integration.config.get("team_id") if self._integration.config else None
        if not isinstance(team_id, str) or not team_id:
            raise AdapterRemoteError(
                "Linear integration.config['team_id'] missing — set the Linear team UUID"
            )
        return team_id

    def _read_status_map_override(self) -> dict[str, str] | None:
        if not self._integration.config:
            return None
        raw = self._integration.config.get("status_map")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            logger.warning(
                "linear_adapter.status_map.invalid_shape",
                extra={"got": type(raw).__name__},
            )
            return None
        # Coerce keys/values to str so the merge step doesn't choke on weird
        # JSONB shapes that survived in old DB rows.
        return {str(k): str(v) for k, v in raw.items()}

    def _api_key(self) -> str:
        blob = self._integration.secrets_encrypted
        if not blob:
            raise AdapterAuthError("Linear integration has no PAT configured")
        try:
            secrets = self._crypto.decrypt(blob)
        except Exception as exc:  # pragma: no cover — corrupt secrets are rare
            raise AdapterAuthError(f"Linear secret decryption failed: {exc}") from exc
        api_key = secrets.get("LINEAR_API_KEY")
        if not api_key:
            raise AdapterAuthError("Linear integration secret missing LINEAR_API_KEY")
        return api_key

    # ------------------------------------------------------------------
    # GraphQL transport
    # ------------------------------------------------------------------

    async def _gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST one GraphQL operation and unwrap ``data`` / translate errors.

        Returns the ``data`` block of a successful response. Translates:

        * 401 / 403 → :class:`AdapterAuthError`
        * 429 → :class:`AdapterRateLimitError`
        * :class:`httpx.TimeoutException` → :class:`AdapterTimeoutError`
        * any other non-2xx → :class:`AdapterRemoteError`
        * 200 with ``errors`` field → :class:`AdapterRemoteError`
        """
        token = self._api_key()
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}
        try:
            response = await self._http.post(
                LINEAR_GRAPHQL_URL,
                headers={
                    # Linear convention: raw PAT, NO ``Bearer`` prefix.
                    "Authorization": token,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=LINEAR_HTTP_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"Linear API timed out after {LINEAR_HTTP_TIMEOUT_SECONDS}s"
            ) from exc

        if response.status_code in (401, 403):
            raise AdapterAuthError(
                f"Linear API auth failed ({response.status_code}): "
                "PAT is revoked or insufficient scope"
            )
        if response.status_code == 429:
            raise AdapterRateLimitError(
                "Linear API rate limit hit (429) — runner ARQ will retry with backoff"
            )
        if response.status_code >= 400:
            raise AdapterRemoteError(
                f"Linear API returned {response.status_code}: {response.text[:200]}"
            )

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise AdapterRemoteError(
                f"Linear API returned non-JSON body: {response.text[:200]}"
            ) from exc

        if body.get("errors"):
            raise AdapterRemoteError(f"Linear GraphQL errors: {body['errors']}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise AdapterRemoteError("Linear GraphQL response missing 'data'")
        return data

    # ------------------------------------------------------------------
    # IssueTrackerAdapter Protocol
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """Round-trip ``viewer { id name email }`` to confirm auth + reachability."""
        query = "query { viewer { id name email } }"
        try:
            data = await self._gql(query)
        except AdapterAuthError as exc:
            return ConnectionTestResult(ok=False, error=f"LINEAR_AUTH: {exc}")
        except AdapterTimeoutError as exc:
            return ConnectionTestResult(ok=False, error=f"LINEAR_TIMEOUT: {exc}")
        except AdapterRateLimitError as exc:
            return ConnectionTestResult(ok=False, error=f"LINEAR_RATE_LIMIT: {exc}")
        except AdapterRemoteError as exc:
            return ConnectionTestResult(ok=False, error=f"LINEAR_REMOTE: {exc}")

        viewer = data.get("viewer")
        if not isinstance(viewer, dict):
            return ConnectionTestResult(ok=False, error="LINEAR_REMOTE: viewer missing")
        return ConnectionTestResult(
            ok=True,
            account_id=str(viewer.get("id") or ""),
            display_name=str(viewer.get("name") or viewer.get("email") or "Linear user"),
        )

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        """Run the ``issueCreate`` mutation; returns the canonical :class:`ExternalIssue`."""
        mutation = (
            "mutation IssueCreate($input: IssueCreateInput!) {"
            "  issueCreate(input: $input) {"
            "    success"
            "    issue { id identifier url title state { id name } }"
            "  }"
            "}"
        )
        input_obj: dict[str, Any] = {
            "teamId": self._team_id,
            "title": body.title,
            "description": body.description,
            "priority": SEVERITY_TO_PRIORITY[body.severity],
        }
        # Linear's label ids are UUIDs not names — we only forward labels when
        # the caller already resolved them upstream. ``ExternalIssueInput.labels``
        # carries human-typed strings, so we attach them as the description
        # suffix instead of risking 400-ing on an unresolved labelId.
        if body.assignee_external_id:
            input_obj["assigneeId"] = body.assignee_external_id

        description = body.description
        meta_lines: list[str] = []
        if body.labels:
            meta_lines.append("**Labels:** " + ", ".join(body.labels))
        if body.run_id:
            meta_lines.append(f"**Run:** `{body.run_id}`")
        if body.test_case_public_id:
            meta_lines.append(f"**Test case:** `{body.test_case_public_id}`")
        meta_lines.append(f"**Suitest defect id:** `{body.defect_id}`")
        if meta_lines:
            description = (description + "\n\n---\n" + "\n".join(meta_lines)).strip()
        input_obj["description"] = description

        data = await self._gql(mutation, {"input": input_obj})
        result = data.get("issueCreate")
        if not isinstance(result, dict) or not result.get("success"):
            raise AdapterRemoteError(f"Linear issueCreate failed: {result}")
        issue = result.get("issue")
        if not isinstance(issue, dict):
            raise AdapterRemoteError("Linear issueCreate returned no issue")

        return _issue_payload_to_external(issue)

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        """Run ``issueUpdate(id:, input:)``; returns the refreshed :class:`ExternalIssue`.

        Linear's ``issueUpdate`` accepts the same numeric id as ``create`` (UUID
        string); we treat ``external_key`` as that id since :meth:`create_external_issue`
        stores ``issue.id`` in :attr:`ExternalIssue.external_id` and the
        identifier in :attr:`ExternalIssue.external_key`. Callers pass whichever
        they have on hand — the mutation tolerates both UUID and ``TEAM-123``
        identifiers per Linear docs.
        """
        mutation = (
            "mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {"
            "  issueUpdate(id: $id, input: $input) {"
            "    success"
            "    issue { id identifier url title state { id name } }"
            "  }"
            "}"
        )
        input_obj: dict[str, Any] = {
            "title": body.title,
            "description": body.description,
            "priority": SEVERITY_TO_PRIORITY[body.severity],
        }
        if body.assignee_external_id:
            input_obj["assigneeId"] = body.assignee_external_id

        data = await self._gql(mutation, {"id": external_key, "input": input_obj})
        result = data.get("issueUpdate")
        if not isinstance(result, dict) or not result.get("success"):
            raise AdapterRemoteError(f"Linear issueUpdate failed: {result}")
        issue = result.get("issue")
        if not isinstance(issue, dict):
            raise AdapterRemoteError("Linear issueUpdate returned no issue")
        return _issue_payload_to_external(issue)

    async def fetch_external_issue(self, external_key: str) -> ExternalIssue:
        """Read-only Linear ``issue(id:)`` query — refresh state without mutating.

        Implements the :class:`IssueTrackerAdapter` Protocol method M1d-19's
        ``IntegrationService.sync_external`` calls when refreshing the live
        remote status. ``external_key`` may be the Linear UUID or the
        ``TEAM-123`` identifier — both resolve through the same query.
        """
        query = (
            "query IssueFetch($id: String!) {"
            "  issue(id: $id) { id identifier url title state { id name } }"
            "}"
        )
        data = await self._gql(query, {"id": external_key})
        issue = data.get("issue")
        if not isinstance(issue, dict):
            raise AdapterRemoteError(f"Linear issue {external_key} not found")
        return _issue_payload_to_external(issue)

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        """Move the issue to the workflow state mapped from ``new_status``.

        Two-step: (1) lazy-load the team's ``workflowStates`` so we can map the
        canonical state name to a Linear state id, (2) run ``issueUpdate(id:,
        input: { stateId })``. The states list is cached for the life of the
        adapter (rarely changes; refresh on process restart).
        """
        target_name = self._status_map.defect_to_external(new_status)
        if target_name is None:
            raise AdapterRemoteError(
                f"Linear status_map has no mapping for DefectStatus.{new_status.value}"
            )

        state_id = await self._resolve_state_id(target_name)
        mutation = (
            "mutation IssueTransition($id: String!, $stateId: String!) {"
            "  issueUpdate(id: $id, input: { stateId: $stateId }) {"
            "    success"
            "    issue { id state { id name } }"
            "  }"
            "}"
        )
        data = await self._gql(mutation, {"id": external_key, "stateId": state_id})
        result = data.get("issueUpdate")
        if not isinstance(result, dict) or not result.get("success"):
            raise AdapterRemoteError(f"Linear transition_status failed: {result}")

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        """Translate a Linear state name back to :class:`DefectStatus` (or None)."""
        return self._status_map.external_to_defect(external_status)

    # ------------------------------------------------------------------
    # Internal — workflow-state resolution
    # ------------------------------------------------------------------

    async def _resolve_state_id(self, state_name: str) -> str:
        """Return the Linear ``WorkflowState.id`` whose ``name`` matches.

        Lazy-loads + caches the team's full state list on first call. Lookup is
        case-insensitive because Linear state names ship lowercase ("In
        Progress") vs Title Case ("Backlog") depending on workspace template.
        """
        if self._workflow_states_cache is None:
            query = (
                "query WorkflowStates($teamId: ID!) {"
                "  workflowStates(filter: { team: { id: { eq: $teamId } } }) {"
                "    nodes { id name }"
                "  }"
                "}"
            )
            data = await self._gql(query, {"teamId": self._team_id})
            states = data.get("workflowStates")
            if not isinstance(states, dict) or not isinstance(states.get("nodes"), list):
                raise AdapterRemoteError("Linear workflowStates response malformed")
            cache: dict[str, str] = {}
            for node in states["nodes"]:
                if not isinstance(node, dict):
                    continue
                name = node.get("name")
                node_id = node.get("id")
                if isinstance(name, str) and isinstance(node_id, str):
                    cache[name.casefold()] = node_id
            self._workflow_states_cache = cache

        state_id = self._workflow_states_cache.get(state_name.casefold())
        if state_id is None:
            raise AdapterRemoteError(
                f"Linear team has no workflow state named '{state_name}' — "
                "configure status_map in integration.config"
            )
        return state_id


def _issue_payload_to_external(issue: dict[str, Any]) -> ExternalIssue:
    """Build :class:`ExternalIssue` from a Linear ``Issue`` GraphQL payload.

    Linear exposes ``id`` (UUID), ``identifier`` (e.g. ``ENG-123``), ``url``
    and a nested ``state.name``. Falls back to ``id`` for both ``external_id``
    and ``external_key`` if ``identifier`` is missing (shouldn't happen in
    practice but keeps the DTO non-empty for mypy strict).
    """
    external_id = str(issue.get("id") or "")
    external_key = str(issue.get("identifier") or external_id)
    external_url = str(issue.get("url") or "")
    state = issue.get("state") if isinstance(issue.get("state"), dict) else {}
    external_status = str(state.get("name") or "") if isinstance(state, dict) else ""
    return ExternalIssue(
        external_id=external_id or external_key,
        external_key=external_key or external_id,
        external_url=external_url or f"https://linear.app/issue/{external_key}",
        external_status=external_status,
        raw_payload=issue,
    )
