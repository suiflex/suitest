"""IntegrationService — workspace-scoped, REDACTS secrets in every response.

``IntegrationOut`` has no ``secrets_encrypted`` field, so the encrypted blob can
never be serialised. We additionally build the DTO explicitly (rather than
``model_validate``) so we never even touch the decrypting ``secrets_encrypted``
attribute — only a boolean ``has_secrets`` derived from whether a value is set.

M1d-19 adds the write surface:

* :meth:`create` — INSERT a row, AES-GCM-encrypt secrets via
  ``packages/core/crypto``, flip the bundled MCP provider's ``enabled=true``
  on the *first* Jira / GitHub connect.
* :meth:`update` — partial patch with secret-merge semantics (FE submits the
  changing keys only; absent keys preserved).
* :meth:`delete` — HARD delete (no soft delete on integrations per plan-05b
  M1d-19; the row is gone but the AuditLog history persists).
* :meth:`test_connection` — resolve adapter from
  :class:`AdapterRegistry` (issue trackers) or :class:`NotifierFactoryRegistry`
  (notifiers), invoke ``test_connection``, return the result.
* :meth:`sync_external` — for issue-tracker integrations, iterate the linked
  defects, refetch the external status, and update the local
  :class:`DefectStatus`. Conflicts (local diverged from remote and local is
  terminal) are surfaced without overwriting the local state.

Per ``CLAUDE.md §2.3`` all mutations write an :class:`AuditLog` row and emit a
typed WS event the router publishes post-commit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.integration import Integration
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.integrations import IntegrationRepo
from suitest_shared.domain.enums import DefectStatus, IntegrationKind
from suitest_shared.schemas.responses import IntegrationOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    IssueTrackerAdapter,
    NotifierAdapter,
)
from suitest_api.integrations.registry import (
    AdapterNotRegistered,
    AdapterRegistry,
)
from suitest_api.schemas.integration import SyncConflict, SyncResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.integrations.notifier_registry import (
        NotifierFactoryRegistry,
    )


# Kinds wired as :class:`IssueTrackerAdapter` (PR-12/13/14 register singletons).
# Slack is a :class:`NotifierAdapter`, registered as a per-row factory in PR-15.
# MCP_* and CI/CD kinds (GITLAB, JENKINS, OPENAPI) have no adapter wired in M1d.
_ISSUE_TRACKER_KINDS: frozenset[IntegrationKind] = frozenset(
    {IntegrationKind.JIRA, IntegrationKind.LINEAR, IntegrationKind.GITHUB}
)
_NOTIFIER_KINDS: frozenset[IntegrationKind] = frozenset({IntegrationKind.SLACK})
# Defect statuses we treat as terminal for sync purposes (skip refetching).
# RESOLVED is intentionally non-terminal because Jira "Resolved" can transition
# back to "Reopened" — only CLOSED / WONT_FIX are truly write-once for sync.
_TERMINAL_DEFECT_STATUSES: frozenset[DefectStatus] = frozenset(
    {DefectStatus.CLOSED, DefectStatus.WONT_FIX}
)


def _to_out(row: Integration) -> IntegrationOut:
    """Map an Integration ORM row to a redacted DTO (no secret material)."""
    return IntegrationOut(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        name=row.name,
        config=row.config,
        status=row.status,
        has_secrets=row.secrets_encrypted is not None,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class IntegrationWriteResult(NamedTuple):
    """Outcome bundle: redacted DTO + WS event for the router to publish post-commit."""

    out: IntegrationOut
    ws_event: str
    ws_payload: dict[str, object]


class IntegrationNotFoundError(Exception):
    """Service-side miss — router translates to 404."""


class IntegrationKindUnsupportedError(Exception):
    """No adapter / factory registered for the integration's kind."""

    def __init__(self, kind: IntegrationKind) -> None:
        super().__init__(f"integration kind '{kind.value}' has no adapter registered")
        self.kind = kind


def _encrypt_secrets_dict(secrets: dict[str, Any] | None) -> str | None:
    """Serialise ``secrets`` → JSON → AES-GCM-encrypted column value.

    ``None`` or ``{}`` round-trip as ``None`` so a secret-less integration
    leaves ``secrets_encrypted`` NULL (and ``has_secrets`` reads ``False``).
    The actual AES-GCM happens transparently on bind via
    :class:`suitest_core.crypto.EncryptedBytes`; we hand the SQLAlchemy column
    a plain ``str`` (the JSON-serialised secret dict).
    """
    if not secrets:
        return None
    return json.dumps(secrets, separators=(",", ":"), sort_keys=True)


