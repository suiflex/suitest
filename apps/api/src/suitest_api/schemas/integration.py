"""Integration request + response DTOs (docs/API.md §3.9) — secrets always REDACTED.

The full encrypted secret is NEVER serialised. ``SecretsHint`` carries only a
``redacted=True`` marker and a ``hint`` (the last 4 chars of the decrypted secret),
matching ``{"redacted": true, "hint": "...last4"}`` from API.md §3.9. ``secrets`` is
``null`` when no secret is configured.

M1d-19 add the write surface:

* :class:`IntegrationCreate` / :class:`IntegrationUpdate` — request bodies.
* :class:`IntegrationRead` — write-path response (same shape as
  :class:`IntegrationDetail` but explicit so the router signatures stay clear).
* :class:`ConnectionTestResponse` — return shape for ``POST /integrations/:id/test``
  and the two pre-save ``test-connection`` endpoints. Mirrors
  :class:`suitest_api.integrations.base.ConnectionTestResult` but JSON-friendly.
* :class:`SyncResult` — return shape for ``POST /integrations/:id/sync``.
* :class:`JiraTestConnectionRequest` / :class:`GitHubTestConnectionRequest` —
  pre-save credential payloads. These are never persisted; the router spawns
  an ephemeral adapter, invokes ``test_connection``, and discards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import IntegrationKind


class SecretsHint(BaseModel):
    """Redacted secret marker + last-4 hint (no full secret ever)."""

    redacted: bool = True
    hint: str | None = None


class IntegrationListItem(BaseModel):
    """List row for ``GET /integrations`` (config visible, no secret material)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    kind: IntegrationKind
    name: str
    status: str
    has_secrets: bool
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IntegrationDetail(IntegrationListItem):
    """Detail — adds visible ``config`` and the redacted ``secrets`` block."""

    config: dict[str, Any]
    secrets: SecretsHint | None = None


class IntegrationRead(IntegrationListItem):
    """Write-path response: ``config`` is visible but secrets stay opaque.

    Deliberately ``model_config`` does NOT add a ``secrets`` field — the only
    cue the FE gets that secrets exist is ``has_secrets: bool``. The ``config``
    field is allowed because integration config (``Jira url``, ``Slack channel
    name``) is non-sensitive metadata; the AES-GCM blob lives only in the
    database column. See ``docs/API.md §3.9``.
    """

    config: dict[str, Any]


class IntegrationCreate(BaseModel):
    """``POST /integrations`` request body.

    ``secrets`` is an arbitrary JSON-object the kind-specific adapter consumes
    (e.g. Slack: ``{"webhook_url": "..."}``, Jira: ``{"jira_token": "..."}``).
    The service AES-GCM-encrypts it via ``packages/core/crypto`` before INSERT.
    ``status`` defaults to ``active`` and is set by the service — accepting it
    from the wire would let an admin force-set bypassed states.
    """

    model_config = ConfigDict(extra="forbid")

    kind: IntegrationKind
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Adapter-specific secret material (e.g. Slack webhook_url, Jira "
            "token). Encrypted at rest via AES-GCM; never echoed back."
        ),
    )


class IntegrationUpdate(BaseModel):
    """``PATCH /integrations/:id`` request body — partial update.

    ``secrets`` semantics:

    * absent from body → existing encrypted blob preserved verbatim.
    * present but empty dict → existing blob CLEARED (the integration becomes
      secret-less; ``has_secrets`` flips to False).
    * present with keys → MERGED with the existing decrypted dict before
      re-encrypting (FE doesn't have to know every secret key). Submitted keys
      overwrite; unsubmitted keys retain prior values.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    status: str | None = Field(default=None, max_length=32)


class ConnectionTestResponse(BaseModel):
    """JSON response for ``/test`` + pre-save ``test-connection`` endpoints.

    Mirrors :class:`suitest_api.integrations.base.ConnectionTestResult` 1:1 so
    the FE can render the same UI for both pre-save and post-save flows. On
    success ``ok=True`` and ``account_id``/``display_name`` describe who the
    adapter authenticated as. On failure ``ok=False`` and ``error`` carries
    the human-readable string the FE renders inline.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    account_id: str | None = None
    display_name: str | None = None
    error: str | None = None


class SyncConflict(BaseModel):
    """One entry in :class:`SyncResult.conflicts` — local state diverges from remote.

    Surfaces the defect public id + the local / remote DefectStatus strings so
    the FE renders a clear "external system says X but Suitest says Y" prompt.
    """

    defect_public_id: str
    local_status: str
    remote_status: str
    external_id: str


class SyncResult(BaseModel):
    """``POST /integrations/:id/sync`` response.

    ``synced`` counts defects whose ``status`` was updated to match the remote
    system. ``conflicts`` lists defects whose remote state could not be applied
    without overwriting a manual change (e.g. local CLOSED, remote OPEN → the
    sync respects manual override). ``skipped`` counts defects ignored because
    they were already in a terminal status.
    """

    model_config = ConfigDict(extra="forbid")

    synced: int = 0
    skipped: int = 0
    conflicts: list[SyncConflict] = Field(default_factory=list)


class JiraTestConnectionRequest(BaseModel):
    """Pre-save credential payload for ``POST /integrations/jira/test-connection``.

    No row is persisted; the router spawns an ephemeral ``jirac-mcp`` adapter
    with these creds, calls ``test_connection`` (``GET /rest/api/3/myself``),
    and discards the process. ``jira_auth_type`` selects between cloud OAuth
    token (``cloud_token``) and PAT (``pat``). M1d ships PAT-only — OAuth flow
    deferred to v1.x.
    """

    model_config = ConfigDict(extra="forbid")

    jira_url: str = Field(min_length=1)
    jira_email: str = Field(min_length=1)
    jira_token: str = Field(min_length=1)
    jira_auth_type: Literal["cloud_token", "pat"] = "cloud_token"


class GitHubTestConnectionRequest(BaseModel):
    """Pre-save credential payload for ``POST /integrations/github/test-connection``.

    No row is persisted. ``private_key_pem`` is never logged and never stored
    by this endpoint (per ``docs/API.md §3.9``). The router spawns an ephemeral
    ``github-mcp-server`` process, derives an installation token, calls a
    cheap whoami / list-repos tool, and discards.
    """

    model_config = ConfigDict(extra="forbid")

    app_installation_id: str = Field(min_length=1)
    private_key_pem: str = Field(min_length=1)
