"""Shared utilities for inbound webhook receivers.

M1d-18 (Jira) is the first receiver on this branch line, but the helpers here
are deliberately decoupled from any one provider so M1d-16 (GitHub) and M1d-17
(GitLab) can plug in without copy/paste when they land. Two primitives ship:

1. **Workspace resolution by URL-secret** — Jira webhooks don't ship an HMAC
   header; the public convention is to embed a per-workspace secret in the
   subscription URL (``…/webhooks/jira?secret=<token>``). We resolve the
   tenant by iterating every ``Integration`` of the requested ``kind`` and
   running a constant-time compare against ``Integration.config['webhook_secret']``
   (falling back to ``secrets_encrypted`` so legacy GitLab-style token-in-secret
   payloads stay supported). The loop runs to completion regardless of whether a
   match was found so the reply timing carries no information about which
   integration matched.

2. **Webhook dedup via Redis SETNX** — keyed by ``(workspace_id, issue_key,
   changelog_id)`` for Jira (60 s TTL). The helper returns ``True`` on first
   call, ``False`` on dedup hit; the receiver short-circuits to a 200
   ``ignored`` reply on dedup hit so Jira's at-least-once delivery never
   double-updates the local defect.

No HTTP / FastAPI imports here so the receiver service is unit-testable
without a request scope and can be re-used by future webhook handlers.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Sequence


# Dedup TTL — plan-05b §M1d-18 pins 60 seconds for Jira changelog replay.
DEFAULT_DEDUP_TTL_SECONDS = 60


# ---------------------------------------------------------------------------
# Redis dedup
# ---------------------------------------------------------------------------


class _RedisLike(Protocol):
    """Subset of ``redis.asyncio.Redis`` that :func:`setnx_jira_dedup` exercises.

    Declared as a Protocol so tests can pass a ``fakeredis.aioredis.FakeRedis``
    (or an inline stub) without inheriting the SDK. The signature mirrors
    ``redis-py``'s ``set(name, value, *, nx, ex)``.
    """

    async def set(
        self,
        name: str,
        value: object,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> object: ...


async def setnx_jira_dedup(
    redis: _RedisLike,
    *,
    workspace_id: str,
    issue_key: str,
    changelog_id: str,
    ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
) -> bool:
    """Return ``True`` on first call within the TTL, ``False`` on dedup hit.

    Key shape ``dedup:jira:webhook:{workspace_id}:{issue_key}:{changelog_id}``
    is the one plan-05b §M1d-18 spells out. ``changelog_id`` may be the empty
    string when Jira omits the changelog block (some webhook configurations
    only forward the ``issue`` payload) — we keep dedup keyed on it anyway
    because two distinct payloads with an empty id within 60 s still represent
    the same logical event from Jira's perspective.
    """
    key = f"dedup:jira:webhook:{workspace_id}:{issue_key}:{changelog_id}"
    result = await redis.set(name=key, value="1", nx=True, ex=ttl_seconds)
    return bool(result)


# ---------------------------------------------------------------------------
# Workspace resolution by URL-embedded secret
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebhookTenant:
    """The workspace + integration pair authenticated for a single webhook.

    ``integration`` is exposed so the caller can stash the integration id on
    the audit row's ``metadata`` for replay-debug purposes and use it to build
    the per-Integration adapter via the factory on
    ``app.state.adapter_factories``.
    """

    workspace_id: str
    integration: Integration


async def resolve_workspace_by_secret(
    session: AsyncSession, *, kind: IntegrationKind, secret: str
) -> WebhookTenant | None:
    """Return the workspace + integration whose webhook secret matches ``secret``.

    Resolution order per integration row:

    1. ``Integration.config['webhook_secret']`` if present (the documented
       v1 location for Jira's URL-embedded secret — Jira webhooks don't have
       HMAC headers).
    2. ``Integration.secrets_encrypted`` as a backwards-compatibility seam for
       integrations that re-use the auth credential as the webhook secret.

    Runs :func:`hmac.compare_digest` against every candidate so the response
    timing carries no information about which (if any) integration matched.
    First match wins, but the loop continues so a wrong-secret call costs the
    same wall-time as a right-secret one.

    Returns ``None`` when no integration matches; callers turn that into
    ``401 Unauthorized``.
    """
    stmt = select(Integration).where(Integration.kind == kind)
    rows: Sequence[Integration] = (await session.scalars(stmt)).all()
    matched: WebhookTenant | None = None
    secret_bytes = secret.encode("utf-8")
    for row in rows:
        candidate = _resolve_webhook_secret(row)
        if candidate is None:
            # Keep the loop length stable: pay the same compare cost on every
            # iteration so the wrong-secret reply timing reveals nothing about
            # which rows had a secret configured.
            hmac.compare_digest(secret_bytes, secret_bytes)
            continue
        candidate_bytes = candidate.encode("utf-8")
        if (
            len(candidate_bytes) == len(secret_bytes)
            and hmac.compare_digest(candidate_bytes, secret_bytes)
            and matched is None
        ):
            matched = WebhookTenant(workspace_id=row.workspace_id, integration=row)
    return matched


def _resolve_webhook_secret(row: Integration) -> str | None:
    """Pull the per-Integration webhook secret out of config / secrets, or ``None``.

    Config wins when present so a future FE flow that rotates the webhook
    secret independently of the API credential doesn't bleed into the auth
    surface.
    """
    cfg = row.config or {}
    if isinstance(cfg, dict):
        candidate = cfg.get("webhook_secret")
        if isinstance(candidate, str) and candidate:
            return candidate
    secret = row.secrets_encrypted
    if isinstance(secret, str) and secret:
        return secret
    return None
