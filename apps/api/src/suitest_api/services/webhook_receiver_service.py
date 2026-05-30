"""Shared utilities for inbound CI / git-provider / issue-tracker webhook receivers.

Implements primitives reused by M1d-16 (GitHub), M1d-17 (GitLab) and M1d-18 (Jira):

1. **Workspace resolution by integration secret** — the workspace whose
   :class:`Integration` row carries the matching encrypted secret is the tenant
   on whose behalf the run is enqueued. Constant-time comparison is used
   against every candidate so a wrong-secret reply cannot be timed. Two
   variants ship:
   - :func:`resolve_workspace_by_token` for header-token providers (GitLab).
   - :func:`resolve_workspace_by_secret` for URL-secret providers (Jira),
     which also checks ``Integration.config['webhook_secret']``.

2. **GitHub HMAC verify** — :func:`verify_github_hmac` resolves the integration
   row whose secret HMAC-SHA256s the raw body to the supplied
   ``X-Hub-Signature-256`` header. Constant-time across every candidate.

3. **Run dedup via Redis SETNX** — keyed by ``project_id`` + ``commit_sha`` +
   ``trigger`` (CI/git providers) or ``workspace_id`` + ``issue_key`` +
   ``changelog_id`` (Jira). TTL 60 s default per plan-05b. The helpers return
   ``True`` on first call, ``False`` on dedup hit; the receiver short-circuits
   to a 200 ``ignored`` response on dedup hit.

4. **Gating-suite selection resolution** — returns either the project's pinned
   ``gating_suite_id`` (preferred) or, falling back, every active case tagged
   ``smoke``. ``None`` when neither is configured (Q4 default → 200 ignored).

No HTTP / FastAPI imports here so the receiver service is unit-testable without
a request scope and can be re-used by future webhook handlers (Jenkins, …).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.case import CaseTag, TestCase
from suitest_db.models.integration import Integration
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Sequence


# GitHub signature header prefix. Constant exported so the router can branch
# on a mis-prefixed header (e.g. someone sent the legacy ``sha1=`` variant)
# without re-hardcoding the literal.
GITHUB_SIGNATURE_PREFIX = "sha256="


# Smoke fallback tag — cases carrying this tag are auto-selected when the
# project has no ``gating_suite_id`` pinned.
SMOKE_TAG = "smoke"


# Dedup TTL — plan-05b pins 60 seconds. Exposed as a constant so the GitHub
# receiver (M1d-16) can override per push vs. PR if a future spec change asks.
DEFAULT_DEDUP_TTL_SECONDS = 60


# ---------------------------------------------------------------------------
# Redis dedup
# ---------------------------------------------------------------------------


class _RedisLike(Protocol):
    """Subset of ``redis.asyncio.Redis`` the dedup helpers exercise.

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


async def setnx_dedup(
    redis: _RedisLike,
    *,
    project_id: str,
    commit_sha: str,
    trigger: str,
    ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
) -> bool:
    """Return ``True`` on first call within the TTL, ``False`` on dedup hit.

    Key shape ``dedup:run:{project_id}:{commit_sha}:{trigger}`` is the one
    plan-05b §M1d-16 spells out; the GitHub receiver shares the same key
    space so a GitHub push + a GitLab push for the same commit + project + a
    *different* trigger value (``WEBHOOK_GITHUB`` vs. ``WEBHOOK_GITLAB``) do
    not collide — both runs are enqueued.

    ``commit_sha`` may be the empty string on payloads that omit it (a tag push
    without commits, an MR ``update`` with no last_commit). We keep dedup
    keyed on it anyway because two distinct payloads with an empty sha within
    60 s would still represent the same "no-op" event from CI's perspective
    and we don't want to enqueue twice.
    """
    key = f"dedup:run:{project_id}:{commit_sha}:{trigger}"
    result = await redis.set(name=key, value="1", nx=True, ex=ttl_seconds)
    return bool(result)


async def setnx_jira_dedup(
    redis: _RedisLike,
    *,
    workspace_id: str,
    issue_key: str,
    changelog_id: str,
    ttl_seconds: int = DEFAULT_DEDUP_TTL_SECONDS,
) -> bool:
    """Return ``True`` on first call within the TTL, ``False`` on dedup hit (Jira).

    Key shape ``dedup:jira:webhook:{workspace_id}:{issue_key}:{changelog_id}``
    is the one plan-05b §M1d-18 spells out. ``changelog_id`` may be the empty
    string when Jira omits the changelog block.
    """
    key = f"dedup:jira:webhook:{workspace_id}:{issue_key}:{changelog_id}"
    result = await redis.set(name=key, value="1", nx=True, ex=ttl_seconds)
    return bool(result)


# ---------------------------------------------------------------------------
# Workspace + project resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebhookTenant:
    """The workspace + integration pair authenticated for a single webhook.

    ``integration`` is exposed so the caller can stash the integration id on
    the audit row's ``metadata`` for replay-debug purposes.
    """

    workspace_id: str
    integration: Integration


