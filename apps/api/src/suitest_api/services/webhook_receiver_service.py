"""Shared utilities for inbound CI/git-provider webhook receivers.

Implements three primitives reused by M1d-16 (GitHub) and M1d-17 (GitLab):

1. **Workspace resolution by integration secret** — the workspace whose
   :class:`Integration` row carries the matching encrypted secret is the tenant
   on whose behalf the run is enqueued. Constant-time comparison is used
   against every candidate so a wrong-secret reply cannot be timed.

2. **Run dedup via Redis SETNX** — keyed by ``project_id`` + ``commit_sha`` +
   ``trigger``, TTL configurable (60 s default per plan-05b §M1d-16). The
   helper returns ``True`` on first call, ``False`` on dedup hit; the receiver
   short-circuits to a 200 ``ignored`` response on dedup hit.

3. **Gating-suite selection resolution** — returns either the project's pinned
   ``gating_suite_id`` (preferred) or, falling back, every active case tagged
   ``smoke``. ``None`` when neither is configured (Q4 default → 200 ignored).

No HTTP / FastAPI imports here so the receiver service is unit-testable without
a request scope and can be re-used by future webhook handlers (Jenkins, Jira).
"""

from __future__ import annotations

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


# Smoke fallback tag — cases carrying this tag are auto-selected when the
# project has no ``gating_suite_id`` pinned. Kept as a constant so a future
# product call to rename the convention happens in one place.
SMOKE_TAG = "smoke"


# Dedup TTL — plan-05b pins 60 seconds. Exposed as a constant so the GitHub
# receiver (M1d-16) can override per push vs. PR if a future spec change asks.
DEFAULT_DEDUP_TTL_SECONDS = 60


# ---------------------------------------------------------------------------
# Redis dedup
# ---------------------------------------------------------------------------


class _RedisLike(Protocol):
    """Subset of ``redis.asyncio.Redis`` that :func:`setnx_dedup` exercises.

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
    plan-05b §M1d-16 spells out; the GitHub receiver will share the same key
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
    """Return the workspace + integration whose secret matches ``token``.

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
            # Keep the loop length stable: hash the token against itself so
            # the timing cost of the compare is paid on every iteration.
            hmac.compare_digest(token_bytes, token_bytes)
            continue
        secret_bytes = secret_plain.encode("utf-8")
        # First match wins, but we deliberately keep looping below so the
        # constant-time guarantee covers the wrong-secret case too.
        if hmac.compare_digest(secret_bytes, token_bytes) and matched is None:
            matched = WebhookTenant(workspace_id=row.workspace_id, integration=row)
    return matched


async def resolve_project_from_payload(
    session: AsyncSession,
    *,
    tenant: WebhookTenant,
    external_project_id: int | None,
    external_path: str | None,
) -> Project | None:
    """Look up the local :class:`Project` referenced by an inbound payload.

    Resolution order (DATA_MODEL.md currently lacks a dedicated
    ``projects.gitlab_project_id`` column — see TODO below):

    1. ``integration.config["local_project_id"]`` if the integration row pins
       a single project (most v1 GitLab installs map one webhook to one
       Suitest project). Validates that the resolved project lives under the
       same workspace as the integration.
    2. Otherwise return ``None`` — caller emits ``404 project not found``.

    TODO(M2): introduce ``projects.gitlab_project_id`` / ``projects.repo_url``
    so we can resolve by ``external_project_id`` / ``external_path`` without
    relying on a per-integration mapping. The signature already accepts those
    values so the lookup can be widened without churning callers.
    """
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
    """Return the ``selection`` payload for the gating run, or ``None``.

    Order:

    1. ``project.gating_suite_id`` pinned and the suite is non-deleted →
       every active case in that suite.
    2. Otherwise every active case in the project tagged ``smoke``.
    3. Neither → ``None`` (the caller emits the 200 ``no_gating_suite`` reply).

    Selection items use the ``{"case_id": ...}`` shape :class:`RunService`
    consumes; ``selectedStepIds`` is omitted so the runner picks every active
    step on each case (the default per plan-05b §M1d-16).
    """
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