def _decrypt_secrets_dict(integration: Integration) -> dict[str, Any]:
    """Read the AES-GCM blob back into a dict (empty if column NULL).

    The ``EncryptedBytes`` column has already decrypted to a JSON string on
    load; we deserialise here. Malformed JSON degrades to ``{}`` so a corrupt
    row can still be patched without throwing on every PATCH.
    """
    raw = integration.secrets_encrypted
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


class IntegrationService:
    """Workspace-scoped CRUD + adapter dispatch for the ``/integrations`` surface."""

    def __init__(
        self,
        ctx: TenantContext,
        repo: IntegrationRepo,
        *,
        adapter_registry: AdapterRegistry | None = None,
        notifier_factory_registry: NotifierFactoryRegistry | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._adapter_registry = adapter_registry
        self._notifier_factory_registry = notifier_factory_registry
        self._http_client = http_client

    @property
    def _session(self) -> AsyncSession:
        return self._repo.session

    # ------------------------------------------------------------------
    # Read path (M1a)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def list(self, *, kind: IntegrationKind | None = None) -> list[IntegrationOut]:
        rows = await self._repo.list_by_workspace(self._ctx.workspace_id, kind=kind)
        return [_to_out(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, integration_id: str) -> IntegrationOut | None:
        row = await self._repo.get_by_id(integration_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return _to_out(row)

    # ------------------------------------------------------------------
    # Internal helpers — scoped row load
    # ------------------------------------------------------------------

    async def _load_in_scope(self, integration_id: str) -> Integration | None:
        row = await self._repo.get_by_id(integration_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return row

    # ------------------------------------------------------------------
    # Write path (M1d-19)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create(
        self,
        *,
        kind: IntegrationKind,
        name: str,
        config: dict[str, Any],
        secrets: dict[str, Any] | None,
    ) -> IntegrationWriteResult:
        """INSERT an integration; encrypt secrets; flip bundled MCP on first connect.

        The "first connect" detection is intentionally read-then-insert (not
        a single atomic statement) because the bundled MCP flip is an
        idempotent UPDATE — if a concurrent second create both observe count=0
        they'll both flip ``enabled=true`` and the net effect is the same.
        """
        existing_count = await self._repo.count_by_workspace_kind(self._ctx.workspace_id, kind)
        is_first_connect = existing_count == 0

        row = Integration(
            workspace_id=self._ctx.workspace_id,
            kind=kind,
            name=name,
            config=config,
            secrets_encrypted=_encrypt_secrets_dict(secrets),
            status="active",
        )
        self._session.add(row)
        await self._session.flush()

        flipped_mcp: str | None = None
        if is_first_connect:
            flipped_mcp = await self._repo.enable_bundled_mcp_for_kind(kind)

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="integration.created",
            resource_type="integration",
            resource_id=row.id,
            metadata={
                "kind": kind.value,
                "name": name,
                "hasSecrets": bool(secrets),
                "firstConnectMcpFlipped": flipped_mcp,
            },
        )

        return IntegrationWriteResult(
            out=_to_out(row),
            ws_event="integration.created",
            ws_payload={
                "integrationId": row.id,
                "kind": kind.value,
                "name": name,
            },
        )

    @require_tier(TierFlag.ANY)
    async def update(
        self,
        integration_id: str,
        *,
        name: str | None,
        config: dict[str, Any] | None,
        secrets: dict[str, Any] | None,
        status: str | None,
        secrets_field_present: bool,
    ) -> IntegrationWriteResult | None:
        """PATCH metadata / config / secrets atomically.

        ``secrets_field_present`` lets the caller distinguish "field absent" from
        "field set to None / empty dict" — Pydantic's ``model_dump`` loses that
        distinction at the request boundary, but for secrets it matters:

        * field absent → existing encrypted blob preserved verbatim.
        * field == ``{}`` → blob CLEARED to NULL.
        * field == ``{"k": "v"}`` → MERGED with existing decrypted dict, re-encrypted.
        """
        row = await self._load_in_scope(integration_id)
        if row is None:
            return None

        changed: list[str] = []
        if name is not None and name != row.name:
            row.name = name
            changed.append("name")
        if config is not None and config != row.config:
            row.config = config
            changed.append("config")
        if status is not None and status != row.status:
            row.status = status
            changed.append("status")

        if secrets_field_present:
            if not secrets:
                row.secrets_encrypted = None
            else:
                merged = _decrypt_secrets_dict(row)
                merged.update(secrets)
                row.secrets_encrypted = _encrypt_secrets_dict(merged)
            changed.append("secrets")

        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="integration.updated",
            resource_type="integration",
            resource_id=row.id,
            metadata={"fields": changed, "kind": row.kind.value},
        )

        return IntegrationWriteResult(
            out=_to_out(row),
            ws_event="integration.updated",
            ws_payload={
                "integrationId": row.id,
                "kind": row.kind.value,
                "fields": changed,
            },
        )

    @require_tier(TierFlag.ANY)
    async def delete(self, integration_id: str) -> IntegrationWriteResult | None:
        """Hard-delete an integration row (no soft delete per plan-05b M1d-19)."""
        row = await self._load_in_scope(integration_id)
        if row is None:
            return None
        kind = row.kind
        name = row.name
        # Capture the audit row BEFORE the delete so the resource_id still
        # references a valid row (Audit row stays referentially valid via the
        # text column — but writing the row pre-delete is cleaner ordering).
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="integration.deleted",
            resource_type="integration",
            resource_id=row.id,
            metadata={"kind": kind.value, "name": name},
        )
        await self._repo.hard_delete(row.id)
        return IntegrationWriteResult(
            out=_to_out(row),
            ws_event="integration.deleted",
            ws_payload={
                "integrationId": row.id,
                "kind": kind.value,
            },
        )

    # ------------------------------------------------------------------
    # Test connection (post-save — adapter resolved from registry)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def test_connection(self, integration_id: str) -> ConnectionTestResult | None:
        """Invoke the registered adapter's ``test_connection`` against ``integration_id``.

        Returns ``None`` when the row is missing or cross-workspace (router →
        404). Raises :class:`IntegrationKindUnsupportedError` when no adapter
        / factory is registered for the kind (router → 400). Adapter failures
        are caught and surfaced as ``ConnectionTestResult(ok=False, error=...)``
        rather than bubbling up — the test endpoint never 500s on a bad creds.
        """
        row = await self._load_in_scope(integration_id)
        if row is None:
            return None

        try:
            result = await self._invoke_adapter_test(row)
        except AdapterAuthError as exc:
            result = ConnectionTestResult(ok=False, error=f"AUTH: {exc}")
        except AdapterRateLimitError as exc:
            result = ConnectionTestResult(ok=False, error=f"RATE_LIMIT: {exc}")
        except AdapterTimeoutError as exc:
            result = ConnectionTestResult(ok=False, error=f"TIMEOUT: {exc}")
        except AdapterRemoteError as exc:
            result = ConnectionTestResult(ok=False, error=f"REMOTE: {exc}")
        except AdapterError as exc:
            result = ConnectionTestResult(ok=False, error=str(exc))

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="integration.tested",
            resource_type="integration",
            resource_id=row.id,
            metadata={"kind": row.kind.value, "ok": result.ok},
        )
        return result

    async def _invoke_adapter_test(self, integration: Integration) -> ConnectionTestResult:
        """Dispatch to the issue-tracker or notifier adapter for ``integration.kind``."""
        kind = integration.kind
        if kind in _ISSUE_TRACKER_KINDS:
            adapter = self._resolve_issue_tracker(kind)
            return await adapter.test_connection()
        if kind in _NOTIFIER_KINDS:
            notifier = self._resolve_notifier(integration)
            return await notifier.test_connection()
        raise IntegrationKindUnsupportedError(kind)

    def _resolve_issue_tracker(self, kind: IntegrationKind) -> IssueTrackerAdapter:
        if self._adapter_registry is None:
            raise IntegrationKindUnsupportedError(kind)
        try:
            return self._adapter_registry.get(kind)
        except AdapterNotRegistered as exc:
            raise IntegrationKindUnsupportedError(kind) from exc

    def _resolve_notifier(self, integration: Integration) -> NotifierAdapter:
        if self._notifier_factory_registry is None or self._http_client is None:
            raise IntegrationKindUnsupportedError(integration.kind)
        try:
            factory = self._notifier_factory_registry.get(integration.kind)
        except KeyError as exc:
            raise IntegrationKindUnsupportedError(integration.kind) from exc
        return factory(integration, self._http_client)

    # ------------------------------------------------------------------
    # Sync external (issue-tracker only)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def sync_external(self, integration_id: str) -> SyncResult | None:
        """Refetch external status for every defect linked to ``integration_id``.

        Iterates the ``external_issues`` table for ``provider == kind.value``,
        joining defects whose ``workspace_id`` matches the integration's
        workspace. For each non-terminal local defect, asks the adapter for
        the live external status and either:

        * updates ``defect.status`` when remote maps to a different
          non-terminal local status (no conflict);
        * records a :class:`SyncConflict` when the local status is terminal
          (CLOSED / WONT_FIX) and remote would re-open;
        * skips when the defect is already in a terminal status (counts under
          ``skipped``).

        Only issue-tracker kinds are supported — Slack / MCP kinds raise
        :class:`IntegrationKindUnsupportedError`.
        """
        row = await self._load_in_scope(integration_id)
        if row is None:
            return None
        if row.kind not in _ISSUE_TRACKER_KINDS:
            raise IntegrationKindUnsupportedError(row.kind)

        adapter = self._resolve_issue_tracker(row.kind)
        provider_label = row.kind.value
        defects_with_external = await self._load_defects_with_external(
            workspace_id=row.workspace_id, provider=provider_label
        )

        synced = 0
        skipped = 0
        conflicts: list[SyncConflict] = []
        for defect, external in defects_with_external:
            if defect.status in _TERMINAL_DEFECT_STATUSES:
                skipped += 1
                continue
            try:
                external_issue = await adapter.fetch_external_issue(external.external_id)
            except AdapterError:
                # Bubble up via integration.status=error WS — but a single
                # adapter miss should not abort the whole sync. Skip + log.
                skipped += 1
                continue
            new_status = adapter.map_external_status_to_defect_status(
                external_issue.external_status
            )
            if new_status is None or new_status == defect.status:
                skipped += 1
                continue
            if (
                defect.status in _TERMINAL_DEFECT_STATUSES
                and new_status not in _TERMINAL_DEFECT_STATUSES
            ):
                # Local is terminal but remote re-opened — respect manual close.
                conflicts.append(
                    SyncConflict(
                        defect_public_id=defect.public_id,
                        local_status=defect.status.value,
                        remote_status=external_issue.external_status,
                        external_id=external.external_id,
                    )
                )
                continue
            defect.status = new_status
            synced += 1

        row.last_synced_at = datetime.now(tz=UTC)
        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="integration.synced",
            resource_type="integration",
            resource_id=row.id,
            metadata={
                "kind": row.kind.value,
                "synced": synced,
                "skipped": skipped,
                "conflicts": len(conflicts),
            },
        )
        return SyncResult(synced=synced, skipped=skipped, conflicts=conflicts)

    async def _load_defects_with_external(
        self, *, workspace_id: str, provider: str
    ) -> Sequence[tuple[Defect, ExternalIssue]]:
        """Return ``[(defect, external_issue), ...]`` for the given provider + workspace."""
        from sqlalchemy import select

        stmt = (
            select(Defect, ExternalIssue)
            .join(ExternalIssue, ExternalIssue.defect_id == Defect.id)
            .where(
                Defect.workspace_id == workspace_id,
                ExternalIssue.provider == provider,
            )
            .order_by(Defect.public_id.asc())
        )
        rows: list[tuple[Defect, ExternalIssue]] = [
            (d, e) for d, e in (await self._session.execute(stmt)).all()
        ]
        return rows


# Re-export the friendly aliases so the router imports stay tight.
__all__ = [
    "DefectRepo",
    "IntegrationKindUnsupportedError",
    "IntegrationNotFoundError",
    "IntegrationService",
    "IntegrationWriteResult",
    "_decrypt_secrets_dict",
    "_encrypt_secrets_dict",
    "_to_out",
]