async def resolve_workspace_by_token(
    session: AsyncSession, *, kind: IntegrationKind, token: str
) -> WebhookTenant | None:
    """Return the workspace + integration whose secret matches ``token`` (GitLab-style header).

    Iterates every ``Integration`` row of the given ``kind`` and runs a
    constant-time comparison against the decrypted secret. The
    :class:`~suitest_core.crypto.EncryptedBytes` column transparently decrypts
    on attribute read, so a single ``select`` is enough — we don't expose any
    raw cipher manipulation here.

    Returns ``None`` when no integration matches; callers turn that into
    ``401 Unauthorized``. The constant-time loop runs to completion regardless
    of whether a match was found earlier, so the response timing carries no
    information about which (if any) integration matched.
    """
    stmt = select(Integration).where(Integration.kind == kind)
    rows: Sequence[Integration] = (await session.scalars(stmt)).all()
    matched: WebhookTenant | None = None
    token_bytes = token.encode("utf-8")
    for row in rows:
        secret_plain = row.secrets_encrypted
        if secret_plain is None:
            hmac.compare_digest(token_bytes, token_bytes)
            continue
        secret_bytes = secret_plain.encode("utf-8")
        if hmac.compare_digest(secret_bytes, token_bytes) and matched is None:
            matched = WebhookTenant(workspace_id=row.workspace_id, integration=row)
    return matched


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


async def verify_github_hmac(
    session: AsyncSession, *, body: bytes, signature_header: str
) -> WebhookTenant | None:
    """Return the GitHub tenant whose secret HMAC-signs ``body`` to ``signature_header``."""
    if not signature_header.startswith(GITHUB_SIGNATURE_PREFIX):
        hmac.new(b"\x00", body, hashlib.sha256).hexdigest()
        return None
    supplied_hex = signature_header[len(GITHUB_SIGNATURE_PREFIX) :]
    supplied_bytes = supplied_hex.encode("ascii")
    stmt = select(Integration).where(Integration.kind == IntegrationKind.GITHUB)
    rows: Sequence[Integration] = (await session.scalars(stmt)).all()
    matched: WebhookTenant | None = None
    for row in rows:
        secret_plain = row.secrets_encrypted
        if secret_plain is None:
            hmac.new(b"\x00", body, hashlib.sha256).hexdigest()
            hmac.compare_digest(supplied_bytes, supplied_bytes)
            continue
        secret_bytes = secret_plain.encode("utf-8")
        expected_hex = hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
        expected_bytes = expected_hex.encode("ascii")
        if hmac.compare_digest(expected_bytes, supplied_bytes) and matched is None:
            matched = WebhookTenant(workspace_id=row.workspace_id, integration=row)
    return matched


async def resolve_github_project(
    session: AsyncSession,
    *,
    tenant: WebhookTenant,
    repo_full_name: str | None,
) -> Project | None:
    """Resolve the local :class:`Project` for an inbound GitHub event."""
    cfg = tenant.integration.config or {}
    if not isinstance(cfg, dict):
        return None
    local_id = cfg.get("local_project_id")
    if not isinstance(local_id, str):
        return None
    expected_repo = cfg.get("github_repo")
    if (
        isinstance(expected_repo, str)
        and expected_repo
        and (repo_full_name is None or expected_repo != repo_full_name)
    ):
        return None
    project = await session.get(Project, local_id)
    if project is None or project.workspace_id != tenant.workspace_id:
        return None
    return project


async def resolve_project_from_payload(
    session: AsyncSession,
    *,
    tenant: WebhookTenant,
    external_project_id: int | None,
    external_path: str | None,
) -> Project | None:
    """Look up the local :class:`Project` referenced by an inbound payload (GitLab)."""
    del external_project_id, external_path  # consumed by the future M2 lookup
    cfg = tenant.integration.config or {}
    local_id = cfg.get("local_project_id") if isinstance(cfg, dict) else None
    if not isinstance(local_id, str):
        return None
    project = await session.get(Project, local_id)
    if project is None or project.workspace_id != tenant.workspace_id:
        return None
    return project


# ---------------------------------------------------------------------------
# Gating-suite selection
# ---------------------------------------------------------------------------


async def resolve_gating_selection(
    session: AsyncSession, *, project: Project
) -> list[dict[str, str]] | None:
    """Return the ``selection`` payload for the gating run, or ``None``."""
    case_ids: list[str] = []
    if project.gating_suite_id is not None:
        suite = await session.get(Suite, project.gating_suite_id)
        if suite is not None and suite.deleted_at is None:
            stmt_suite = (
                select(TestCase.id)
                .where(
                    TestCase.suite_id == project.gating_suite_id,
                    TestCase.deleted_at.is_(None),
                )
                .order_by(TestCase.order_in_suite.asc(), TestCase.created_at.asc())
            )
            case_ids = list((await session.scalars(stmt_suite)).all())
    if not case_ids:
        stmt_smoke = (
            select(TestCase.id)
            .join(Suite, Suite.id == TestCase.suite_id)
            .where(
                Suite.project_id == project.id,
                Suite.deleted_at.is_(None),
                TestCase.deleted_at.is_(None),
                TestCase.id.in_(select(CaseTag.case_id).where(CaseTag.tag == SMOKE_TAG)),
            )
            .order_by(TestCase.created_at.asc())
        )
        case_ids = list((await session.scalars(stmt_smoke)).all())
    if not case_ids:
        return None
    return [{"case_id": cid} for cid in case_ids]
