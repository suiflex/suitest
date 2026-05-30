"""Concrete :class:`JiraAdapter` — thin wrapper over bundled ``jirac-mcp``.

This adapter is intentionally a **thin shell** over the bundled ``jirac-mcp``
Rust binary (version-pinned at ``jira-mcp-v2.0.1``, registered in
``mcp_providers`` by M1d-1). Every tool call delegates to the MCP layer via the
:class:`JiraMcpClient` Protocol the constructor receives — no Python ``httpx``
Jira REST client, no OAuth 3LO (``jirac-mcp`` binary does not support it).

Env contract injected per invocation (so the binary never reads
``~/.config/jira/config.toml``):

* ``JIRA_URL``       — workspace's Jira base URL.
* ``JIRA_EMAIL``     — account email (Cloud) or username (Data Center basic).
* ``JIRA_TOKEN``     — API token (Cloud) / PAT (Data Center).
* ``JIRA_AUTH_TYPE`` — one of ``cloud_api_token`` / ``datacenter_pat`` /
  ``datacenter_basic``.
* ``JIRA_DEPLOYMENT`` — ``cloud`` or ``data_center``.

Secrets are decrypted **once** at construction time (the Integration row's
``secrets_encrypted`` column stores a JSON blob with the four/five values
above; ``EncryptedBytes`` already returns plaintext on read but we still funnel
through the :class:`JiraCrypto` Protocol so production wiring can pass a real
``packages/core/crypto`` instance and tests can pass an identity stub).

Status + severity mapping (Python-side, overridable per integration via
``Integration.config['status_map']``):

* :class:`DefectStatus.OPEN`         → ``"To Do"``
* :class:`DefectStatus.IN_PROGRESS`  → ``"In Progress"``
* :class:`DefectStatus.RESOLVED`     → ``"Resolved"``
* :class:`DefectStatus.CLOSED`       → ``"Done"``
* :class:`DefectStatus.WONT_FIX`     → ``"Won't Do"``

* :class:`Severity.LOW`      → ``"P4"``
* :class:`Severity.MEDIUM`   → ``"P3"``
* :class:`Severity.HIGH`     → ``"P2"``
* :class:`Severity.CRITICAL` → ``"P1"``

Error translation: every :class:`suitest_mcp.errors.McpError` raised by the
underlying MCP layer is translated to one of the :mod:`suitest_api.integrations.base`
``Adapter*`` exception types so :class:`AdapterError` catches downstream don't
need to special-case the MCP error hierarchy.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

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

# ---------------------------------------------------------------------------
# External collaborator Protocols (kept tiny so apps/api does NOT depend on
# the ``suitest_mcp`` package at runtime; M1d-19 wires the real implementation
# at lifespan time).
# ---------------------------------------------------------------------------


class JiraMcpClient(Protocol):
    """Minimum surface :class:`JiraAdapter` needs from the MCP layer.

    Production wiring (M1d-19) implements this against
    :class:`suitest_mcp.invoker.McpInvoker` + a per-call ``env_overrides`` knob.
    Tests inject an ``AsyncMock`` matching this signature.

    The :meth:`invoke` return shape is the parsed JSON ``stdout`` of the tool
    call — Jira's MCP tools always return a JSON document on stdout. Raises
    :class:`suitest_mcp.errors.McpError` (or a subclass) on any transport /
    tool failure; the adapter catches and re-raises as one of the
    :class:`AdapterError` subclasses.
    """

    async def invoke(
        self,
        *,
        provider: str,
        tool: str,
        arguments: dict[str, object],
        env_overrides: dict[str, str],
    ) -> dict[str, object]: ...


class JiraCrypto(Protocol):
    """Decryption protocol for the Integration row's secrets blob.

    Production wiring passes ``packages/core/crypto.decrypt`` (or a thin
    wrapper around it). Tests pass an identity callable since the
    ``EncryptedBytes`` SQLAlchemy column already returns plaintext on read —
    the Protocol stays for symmetry with the task spec (``decrypts
    integration.secrets_json_encrypted once``) and to keep a single seam to
    swap in a real KMS-backed crypto later.
    """

    def decrypt(self, blob: str) -> str: ...


# ---------------------------------------------------------------------------
# Mapping defaults
# ---------------------------------------------------------------------------

# Canonical forward map :class:`DefectStatus` → Jira workflow status name.
# Workspace overrides at ``Integration.config['status_map']`` merge over this.
_DEFAULT_STATUS_FORWARD: dict[DefectStatus, str] = {
    DefectStatus.OPEN: "To Do",
    DefectStatus.IN_PROGRESS: "In Progress",
    DefectStatus.RESOLVED: "Resolved",
    DefectStatus.CLOSED: "Done",
    DefectStatus.WONT_FIX: "Won't Do",
}

# Aliases on the external→DefectStatus side that don't override the canonical
# forward mapping. e.g. Jira workflows commonly expose both ``Open`` and
# ``To Do`` as "newly created" — both should map to OPEN, but transitions
# target the canonical "To Do".
_DEFAULT_STATUS_ALIASES: dict[str, DefectStatus] = {
    "Open": DefectStatus.OPEN,
    "Done": DefectStatus.RESOLVED,
    "Wontfix": DefectStatus.WONT_FIX,
    "Won't Fix": DefectStatus.WONT_FIX,
    "Closed": DefectStatus.CLOSED,
}

# :class:`Severity` → Jira priority name. Plan-05b §M1d-12 fixes this mapping.
_SEVERITY_TO_PRIORITY: dict[Severity, str] = {
    Severity.LOW: "P4",
    Severity.MEDIUM: "P3",
    Severity.HIGH: "P2",
    Severity.CRITICAL: "P1",
}

# Provider name the adapter dispatches against. Bundled by M1d-1 (registered
# in ``mcp_providers`` table with this name).
_JIRA_PROVIDER_NAME = "jirac-mcp"

# Default issue type when the Integration config does not pin one.
_DEFAULT_ISSUE_TYPE = "Bug"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class JiraAdapter:
    """Issue-tracker adapter for Jira Cloud / Data Center via ``jirac-mcp``.

    Constructor side-effects (one-shot):
      * Decrypts ``integration.secrets_encrypted`` into a ``dict`` (JSON blob
        with ``url`` / ``email`` / ``token`` / ``auth_type`` / ``deployment``).
      * Builds the per-invocation env overrides dict once.
      * Merges ``Integration.config['status_map']`` overrides onto the default
        Python-side status mapping.

    The instance is **per-Integration** (not per-process): each request that
    needs to talk to a Jira workspace builds one via the factory registered in
    :data:`adapter_factory_registry` at lifespan time.
    """

    kind: IntegrationKind = IntegrationKind.JIRA

    def __init__(
        self,
        integration: Integration,
        mcp_client: JiraMcpClient,
        crypto: JiraCrypto,
    ) -> None:
        self._integration = integration
        self._mcp = mcp_client
        # Decrypt secrets once at init. ``EncryptedBytes`` already returns the
        # plaintext JSON blob on read; ``crypto.decrypt`` is the seam tests
        # use to assert decryption happens (identity callable in production
        # because the SQLAlchemy type already transparent-decrypted).
        raw = integration.secrets_encrypted
        if raw is None:
            raise AdapterAuthError(f"jira integration {integration.id} has no secrets configured")
        plaintext = crypto.decrypt(raw)
        try:
            secrets = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise AdapterAuthError(
                f"jira integration {integration.id} secrets blob is not valid JSON"
            ) from exc
        if not isinstance(secrets, dict):
            raise AdapterAuthError(
                f"jira integration {integration.id} secrets blob is not a JSON object"
            )
        self._secrets: dict[str, str] = {k: str(v) for k, v in secrets.items()}
        self._env_overrides: dict[str, str] = self._build_env_overrides(self._secrets)
        # Workspace overrides on the status map (per docs/DATA_MODEL.md §3.8).
        cfg_map = integration.config.get("status_map") if integration.config else None
        self._status_map = self._build_status_map(cfg_map)
        # Default issue type / project_key pulled from integration.config —
        # the FE Integrations page (M1d-25) writes them on connect.
        self._project_key: str | None = (
            integration.config.get("project_key") if integration.config else None
        )
        self._issue_type: str = (
            integration.config.get("issue_type") if integration.config else None
        ) or _DEFAULT_ISSUE_TYPE

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_env_overrides(secrets: dict[str, str]) -> dict[str, str]:
        """Translate the decrypted secrets dict to the ``JIRA_*`` env contract.

        Missing required fields raise :class:`AdapterAuthError` at construction
        so the FE Integrations page can surface a "missing fields" hint rather
        than the runner ARQ job blowing up later.
        """
        try:
            url = secrets["url"]
            email = secrets["email"]
            token = secrets["token"]
        except KeyError as exc:
            raise AdapterAuthError(
                f"jira secrets blob missing required field: {exc.args[0]}"
            ) from exc
        auth_type = secrets.get("auth_type", "cloud_api_token")
        deployment = secrets.get("deployment", "cloud")
        if auth_type not in {"cloud_api_token", "datacenter_pat", "datacenter_basic"}:
            raise AdapterAuthError(
                f"jira auth_type must be cloud_api_token | datacenter_pat | datacenter_basic, "
                f"got {auth_type!r}"
            )
        if deployment not in {"cloud", "data_center"}:
            raise AdapterAuthError(
                f"jira deployment must be cloud | data_center, got {deployment!r}"
            )
        return {
            "JIRA_URL": url,
            "JIRA_EMAIL": email,
            "JIRA_TOKEN": token,
            "JIRA_AUTH_TYPE": auth_type,
            "JIRA_DEPLOYMENT": deployment,
        }

    @staticmethod
    def _build_status_map(overrides: object) -> StatusMap:
        """Merge workspace status_map overrides over the canonical defaults."""
        forward: dict[DefectStatus, str] = dict(_DEFAULT_STATUS_FORWARD)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                try:
                    ds = DefectStatus(k)
                except ValueError:
                    # Unknown DefectStatus name in user override → ignore
                    # rather than 500; the FE surfaces the canonical names.
                    continue
                if isinstance(v, str) and v:
                    forward[ds] = v
        sm = StatusMap(forward)
        # Register aliases unconditionally — they widen the reverse direction
        # without overriding the canonical forward target.
        for ext_name, ds in _DEFAULT_STATUS_ALIASES.items():
            sm.register_alias(ext_name, ds)
        return sm

    # ------------------------------------------------------------------
    # MCP plumbing
    # ------------------------------------------------------------------

    async def _invoke(self, tool: str, arguments: dict[str, object]) -> dict[str, object]:
        """Delegate one tool call to the MCP layer with our env overrides.

        Translates :class:`suitest_mcp.errors.McpError` subclasses to the
        adapter's own :class:`AdapterError` hierarchy so call sites can catch
        a single base type. The translation matrix:

        * :class:`McpToolTimeout` → :class:`AdapterTimeoutError`
        * :class:`McpError` whose message looks like 401/403 → :class:`AdapterAuthError`
        * :class:`McpError` whose message looks like 429 → :class:`AdapterRateLimitError`
        * anything else → :class:`AdapterRemoteError`
        """
        # Local import: keeps ``suitest_mcp`` off the ``apps/api`` import graph
        # for environments that don't ship the MCP runtime (e.g. ZERO-tier
        # builds that compile out the runner). Production wiring imports it
        # once at lifespan time when constructing the production client.
        from suitest_mcp.errors import McpError, McpToolTimeout

        try:
            return await self._mcp.invoke(
                provider=_JIRA_PROVIDER_NAME,
                tool=tool,
                arguments=arguments,
                env_overrides=self._env_overrides,
            )
        except McpToolTimeout as exc:
            raise AdapterTimeoutError(f"jira tool {tool} timed out: {exc}") from exc
        except McpError as exc:
            msg = str(exc)
            lowered = msg.lower()
            if any(tok in lowered for tok in ("401", "403", "unauthorized", "forbidden")):
                raise AdapterAuthError(f"jira {tool}: {msg}") from exc
            if "429" in msg or "rate limit" in lowered:
                raise AdapterRateLimitError(f"jira {tool}: {msg}") from exc
            raise AdapterRemoteError(f"jira {tool}: {msg}") from exc

    # ------------------------------------------------------------------
    # IssueTrackerAdapter Protocol surface
    # ------------------------------------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """Round-trip ``/rest/api/3/myself`` via ``jira_api_request``.

        On any auth failure returns ``ok=False`` with a ``"JIRA_AUTH"``
        sentinel rather than raising — the FE renders the error inline; the
        M1d-19 endpoint doesn't 500.
        """
        try:
            payload = await self._invoke(
                "jira_api_request",
                {"method": "GET", "path": "/rest/api/3/myself"},
            )
        except AdapterAuthError as exc:
            return ConnectionTestResult(ok=False, error=f"JIRA_AUTH: {exc}")
        except AdapterRateLimitError as exc:
            return ConnectionTestResult(ok=False, error=f"JIRA_RATE_LIMIT: {exc}")
        except AdapterTimeoutError as exc:
            return ConnectionTestResult(ok=False, error=f"JIRA_TIMEOUT: {exc}")
        except AdapterRemoteError as exc:
            return ConnectionTestResult(ok=False, error=f"JIRA_REMOTE: {exc}")
        body = _unwrap_result(payload)
        return ConnectionTestResult(
            ok=True,
            account_id=_str_or_none(body.get("accountId")),
            display_name=_str_or_none(body.get("displayName")),
        )

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        """Create the Jira issue via ``jira_issue_create``."""
        if not self._project_key:
            raise AdapterRemoteError(
                "jira integration is missing config.project_key — "
                "cannot create issues without a target project"
            )
        args: dict[str, object] = {
            "project_key": self._project_key,
            "issue_type": self._issue_type,
            "summary": body.title,
            "description": body.description or "",
            "priority": _SEVERITY_TO_PRIORITY.get(body.severity, "P3"),
            "labels": list(body.labels),
        }
        if body.assignee_external_id:
            args["assignee"] = body.assignee_external_id
        result = await self._invoke("jira_issue_create", args)
        return self._to_external_issue(result)

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        """Patch the issue via ``jira_issue_update`` then refresh via ``jira_issue_view``."""
        args: dict[str, object] = {
            "key": external_key,
            "summary": body.title,
            "description": body.description or "",
            "priority": _SEVERITY_TO_PRIORITY.get(body.severity, "P3"),
            "labels": list(body.labels),
        }
        if body.assignee_external_id:
            args["assignee"] = body.assignee_external_id
        result = await self._invoke("jira_issue_update", args)
        # ``jira_issue_update`` may not echo the full issue payload — round-trip
        # via ``jira_issue_view`` so callers get a fresh ExternalIssue with the
        # current external_status.
        refreshed = await self._invoke("jira_issue_view", {"key": external_key})
        merged = {**_unwrap_result(result), **_unwrap_result(refreshed)}
        return self._to_external_issue({"result": merged})

    async def fetch_external_issue(self, external_key: str) -> ExternalIssue:
        """Read-only ``jira_issue_view`` to refresh the live :class:`ExternalIssue`."""
        result = await self._invoke("jira_issue_view", {"key": external_key})
        return self._to_external_issue(result)

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        """Resolve the workflow transition id then call ``jira_issue_transition``."""
        target_name = self._status_map.defect_to_external(new_status)
        if target_name is None:
            raise AdapterRemoteError(
                f"jira status map has no entry for DefectStatus.{new_status.value}"
            )
        listing = await self._invoke("jira_issue_transitions_list", {"key": external_key})
        transition_id = _pick_transition_id(listing, target_name)
        if transition_id is None:
            raise AdapterRemoteError(
                f"jira issue {external_key} has no transition to {target_name!r}"
            )
        await self._invoke(
            "jira_issue_transition",
            {"key": external_key, "transition": transition_id},
        )

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        """Translate a Jira status name to :class:`DefectStatus` (case-insensitive)."""
        return self._status_map.external_to_defect(external_status)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_external_issue(self, payload: dict[str, object]) -> ExternalIssue:
        """Build an :class:`ExternalIssue` from a ``jirac-mcp`` response.

        ``jirac-mcp`` wraps every response in ``{"result": {...}}``. We accept
        either the wrapped or already-unwrapped shape so the helper works for
        ``create`` (wrapped) and ``view`` (also wrapped) consistently.
        """
        body = _unwrap_result(payload)
        external_key = _str_or_none(body.get("key")) or ""
        external_id = _str_or_none(body.get("id")) or external_key
        url = _str_or_none(body.get("url")) or _build_browse_url(
            self._env_overrides["JIRA_URL"], external_key
        )
        # Status may arrive as a nested ``{"name": "..."}`` object on the
        # ``fields.status`` path (Jira REST shape) or as a flat string (some
        # MCP tool implementations flatten it).
        external_status = _extract_status(body)
        if not external_key:
            raise AdapterRemoteError(f"jira response missing 'key' field — got {sorted(body)!r}")
        return ExternalIssue(
            external_id=external_id,
            external_key=external_key,
            external_url=url,
            external_status=external_status,
            raw_payload=body,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (kept free functions so unit tests can hit them
# directly without instantiating the adapter).
# ---------------------------------------------------------------------------


def _unwrap_result(payload: dict[str, object]) -> dict[str, object]:
    """Return ``payload['result']`` if it looks like a wrapped envelope, else payload itself."""
    inner = payload.get("result")
    if isinstance(inner, dict):
        return inner
    return payload


def _str_or_none(value: object) -> str | None:
    """Narrow an arbitrary JSON scalar to ``str | None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _build_browse_url(base_url: str, key: str) -> str:
    """Construct the human-openable ``/browse/<KEY>`` URL when the API didn't include one."""
    trimmed = base_url.rstrip("/")
    return f"{trimmed}/browse/{key}" if key else trimmed


