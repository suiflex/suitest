"""GitHubAdapter — thin wrapper over bundled ``github-mcp-server@v1.1.2`` (M1d-14).

Implementation notes:

* **Wire delegation.** Every issue-tracker operation goes through the bundled
  ``github-mcp-server`` Go binary via :class:`McpClientProtocol` — the adapter
  itself NEVER speaks GitHub's REST / GraphQL surface for issue ops. The MCP
  binary is launched in ``--toolsets issues`` mode (env ``GITHUB_TOOLSETS=issues``)
  so its advertised tool set stays trimmed to what we actually call.
* **Auth.** The only Python-side network call is the GitHub App installation
  access token mint (``POST /app/installations/{id}/access_tokens``). The
  resulting short-lived token (~60 min upstream TTL) is cached in-process with
  a 50-min TTL and injected per-invocation via ``env_overrides[GITHUB_PERSONAL_ACCESS_TOKEN]``
  so it never persists on the :class:`McpProvider` row.
* **JWT signing.** We sign the App JWT (RS256) with
  :mod:`cryptography.hazmat.primitives.asymmetric.padding` directly rather
  than adding ``PyJWT`` to the dependency graph — :mod:`cryptography` is
  already a transitive dep via :mod:`suitest_core.crypto`.
* **Status mapping.** GitHub Issues only expose ``open`` / ``closed`` states.
  We canonicalise IN_PROGRESS → ``open`` (worked-on issues stay open with a
  status label) and RESOLVED / CLOSED / WONT_FIX → ``closed``. Severity is
  represented as a ``severity:<critical|high|medium|low>`` label applied via
  the ``issue_write`` tool's ``labels`` argument.
* **Error translation.** Every catch site collapses :class:`McpError` /
  :class:`httpx.HTTPError` into :class:`AdapterError` subclasses so call sites
  (``DefectAutoFiler``, ``IntegrationService.sync_external``) keep a single
  ``except AdapterError`` block.

The adapter pre-dates a generic ``packages/mcp`` ``McpClient`` facade — the
``McpClientProtocol`` defined below names the contract we need (provider name,
tool name, arguments, env overrides) so a later pool refactor can supply a
concrete implementation without touching this module. Tests inject a tiny
recording fake.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from suitest_mcp.errors import McpError
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
    from collections.abc import Callable

    from suitest_db.models.integration import Integration

log = structlog.get_logger(__name__)


# Upstream installation tokens are valid for 60 minutes. We refresh 10 minutes
# early so an in-flight tool call never trips against expiry mid-request.
_TOKEN_TTL_SECONDS: int = 50 * 60
# GitHub's JWT short-lifetime cap is 10 minutes; we sign for 9 minutes with a
# 30-second clock-skew leeway on ``iat`` per GitHub's docs.
_APP_JWT_LIFETIME_SECONDS: int = 9 * 60
_APP_JWT_SKEW_SECONDS: int = 30
_INSTALLATIONS_URL: str = "https://api.github.com/app/installations/{installation_id}/access_tokens"
_GH_API_VERSION_HEADER: str = "application/vnd.github+json"
_GITHUB_TOOLSETS_VALUE: str = "issues"
_PROVIDER_NAME: str = "github-mcp"


# ---------------------------------------------------------------------------
# Crypto / MCP-client protocols (small DI seams so tests can inject fakes).
# ---------------------------------------------------------------------------


@runtime_checkable
class CryptoServiceProtocol(Protocol):
    """Minimal AES-GCM façade — matches the helper functions in :mod:`suitest_core.crypto`.

    Tests inject a fake that returns a deterministic plaintext blob without
    requiring ``SUITEST_ENCRYPTION_KEY`` to be set in the environment.
    """

    def decrypt(self, blob: bytes, aad: bytes = b"") -> str:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class McpInvokeResult:
    """Normalised return shape of :meth:`McpClientProtocol.invoke`.

    ``output`` is the JSON-decoded payload (when the MCP tool returns JSON in
    its ``text`` content blocks) and ``raw_stdout`` keeps the verbatim text for
    debugging. Adapter code consumes ``output`` exclusively.
    """

    output: dict[str, object]
    raw_stdout: str


@runtime_checkable
class McpClientProtocol(Protocol):
    """High-level MCP invoker the GitHub adapter delegates against.

    A future ``packages/mcp`` refactor will provide a concrete implementation
    that resolves ``provider`` from the registry, leases a session from the
    pool with the supplied ``env_overrides``, and decodes the tool's textual
    JSON response into ``McpInvokeResult.output``. The Protocol shape is
    intentionally narrow so the adapter doesn't depend on registry / pool
    types directly.
    """

    async def invoke(
        self,
        *,
        provider: str,
        tool: str,
        arguments: dict[str, object],
        env_overrides: dict[str, str],
        workspace_id: str,
    ) -> McpInvokeResult:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# StatusMap helpers — GitHub Issues only have open / closed.
# ---------------------------------------------------------------------------


def _build_status_map() -> StatusMap:
    """Default DefectStatus ↔ GitHub Issue state mapping.

    GitHub Issues lack a workflow state machine, so RESOLVED / CLOSED /
    WONT_FIX all collapse to ``closed``. IN_PROGRESS stays ``open`` — the FE
    layers a label on top to communicate nuance to humans.

    The reverse direction (``external_to_defect``) is registered explicitly
    via :meth:`StatusMap.register_alias` so a webhook payload of ``"closed"``
    resolves to :attr:`DefectStatus.CLOSED` (the most conservative interp).
    """
    sm = StatusMap(
        {
            DefectStatus.OPEN: "open",
            DefectStatus.IN_PROGRESS: "open",
            DefectStatus.RESOLVED: "closed",
            DefectStatus.CLOSED: "closed",
            DefectStatus.WONT_FIX: "closed",
        }
    )
    # Reverse: pick the most-informative DefectStatus for each external state.
    sm.register_alias("open", DefectStatus.OPEN)
    sm.register_alias("closed", DefectStatus.CLOSED)
    return sm


# Stable, non-overlapping label set the adapter appends on every create.
_SUITEST_LABEL: str = "suitest"
_SEVERITY_LABEL_PREFIX: str = "severity:"


def _severity_label(severity: Severity) -> str:
    """Map a Suitest :class:`Severity` to its canonical GitHub label name."""
    return f"{_SEVERITY_LABEL_PREFIX}{severity.value.lower()}"


# ---------------------------------------------------------------------------
# JWT signing for GitHub App auth (RS256, no PyJWT).
# ---------------------------------------------------------------------------


def _b64url(payload: bytes) -> str:
    """URL-safe Base64 encode with the JWT-mandated ``=`` stripping."""
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _sign_app_jwt(*, app_id: int | str, private_key_pem: str, now: int | None = None) -> str:
    """Build + sign a GitHub App JWT (RS256, 9-minute lifetime).

    Per GitHub's docs we set ``iat`` 30 s in the past to absorb clock skew and
    ``exp`` 9 minutes ahead (well under the 10-minute hard cap). The ``iss``
    claim MUST be the App ID as a string.
    """
    issued_at = (now if now is not None else int(time.time())) - _APP_JWT_SKEW_SECONDS
    expires_at = issued_at + _APP_JWT_LIFETIME_SECONDS + _APP_JWT_SKEW_SECONDS
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": issued_at, "exp": expires_at, "iss": str(app_id)}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(key, RSAPrivateKey):
        raise AdapterAuthError("GitHub App private key must be an RSA PEM (RS256)")
    signature = key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return signing_input + "." + _b64url(signature)


# ---------------------------------------------------------------------------
# GitHubAdapter
# ---------------------------------------------------------------------------


class GitHubAdapter:
    """Thin wrapper over the bundled ``github-mcp-server`` Go binary.

    Constructor wiring is deliberately verbose so the FastAPI lifespan can pass
    the same long-lived dependencies (mcp_client, crypto helper, ``AsyncClient``)
    to every concrete adapter without a DI framework. ``integration`` is the
    persisted :class:`Integration` row (with ``config_json.app_id /
    installation_id / owner / repo`` + AES-GCM ``secrets_encrypted`` storing the
    App private key PEM under ``"private_key_pem"``).

    Public surface matches :class:`IssueTrackerAdapter` (``kind``,
    ``test_connection``, ``create_external_issue``, ``update_external_issue``,
    ``transition_status``, ``map_external_status_to_defect_status``).
    """

    kind: IntegrationKind = IntegrationKind.GITHUB

    def __init__(
        self,
        *,
        integration: Integration,
        mcp_client: McpClientProtocol,
        crypto: CryptoServiceProtocol,
        http_client: httpx.AsyncClient,
        status_map: StatusMap | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.integration = integration
        self.mcp_client = mcp_client
        self.crypto = crypto
        self.http = http_client
        # Tests inject ``now=lambda: 1234567890`` to freeze time without
        # monkey-patching the module-global ``time.time``. Default uses wall
        # clock so production code path matches the test contract exactly.
        self._now: Callable[[], float] = now if now is not None else time.time
        self._status_map: StatusMap = status_map if status_map is not None else _build_status_map()
        # Token cache keyed by installation_id — multiple adapters per workspace
        # (single-tenant App) share one cache entry. The dict is unbounded by
        # design: a workspace can't grow its installation list at runtime.
        self._token_cache: dict[str, tuple[str, float]] = {}

    # ---- Configuration accessors -----------------------------------------

    @property
    def _app_id(self) -> int:
        try:
            return int(self.integration.config["app_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterAuthError("Integration.config.app_id missing or not numeric") from exc

    @property
    def _installation_id(self) -> str:
        try:
            return str(self.integration.config["installation_id"])
        except (KeyError, TypeError) as exc:
            raise AdapterAuthError("Integration.config.installation_id missing") from exc

    @property
    def _owner(self) -> str:
        try:
            return str(self.integration.config["owner"])
        except (KeyError, TypeError) as exc:
            raise AdapterAuthError("Integration.config.owner missing") from exc

    @property
    def _repo(self) -> str:
        try:
            return str(self.integration.config["repo"])
        except (KeyError, TypeError) as exc:
            raise AdapterAuthError("Integration.config.repo missing") from exc

    def _decrypt_private_key_pem(self) -> str:
        """Decrypt the App private key PEM from ``integration.secrets_encrypted``.

        Stored shape (AES-GCM plaintext): ``{"private_key_pem": "<PEM>"}``.
        """
        secrets_encrypted = self.integration.secrets_encrypted
        if secrets_encrypted is None:
            raise AdapterAuthError("Integration.secrets_encrypted missing for GitHub App")
        # ``Integration.secrets_encrypted`` is declared as ``EncryptedBytes``
        # which transparently decrypts to ``str`` on read — but tests + raw
        # repo flows can also pass the encrypted bytes blob. Accept both.
        if isinstance(secrets_encrypted, bytes):
            plaintext = self.crypto.decrypt(secrets_encrypted)
        else:
            plaintext = str(secrets_encrypted)
        try:
            secrets = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise AdapterAuthError("Integration.secrets_encrypted is not valid JSON") from exc
        pem = secrets.get("private_key_pem")
        if not isinstance(pem, str) or not pem.strip():
            raise AdapterAuthError("secrets.private_key_pem missing or not a string")
        return pem

    def _wall_time(self) -> float:
        """Resolve the current monotonic-ish wall clock (test-injectable)."""
        return float(self._now())

    # ---- App-installation token mint + cache -----------------------------

    async def _installation_token(self) -> str:
        """Return a valid installation token, mintting a fresh one if the cache is stale.

        Cache TTL is 50 minutes (``_TOKEN_TTL_SECONDS``); after that we mint a
        new App JWT, exchange it for an installation token, and store
        ``(token, expires_at)`` keyed by ``installation_id``. Mint failures
        surface as :class:`AdapterAuthError` (401 / non-2xx) or
        :class:`AdapterRemoteError` (network).
        """
        cache_key = self._installation_id
        now = self._wall_time()
        cached = self._token_cache.get(cache_key)
        if cached is not None:
            token, expires_at = cached
            if now < expires_at:
                return token

        app_jwt = _sign_app_jwt(
            app_id=self._app_id,
            private_key_pem=self._decrypt_private_key_pem(),
            now=int(now),
        )
        url = _INSTALLATIONS_URL.format(installation_id=cache_key)
        try:
            response = await self.http.post(
                url,
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": _GH_API_VERSION_HEADER,
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10.0,
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(f"GitHub App token mint timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AdapterRemoteError(f"GitHub App token mint network error: {exc}") from exc

        if response.status_code in (401, 403):
            raise AdapterAuthError(
                f"GitHub App token mint failed: {response.status_code} {response.text}"
            )
        if response.status_code >= 400:
            raise AdapterRemoteError(
                f"GitHub App token mint failed: {response.status_code} {response.text}"
            )
        try:
            payload = response.json()
            token = payload["token"]
        except (ValueError, KeyError) as exc:
            raise AdapterRemoteError("GitHub App token mint returned unexpected body") from exc
        if not isinstance(token, str) or not token:
            raise AdapterRemoteError("GitHub App token mint returned empty token")

        self._token_cache[cache_key] = (token, now + _TOKEN_TTL_SECONDS)
        return token

    # ---- MCP invoke helper -----------------------------------------------

    async def _invoke(self, tool: str, arguments: dict[str, object]) -> dict[str, object]:
        """Dispatch one MCP tool call against ``github-mcp`` with env injection.

        Builds the per-invocation env (``GITHUB_PERSONAL_ACCESS_TOKEN`` +
        ``GITHUB_TOOLSETS=issues``) so the secret never touches the persisted
        ``McpProvider.env`` blob. Translates :class:`McpError` subclasses into
        :class:`AdapterError` subclasses so the caller has one exception base.
        """
        token = await self._installation_token()
        env_overrides: dict[str, str] = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
            "GITHUB_TOOLSETS": _GITHUB_TOOLSETS_VALUE,
        }
        try:
            result = await self.mcp_client.invoke(
                provider=_PROVIDER_NAME,
                tool=tool,
                arguments=arguments,
                env_overrides=env_overrides,
                workspace_id=self.integration.workspace_id,
            )
        except McpError as exc:
            self._translate_mcp_error(exc)
            raise  # pragma: no cover - _translate_mcp_error always raises
        return result.output

    def _translate_mcp_error(self, exc: McpError) -> None:
        """Re-raise an :class:`McpError` as the matching :class:`AdapterError`.

        The mapping is intentionally lossy (we collapse handshake / pool /
        provider-unavailable into AdapterRemoteError) because the upstream
        callers only branch on auth vs rate-limit vs everything-else.
        """
        message = str(exc)
        upper = message.upper()
        # Surface GitHub's 401 / 403 (auth invalid) regardless of where the
        # MCP layer wrapped it — the binary surfaces them as ``McpToolFailed``
        # with the HTTP status embedded.
        if "401" in upper or "UNAUTHORIZED" in upper or "BAD CREDENTIALS" in upper:
            raise AdapterAuthError(f"github-mcp auth rejected: {message}") from exc
        if "403" in upper and "RATE LIMIT" in upper:
            raise AdapterRateLimitError(f"github-mcp rate limited: {message}") from exc
        if exc.code == "MCP_TOOL_TIMEOUT":
            raise AdapterTimeoutError(f"github-mcp tool timed out: {message}") from exc
        raise AdapterRemoteError(f"github-mcp tool failed: {message}") from exc

    # ---- IssueTrackerAdapter surface -------------------------------------

    async def test_connection(self) -> ConnectionTestResult:
        """Round-trip the cheapest read-only call.

        We invoke ``list_issues`` with ``per_page=1`` so the cost stays at one
        GitHub API call regardless of repository size. On any failure we return
        ``ConnectionTestResult(ok=False, error=...)`` rather than raising so the
        Integrations page renders the error inline.
        """
        try:
            await self._invoke(
                "list_issues",
                {
                    "owner": self._owner,
                    "repo": self._repo,
                    "state": "open",
                    "per_page": 1,
                },
            )
        except AdapterAuthError as exc:
            return ConnectionTestResult(ok=False, error=f"Authentication failed: {exc}")
        except (AdapterTimeoutError, AdapterRateLimitError, AdapterRemoteError) as exc:
            return ConnectionTestResult(ok=False, error=str(exc))
        return ConnectionTestResult(
            ok=True,
            account_id=str(self._app_id),
            display_name=f"{self._owner}/{self._repo}",
        )

    async def create_external_issue(self, body: ExternalIssueInput) -> ExternalIssue:
        """Create a new GitHub issue via ``issue_write`` (action=create).

        Labels applied: a stable ``suitest`` provenance label plus the
        severity-prefixed label (e.g. ``severity:high``). Caller-supplied
        ``body.labels`` are merged in deterministically (deduped + sorted) so
        the same input produces the same wire payload.
        """
        labels = _merge_labels(body.labels, body.severity)
        arguments: dict[str, object] = {
            "action": "create",
            "owner": self._owner,
            "repo": self._repo,
            "title": body.title,
            "body": body.description,
            "labels": labels,
        }
        if body.assignee_external_id:
            arguments["assignees"] = [body.assignee_external_id]
        output = await self._invoke("issue_write", arguments)
        return self._to_external_issue(output)

    async def update_external_issue(
        self, external_key: str, body: ExternalIssueInput
    ) -> ExternalIssue:
        """Patch an existing issue via ``issue_write`` (action=update).

        ``external_key`` is the GitHub issue number (e.g. ``"#42"`` or ``"42"``).
        We strip a leading ``#`` defensively so callers don't have to.
        """
        issue_number = _parse_issue_number(external_key)
        labels = _merge_labels(body.labels, body.severity)
        arguments: dict[str, object] = {
            "action": "update",
            "owner": self._owner,
            "repo": self._repo,
            "issue_number": issue_number,
            "title": body.title,
            "body": body.description,
            "labels": labels,
        }
        if body.assignee_external_id:
            arguments["assignees"] = [body.assignee_external_id]
        output = await self._invoke("issue_write", arguments)
        return self._to_external_issue(output)

    async def fetch_external_issue(self, external_key: str) -> ExternalIssue:
        """Read-only ``issue_read`` to refresh the live :class:`ExternalIssue`."""
        issue_number = _parse_issue_number(external_key)
        output = await self._invoke(
            "issue_read",
            {
                "action": "get",
                "owner": self._owner,
                "repo": self._repo,
                "issue_number": issue_number,
            },
        )
        return self._to_external_issue(output)

    async def transition_status(self, external_key: str, new_status: DefectStatus) -> None:
        """Move an issue to ``open`` / ``closed`` per the :class:`StatusMap`.

        We call ``issue_write`` with ``action=update`` and the resolved state
        rather than the GitHub-specific ``add_issue_comment`` workflow, so a
        future webhook receiver can map the synthetic event back to a Suitest
        DefectStatus deterministically.
        """
        target = self._status_map.defect_to_external(new_status)
        if target is None:
            raise AdapterRemoteError(
                f"DefectStatus {new_status.value} has no GitHub mapping in status_map"
            )
        issue_number = _parse_issue_number(external_key)
        await self._invoke(
            "issue_write",
            {
                "action": "update",
                "owner": self._owner,
                "repo": self._repo,
                "issue_number": issue_number,
                "state": target,
            },
        )

    def map_external_status_to_defect_status(self, external_status: str) -> DefectStatus | None:
        """Translate a remote status (e.g. webhook payload's ``"closed"``)."""
        return self._status_map.external_to_defect(external_status)

    async def add_issue_comment(self, external_key: str, comment: str) -> None:
        """Append a free-form comment to an existing issue.

        Surfaced for the M1d-9 ``sync_external`` workflow which posts a
        Suitest-side back-reference into the GitHub issue thread.
        """
        issue_number = _parse_issue_number(external_key)
        await self._invoke(
            "add_issue_comment",
            {
                "owner": self._owner,
                "repo": self._repo,
                "issue_number": issue_number,
                "body": comment,
            },
        )

    # ---- Wire normalisation ----------------------------------------------

    def _to_external_issue(self, raw: dict[str, object]) -> ExternalIssue:
        """Normalise github-mcp's ``issue_write`` payload into :class:`ExternalIssue`.

        The Go binary surfaces the GitHub REST response verbatim — we read
        ``number`` (issue number), ``node_id`` (graphql id), ``html_url``, and
        ``state`` defensively because schema drift across upstream versions is
        a real risk for a ``v1.x`` binary.
        """
        number_value = raw.get("number")
        if number_value is None:
            raise AdapterRemoteError("github-mcp issue_write response missing 'number'")
        external_key = f"#{number_value}"
        external_id_value = raw.get("node_id")
        external_id = (
            str(external_id_value) if isinstance(external_id_value, str) else str(number_value)
        )
        html_url = raw.get("html_url")
        if not isinstance(html_url, str) or not html_url:
            html_url = f"https://github.com/{self._owner}/{self._repo}/issues/{number_value}"
        state = raw.get("state")
        external_status = state if isinstance(state, str) else "open"
        return ExternalIssue(
            external_id=external_id,
            external_key=external_key,
            external_url=html_url,
            external_status=external_status,
            raw_payload=raw,
        )


def _parse_issue_number(external_key: str) -> int:
    """Coerce ``"#42"`` / ``"42"`` to the integer GitHub expects."""
    raw = external_key.lstrip("#").strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise AdapterRemoteError(
            f"external_key {external_key!r} is not a GitHub issue number"
        ) from exc


def _merge_labels(extra: list[str], severity: Severity) -> list[str]:
    """Build the canonical label set for one create / update call.

    Always includes ``suitest`` (provenance) + the severity-derived label.
    Caller-supplied ``extra`` is merged in, deduped case-insensitively, and
    sorted so the wire payload is deterministic across retries.
    """
    base = {_SUITEST_LABEL, _severity_label(severity)}
    for label in extra:
        cleaned = label.strip()
        if cleaned:
            base.add(cleaned)
    return sorted(base)