def _extract_status(body: dict[str, object]) -> str:
    """Pull the workflow status name out of a Jira issue payload.

    Tolerates both flat (``{"status": "In Progress"}``) and nested
    (``{"fields": {"status": {"name": "In Progress"}}}``) shapes — the MCP
    tool implementations across the jirac-mcp versions in production
    inconsistently flatten.
    """
    flat = body.get("status")
    if isinstance(flat, str):
        return flat
    if isinstance(flat, dict):
        name = flat.get("name")
        if isinstance(name, str):
            return name
    fields = body.get("fields")
    if isinstance(fields, dict):
        status = fields.get("status")
        if isinstance(status, dict):
            name = status.get("name")
            if isinstance(name, str):
                return name
        if isinstance(status, str):
            return status
    return ""


def _pick_transition_id(payload: dict[str, object], target_name: str) -> str | None:
    """Find the workflow transition id whose target status matches ``target_name``.

    ``jira_issue_transitions_list`` returns a list of transitions; each
    transition has an ``id`` + a ``to.name`` (Jira REST shape). The match is
    case-insensitive on the name to tolerate workflow rename drift.
    """
    body = _unwrap_result(payload)
    transitions = body.get("transitions")
    if not isinstance(transitions, list):
        # Some MCP servers flatten to the top-level list.
        transitions = body.get("result") if isinstance(body.get("result"), list) else None
    if not isinstance(transitions, list):
        return None
    target_norm = target_name.casefold()
    for t in transitions:
        if not isinstance(t, dict):
            continue
        to = t.get("to")
        to_name = ""
        if isinstance(to, dict):
            to_name = str(to.get("name", ""))
        elif isinstance(to, str):
            to_name = to
        # Also fall back to the transition's own ``name`` field — some MCP
        # tools flatten ``to.name`` onto the transition.
        if not to_name:
            to_name = str(t.get("name", ""))
        if to_name.casefold() == target_norm:
            tid = t.get("id")
            if isinstance(tid, (str, int)):
                return str(tid)
    return None


# ---------------------------------------------------------------------------
# Factory registry — process-wide map from IntegrationKind to a callable that
# builds a concrete adapter from a (Integration, JiraMcpClient, JiraCrypto)
# triple. Wired by lifespan; consumed by ``IntegrationService.sync_external``
# (M1d-19) and the auto-filer (M1d-10).
# ---------------------------------------------------------------------------


class _IdentityCrypto:
    """No-op crypto used when ``EncryptedBytes`` already returns plaintext.

    Production wiring may swap in a KMS-backed crypto later; this no-op keeps
    the seam without forcing every caller to depend on
    :mod:`suitest_core.crypto`.
    """

    @staticmethod
    def decrypt(blob: str) -> str:
        return blob
