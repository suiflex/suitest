"""TestCaseService — read + M1d-2 write API for the test case domain.

Read path (M1a): ``list``/``get_by_id_with_steps`` walk suite -> project ->
workspace and return ``None`` (router maps to 404) for cross-workspace ids so a
caller cannot enumerate the existence of test cases they do not own.

Write path (M1d-2): ``create``, ``update``, ``replace_steps``, ``append_step``,
``duplicate``. Each opens a single transaction owned by the caller (router
commits), runs the per-step validator (``test_case_validator.validate_steps``),
applies the mutation through the repo, and stamps an explicit ``write_audit``
row plus a typed WS event helper consumed by the router for ``Request``-bound
publish.

The router stays thin — it only deals with HTTP plumbing: validating the
``If-Unmodified-Since`` precondition, mapping :class:`StepValidationError`
subtypes to the canonical ``docs/API.md §3`` error envelope, and broadcasting
the WS event after the commit so subscribers can not see a phantom event for a
rolled-back write.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple, cast

from sqlalchemy import select
from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.run import Run as RunRow
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.mcp_providers import McpProviderRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_db.repositories.workspaces import WorkspaceRepo
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, RunTrigger, Tier
from suitest_shared.schemas.responses import TestCaseDetailOut, TestCaseOut, TestStepOut
from suitest_shared.text import derive_slug, derive_title

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.services.run_service import RunService
from suitest_api.services.test_case_validator import _StepLike, validate_steps

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.schemas.test_case import (
        StepAppend,
        StepCreate,
        TestCaseCreate,
        TestCaseUpdate,
    )


class ConcurrentModificationError(Exception):
    """Raised when ``If-Unmodified-Since`` is older than ``test_cases.updated_at``."""

    def __init__(self, *, case_id: str, public_id: str, server_updated_at: datetime) -> None:
        super().__init__("test case was modified by another client")
        self.case_id = case_id
        self.public_id = public_id
        self.server_updated_at = server_updated_at


class CaseWriteResult(NamedTuple):
    """Outcome bundle: the detail payload + the WS event the router should emit.

    Keeping the WS event out-of-band (vs. having the service publish directly)
    lets the router wait for the transaction to commit before broadcasting —
    subscribers never observe a phantom event for a rolled-back write.
    """

    detail: TestCaseDetailOut
    ws_event: str
    ws_payload: dict[str, object]


class CaseLifecycleResult(NamedTuple):
    """Soft-delete / restore outcome — no detail body, only the WS event.

    DELETE returns 204 with no body; restore returns 204 per ``docs/API.md §3.3``.
    The router only needs the WS event + payload after commit; the lifecycle
    state itself is observable via subsequent ``GET`` requests.
    """

    ws_event: str
    ws_payload: dict[str, object]
    audit_action: str
    transitioned: bool


class BulkLimitExceededError(Exception):
    """``POST /test-cases/bulk-update`` received more than the cap (100) ids."""

    def __init__(self, *, received: int, limit: int) -> None:
        super().__init__(f"bulk-update accepts at most {limit} ids per request")
        self.received = received
        self.limit = limit


class CrossWorkspaceIdsError(Exception):
    """``POST /test-cases/bulk-update`` body mixes ids across workspaces."""

    def __init__(self, *, offending_ids: list[str]) -> None:
        super().__init__("bulk-update ids span multiple workspaces or do not exist")
        self.offending_ids = offending_ids


class InvalidBulkTargetSuiteError(Exception):
    """``move_to_suite`` target lives in another workspace (or does not exist)."""

    def __init__(self, *, suite_id: str) -> None:
        super().__init__("move_to_suite target suite is not in the caller's workspace")
        self.suite_id = suite_id


class BulkPerCaseAudit(NamedTuple):
    """Per-case audit + WS event payload to emit after commit."""

    audit_id: str
    case_id: str
    public_id: str
    ws_event: str
    ws_payload: dict[str, object]


class BulkUpdateResult(NamedTuple):
    """Bundle returned by :meth:`TestCaseService.bulk_update`.

    ``audits`` holds one entry per affected case; the router commits the
    transaction, returns ``{updated, audit_ids}`` and emits the WS events.
    """

    affected_count: int
    audits: list[BulkPerCaseAudit]


class TestCaseService:
    __test__ = False  # not a pytest test class

    def __init__(
        self,
        ctx: TenantContext,
        repo: TestCaseRepo,
        suite_repo: SuiteRepo,
        project_repo: ProjectRepo,
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._suite_repo = suite_repo
        self._project_repo = project_repo

    # ------------------------------------------------------------------
    # Scope guards
    # ------------------------------------------------------------------

    async def _suite_in_scope(self, suite_id: str) -> bool:
        suite = await self._suite_repo.get_by_id(suite_id)
        if suite is None:
            return False
        project = await self._project_repo.get_by_id(suite.project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def _load_case_in_scope(self, case_id: str) -> TestCase | None:
        case = await self._repo.get_by_id(case_id)
        if case is None or not await self._suite_in_scope(case.suite_id):
            return None
        if case.deleted_at is not None:
            return None
        return case

    async def _load_case_in_scope_including_deleted(self, case_id: str) -> TestCase | None:
        """Same as :meth:`_load_case_in_scope` but DOES NOT filter tombstoned rows.

        Used by the M1d-3 soft-delete / restore paths so the service can
        distinguish "row never existed in this workspace" (404) from "row
        exists but is currently deleted" (idempotent path).
        """
        case = await self._repo.get_by_id_including_deleted(case_id)
        if case is None or not await self._suite_in_scope(case.suite_id):
            return None
        return case

    @property
    def _session(self) -> AsyncSession:
        return self._repo.session

    # ------------------------------------------------------------------
    # Read path (M1a)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def list(
        self,
        suite_id: str,
        *,
        status: CaseStatus | None = None,
        source: CaseSource | None = None,
        priority: Priority | None = None,
        tag: str | None = None,
        q: str | None = None,
        limit: int = 20,
        include_deleted: bool = False,
    ) -> list[TestCaseOut] | None:
        if not await self._suite_in_scope(suite_id):
            return None
        rows, _ = await self._repo.list_by_suite_filtered(
            suite_id,
            status=status,
            source=source,
            priority=priority,
            tag=tag,
            q=q,
            limit=limit,
            include_deleted=include_deleted,
        )
        return [TestCaseOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id_with_steps(self, case_id: str) -> TestCaseDetailOut | None:
        row = await self._repo.get_by_id(case_id)
        if row is None or not await self._suite_in_scope(row.suite_id):
            return None
        steps = await self._repo.get_steps(case_id)
        detail = TestCaseDetailOut.model_validate(row)
        detail.steps = [TestStepOut.model_validate(s) for s in steps]
        return detail

    # ------------------------------------------------------------------
    # Helpers shared by the write methods
    # ------------------------------------------------------------------

    async def _resolve_tier_and_settings(self) -> tuple[Tier, bool]:
        """Return ``(tier, strict_zero_validation)`` for the active workspace.

        Tier resolves via :class:`WorkspaceCapability` (defaults to
        :attr:`Tier.ZERO` when no overlay exists — matches the read-side
        ``resolve_workspace_tier`` semantics). ``strict_zero_validation`` is a
        plain column on :class:`Workspace` (M1d-1 migration) — defaults to
        ``true`` so existing workspaces inherit the stricter behaviour.
        """
        from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo

        capability = await WorkspaceCapabilityRepo(self._session).get(self._ctx.workspace_id)
        tier = Tier(capability.tier) if capability is not None else Tier.ZERO
        workspace = await WorkspaceRepo(self._session).get_by_id(self._ctx.workspace_id)
        strict = bool(workspace.strict_zero_validation) if workspace is not None else True
        return tier, strict

    async def _registered_mcp_names(self) -> set[str]:
        """Return the set of MCP provider names registered for the workspace.

        Bundled providers (always allowed) are appended by the validator —
        keeps the workspace-scoped query focused on user-installed entries.
        """
        providers = await McpProviderRepo(self._session).list_by_workspace(self._ctx.workspace_id)
        return {p.name for p in providers}

    def _check_if_unmodified_since(
        self, case: TestCase, if_unmodified_since: datetime | None
    ) -> None:
        """Raise :class:`ConcurrentModificationError` if the header predates ``updated_at``.

        Header absent → last-write-wins (M1d-2 contract per docs/API.md §47).
        Comparison is at one-second resolution because HTTP-date headers carry
        no sub-second precision; the row stamp gets floored to whole seconds so
        a same-instant client doesn't trip the 409 on a refetch.
        """
        if if_unmodified_since is None:
            return
        server_updated = case.updated_at
        # HTTP-date precision is whole seconds. Drop microseconds so a freshly
        # refetched client (whose header == server stamp) sees an equal-or-newer
        # value, not a 1-microsecond-older one.
        if server_updated.microsecond:
            server_updated = server_updated.replace(microsecond=0)
        client_ts = if_unmodified_since
        if client_ts.microsecond:
            client_ts = client_ts.replace(microsecond=0)
        if client_ts < server_updated:
            raise ConcurrentModificationError(
                case_id=case.id,
                public_id=case.public_id,
                server_updated_at=case.updated_at,
            )

    async def _build_detail(self, case: TestCase) -> TestCaseDetailOut:
        """Refresh ``case`` + load its current steps and return the detail DTO.

        ``case`` carries a lazy ``steps`` relationship which would emit
        ``MissingGreenlet`` if ``TestCaseDetailOut.model_validate(case)`` were
        allowed to autoload it under asyncpg. Build the DTO from the explicit
        column dump instead and attach the eagerly-loaded steps.
        """
        await self._session.refresh(case)
        steps = await self._repo.get_steps(case.id)
        detail = TestCaseDetailOut(
            id=case.id,
            suite_id=case.suite_id,
            public_id=case.public_id,
            name=case.name,
            title=case.title,
            slug=case.slug,
            description=case.description,
            preconditions=case.preconditions,
            source=case.source,
            status=case.status,
            priority=case.priority,
            owner_id=case.owner_id,
            created_at=case.created_at,
            updated_at=case.updated_at,
            steps=[TestStepOut.model_validate(s) for s in steps],
        )
        return detail

    # ------------------------------------------------------------------
    # Write path (M1d-2)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create(self, body: TestCaseCreate) -> CaseWriteResult | None:
        """Create a test case + steps + tags atomically.

        Returns ``None`` when the target suite is cross-workspace — the router
        translates this to 404 (NEVER 403, to avoid an enumeration oracle).
        """
        if not await self._suite_in_scope(body.suite_id):
            return None

        tier, strict = await self._resolve_tier_and_settings()
        registered = await self._registered_mcp_names()
        validate_steps(
            body.steps,
            tier=tier,
            strict_zero_validation=strict,
            registered_mcp_names=registered,
        )

        case = TestCase(
            workspace_id=self._ctx.workspace_id,
            suite_id=body.suite_id,
            name=body.name,
            # Manual creates carry a human name — it IS the title. If someone
            # pastes a technical key, derive a readable title + keep the slug.
            title=derive_title(body.name),
            slug=derive_slug(body.name),
            description=body.description,
            preconditions=body.preconditions,
            priority=body.priority,
            status=body.status,
            source=body.source,
        )
        set_workspace_id(case, self._ctx.workspace_id)
        self._session.add(case)
        await self._session.flush()

        # Steps land in array order with 0-based ``order_in_suite`` placement —
        # the explicit ``order`` field on each row mirrors the API contract
        # (caller may pass ``order``; we honour it; otherwise array position
        # wins). Duplicate orders are not possible because we coerce to the
        # array position when the caller leaves it None.
        step_rows: list[TestStep] = []
        for index, step in enumerate(body.steps):
            step_order = step.order if step.order is not None else index
            step_rows.append(
                TestStep(
                    case_id=case.id,
                    order=step_order,
                    action=step.action,
                    expected=step.expected,
                    code=step.code,
                    data=step.data,
                    mcp_provider=step.mcp_provider,
                    target_kind=step.target_kind,
                )
            )
        if step_rows:
            await self._repo.add_steps(case.id, step_rows)

        if body.tags:
            await self._repo.replace_tags(case.id, body.tags)

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.created",
            resource_type="test_case",
            resource_id=case.id,
            metadata={
                "publicId": case.public_id,
                "suiteId": case.suite_id,
                "stepCount": len(step_rows),
            },
        )
        detail = await self._build_detail(case)
        return CaseWriteResult(
            detail=detail,
            ws_event="case.created",
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "suiteId": case.suite_id,
                "by": self._ctx.user_id,
            },
        )

    @require_tier(TierFlag.ANY)
    async def update(
        self,
        case_id: str,
        body: TestCaseUpdate,
        *,
        if_unmodified_since: datetime | None,
    ) -> CaseWriteResult | None:
        """Patch metadata + tag replacement; honours ``If-Unmodified-Since``.

        ``tags`` (if provided) replace the existing set in full. Other fields
        only mutate when present in the body — Pydantic's
        ``model_dump(exclude_unset=True)`` distinguishes "absent" from
        "explicit null".
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None
        self._check_if_unmodified_since(case, if_unmodified_since)

        changed_fields: list[str] = []
        payload = body.model_dump(exclude_unset=True)
        for field in ("name", "title", "description", "preconditions", "status", "priority"):
            if field in payload:
                setattr(case, field, payload[field])
                changed_fields.append(field)
        # Renaming via the legacy ``name`` field keeps the display title in sync
        # unless the caller set ``title`` explicitly.
        if "name" in payload and "title" not in payload:
            case.title = derive_title(payload["name"])
            changed_fields.append("title")
        if "tags" in payload:
            tag_list = payload["tags"] or []
            await self._repo.replace_tags(case.id, tag_list)
            changed_fields.append("tags")

        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.updated",
            resource_type="test_case",
            resource_id=case.id,
            metadata={"fields": changed_fields, "publicId": case.public_id},
        )
        detail = await self._build_detail(case)
        return CaseWriteResult(
            detail=detail,
            ws_event="case.updated",
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "fields": changed_fields,
            },
        )

    @require_tier(TierFlag.ANY)
    async def replace_steps(
        self,
        case_id: str,
        steps: Sequence[StepCreate],
        *,
        if_unmodified_since: datetime | None,
    ) -> CaseWriteResult | None:
        """Atomic step replace inside one transaction.

        Validation runs BEFORE the delete, so an invalid payload leaves the
        existing step list intact (no destructive write). After delete + insert
        the case row's ``updated_at`` bumps automatically via the
        :class:`TimestampMixin` ``onupdate`` hook because we mutate
        ``order_in_suite`` (a no-op self-write) — explicit so a downstream
        ``If-Unmodified-Since`` check sees the new stamp.
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None
        self._check_if_unmodified_since(case, if_unmodified_since)

        tier, strict = await self._resolve_tier_and_settings()
        registered = await self._registered_mcp_names()
        validate_steps(
            steps,
            tier=tier,
            strict_zero_validation=strict,
            registered_mcp_names=registered,
        )

        await self._repo.delete_steps(case.id)
        rebuilt: list[TestStep] = []
        for index, step in enumerate(steps):
            step_order = step.order if step.order is not None else index
            rebuilt.append(
                TestStep(
                    case_id=case.id,
                    order=step_order,
                    action=step.action,
                    expected=step.expected,
                    code=step.code,
                    data=step.data,
                    mcp_provider=step.mcp_provider,
                    target_kind=step.target_kind,
                )
            )
        if rebuilt:
            await self._repo.add_steps(case.id, rebuilt)

        # Force ``updated_at`` to advance even when no metadata column changed
        # (mutating just the steps doesn't bump the parent timestamp on its
        # own). Touching ``order_in_suite`` to itself is a no-op write that
        # the SQLAlchemy listener treats as a real update for the timestamp
        # mixin's ``onupdate`` callback.
        case.order_in_suite = case.order_in_suite
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.steps.replaced",
            resource_type="test_case",
            resource_id=case.id,
            metadata={"publicId": case.public_id, "stepCount": len(rebuilt)},
        )
        detail = await self._build_detail(case)
        return CaseWriteResult(
            detail=detail,
            ws_event="case.steps.replaced",
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "stepCount": len(rebuilt),
            },
        )

    @require_tier(TierFlag.ANY)
    async def append_step(self, case_id: str, step: StepAppend) -> CaseWriteResult | None:
        """Append one step using ``SELECT MAX(order) FOR UPDATE`` for race safety.

        Two concurrent appends against the same case serialise via row-level
        locks (see :meth:`TestCaseRepo.next_step_order_locked`) so neither
        overwrites the other's order. Validates first — an invalid step never
        contends for the lock.
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None

        tier, strict = await self._resolve_tier_and_settings()
        registered = await self._registered_mcp_names()
        validate_steps(
            [step],
            tier=tier,
            strict_zero_validation=strict,
            registered_mcp_names=registered,
        )

        next_order = await self._repo.next_step_order_locked(case.id)
        new_step = TestStep(
            case_id=case.id,
            order=next_order,
            action=step.action,
            expected=step.expected,
            code=step.code,
            data=step.data,
            mcp_provider=step.mcp_provider,
            target_kind=step.target_kind,
        )
        await self._repo.add_steps(case.id, [new_step])

        case.order_in_suite = case.order_in_suite
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.steps.appended",
            resource_type="test_step",
            resource_id=new_step.id,
            metadata={"publicId": case.public_id, "order": next_order},
        )
        detail = await self._build_detail(case)
        return CaseWriteResult(
            detail=detail,
            ws_event="case.steps.replaced",  # FE re-renders the whole step list
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "stepCount": len(detail.steps),
            },
        )

    @require_tier(TierFlag.ANY)
    async def reorder_steps(
        self,
        case_id: str,
        step_ids_in_order: Sequence[str],
        *,
        if_unmodified_since: datetime | None,
    ) -> tuple[CaseWriteResult, None] | None:
        """Re-rank existing steps atomically (docs/API.md §3.3 reorder).

        Validates that the submitted id set is exactly the case's current step
        ids — a mismatch surfaces as a 400 with ``details.missing`` /
        ``details.duplicate`` / ``details.unknown`` keys, exposed via the typed
        :class:`StepReorderMismatchError`.
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None
        self._check_if_unmodified_since(case, if_unmodified_since)

        existing_ids = set(await self._repo.step_ids(case.id))
        submitted = list(step_ids_in_order)
        submitted_set = set(submitted)
        duplicates = sorted(id_ for id_ in submitted_set if submitted.count(id_) > 1)
        missing = sorted(existing_ids - submitted_set)
        unknown = sorted(submitted_set - existing_ids)
        if duplicates or missing or unknown:
            raise StepReorderMismatchError(duplicates=duplicates, missing=missing, unknown=unknown)

        steps = list(
            (await self._session.scalars(select(TestStep).where(TestStep.case_id == case.id))).all()
        )
        by_id: dict[str, TestStep] = {s.id: s for s in steps}
        # Two-pass write to dodge the ``uq_test_steps_case_order`` unique
        # constraint: bumping each row to a temporary negative slot first
        # frees every target slot before the final positive assignment lands.
        # Postgres deferrable would be cleaner but the constraint is
        # immediate; this approach stays inside one transaction without
        # touching DDL.
        for offset, step_id in enumerate(submitted):
            by_id[step_id].order = -1 - offset
        await self._session.flush()
        for new_order, step_id in enumerate(submitted):
            by_id[step_id].order = new_order

        case.order_in_suite = case.order_in_suite
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.steps.reordered",
            resource_type="test_case",
            resource_id=case.id,
            metadata={"publicId": case.public_id, "stepCount": len(submitted)},
        )
        detail = await self._build_detail(case)
        return (
            CaseWriteResult(
                detail=detail,
                ws_event="case.steps.replaced",
                ws_payload={
                    "caseId": case.id,
                    "publicId": case.public_id,
                    "stepCount": len(submitted),
                },
            ),
            None,
        )

    @require_tier(TierFlag.ANY)
    async def trigger_adhoc_run(self, case_id: str) -> RunRow | None:
        """Validate + enqueue a one-case run via M1c :class:`RunService.create_run`.

        Pre-flight re-runs the per-step validator against the workspace's
        CURRENT tier + strict-zero flag — a case authored under a permissive
        tier that later flips to ZERO+strict must not silently run. Failure
        bubbles the typed validator exception untouched (router maps to the
        canonical envelope) and NO ``runs`` row is created.

        Cross-workspace / soft-deleted case ids return ``None`` so the router
        translates to 404 without an enumeration oracle.
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None

        suite = await self._suite_repo.get_by_id(case.suite_id)
        if suite is None:
            return None  # pragma: no cover — scope check already loaded suite

        steps = await self._repo.get_steps(case.id)
        tier, strict = await self._resolve_tier_and_settings()
        registered = await self._registered_mcp_names()
        # ``TestStep`` carries the ``code`` + ``mcp_provider`` attrs the
        # validator's ``_StepLike`` protocol describes — explicit cast keeps
        # mypy happy under its invariant ``Sequence`` view of ORM rows.
        validate_steps(
            cast("Sequence[_StepLike]", steps),
            tier=tier,
            strict_zero_validation=strict,
            registered_mcp_names=registered,
        )

        run_service = RunService(self._ctx, RunRepo(self._session), self._project_repo)
        run = await run_service.create_run(
            project_id=suite.project_id,
            name=f"Ad-hoc: {case.title}",
            selection=[{"case_id": case.id}],
            branch=None,
            commit_sha=None,
            env="staging",
            trigger=RunTrigger.MANUAL,
            user_id=self._ctx.user_id,
            mcp_routing_override=None,
        )
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.run_now",
            resource_type="test_case",
            resource_id=case.id,
            metadata={
                "publicId": case.public_id,
                "runId": run.id,
                "runPublicId": run.public_id,
            },
        )
        return run

    @require_tier(TierFlag.ANY)
    async def duplicate(self, case_id: str) -> CaseWriteResult | None:
        """Clone the case + all its steps + tags into the SAME suite.

        New public id (assigned by the ``before_insert`` listener). Name gets
        the ``" (Copy)"`` suffix per UI_SPEC. Runs / defects are NOT cloned —
        clone only the static spec.
        """
        case = await self._load_case_in_scope(case_id)
        if case is None:
            return None

        clone = TestCase(
            workspace_id=self._ctx.workspace_id,
            suite_id=case.suite_id,
            name=f"{case.name} (Copy)",
            title=f"{case.title} (Copy)",
            slug=None,  # a manual clone is no longer bound to the generated key
            description=case.description,
            preconditions=case.preconditions,
            priority=case.priority,
            status=case.status,
            source=case.source,
        )
        set_workspace_id(clone, self._ctx.workspace_id)
        self._session.add(clone)
        await self._session.flush()

        original_steps = await self._repo.get_steps(case.id)
        cloned_steps = [
            TestStep(
                case_id=clone.id,
                order=s.order,
                action=s.action,
                expected=s.expected,
                code=s.code,
                data=s.data,
                mcp_provider=s.mcp_provider,
                target_kind=s.target_kind,
            )
            for s in original_steps
        ]
        if cloned_steps:
            await self._repo.add_steps(clone.id, cloned_steps)

        original_tags = await self._repo.get_tags(case.id)
        if original_tags:
            await self._repo.replace_tags(clone.id, original_tags)

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.duplicated",
            resource_type="test_case",
            resource_id=clone.id,
            metadata={
                "sourceCaseId": case.id,
                "sourcePublicId": case.public_id,
                "publicId": clone.public_id,
            },
        )
        detail = await self._build_detail(clone)
        return CaseWriteResult(
            detail=detail,
            ws_event="case.created",
            ws_payload={
                "caseId": clone.id,
                "publicId": clone.public_id,
                "suiteId": clone.suite_id,
                "by": self._ctx.user_id,
            },
        )

    # ------------------------------------------------------------------
    # M1d-7 bulk update
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def bulk_update(
        self,
        body: object,
    ) -> BulkUpdateResult:
        """Execute a bulk action across ``≤100`` test cases in one transaction.

        Validation order (each step short-circuits with a typed exception):
          1. ``BulkLimitExceededError`` when ``len(ids) > 100``.
          2. ``CrossWorkspaceIdsError`` when any id is missing or lives in
             another workspace — body lists every offending id so the FE can
             highlight them.
          3. ``InvalidBulkTargetSuiteError`` when ``move_to_suite`` targets a
             suite outside the caller's workspace.

        On success the service applies the action, instantiates one
        :class:`AuditLog` row per affected case (so the response can return
        ``audit_ids``), and returns a :class:`BulkUpdateResult` whose
        ``audits`` list drives the post-commit WS broadcast.
        """
        from suitest_db.ids import new_id
        from suitest_db.models.audit import AuditLog

        from suitest_api.schemas.test_case import (
            BULK_LIMIT,
            BulkAction,
            BulkAddTagsRequest,
            BulkDeleteRequest,
            BulkMoveToSuiteRequest,
            BulkRemoveTagsRequest,
            BulkSetPriorityRequest,
        )

        # Pydantic discriminator already narrowed the body to one variant —
        # widen the static type back to the union for the dispatch below.
        ids_attr = getattr(body, "ids", None)
        action_attr = getattr(body, "action", None)
        if not isinstance(ids_attr, list) or action_attr is None:
            raise TypeError("bulk_update received an unexpected body shape")
        ids: list[str] = list(ids_attr)
        action: BulkAction = action_attr

        if len(ids) > BULK_LIMIT:
            raise BulkLimitExceededError(received=len(ids), limit=BULK_LIMIT)

        # Cross-workspace check fail-fast: any id missing OR in another
        # workspace lands in ``offending_ids``. We treat "missing" + "wrong ws"
        # identically so the response never leaks the existence of foreign
        # cases the caller would not otherwise be allowed to see.
        ws_for = await self._repo.workspace_ids_for(ids)
        offending = [cid for cid in ids if ws_for.get(cid) != self._ctx.workspace_id]
        if offending:
            raise CrossWorkspaceIdsError(offending_ids=offending)

        # Load the live cases so we can stamp ``publicId`` into audit + WS
        # payloads. Tombstoned rows are excluded — bulk actions only apply to
        # active cases (re-applying a soft-delete to an already-tombstoned row
        # would be a no-op anyway).
        cases = await self._repo.list_active_by_ids(ids)
        by_id: dict[str, TestCase] = {c.id: c for c in cases}

        # ------------------------------------------------------------------
        # Per-action execution
        # ------------------------------------------------------------------
        affected_ids: list[str] = []
        audit_action: str
        ws_event: str
        extra_payload: dict[str, object] = {}

        if action is BulkAction.DELETE:
            assert isinstance(body, BulkDeleteRequest)
            deleted_at = datetime.now(UTC)
            affected_ids = list(
                await self._repo.bulk_soft_delete([c.id for c in cases], deleted_at=deleted_at)
            )
            audit_action = "test_case.bulk_deleted"
            ws_event = "case.deleted"
            extra_payload = {"deletedAt": deleted_at.isoformat()}
        elif action is BulkAction.MOVE_TO_SUITE:
            assert isinstance(body, BulkMoveToSuiteRequest)
            target_ws = await self._repo.suite_workspace_id(body.payload.target_suite_id)
            if target_ws != self._ctx.workspace_id:
                raise InvalidBulkTargetSuiteError(suite_id=body.payload.target_suite_id)
            affected_ids = list(
                await self._repo.bulk_move_to_suite(
                    [c.id for c in cases], target_suite_id=body.payload.target_suite_id
                )
            )
            audit_action = "test_case.bulk_moved"
            ws_event = "case.updated"
            extra_payload = {"targetSuiteId": body.payload.target_suite_id}
        elif action is BulkAction.SET_PRIORITY:
            assert isinstance(body, BulkSetPriorityRequest)
            affected_ids = list(
                await self._repo.bulk_set_priority(
                    [c.id for c in cases], priority=body.payload.priority
                )
            )
            audit_action = "test_case.bulk_priority_changed"
            ws_event = "case.updated"
            extra_payload = {"priority": body.payload.priority.value}
        elif action is BulkAction.ADD_TAGS:
            assert isinstance(body, BulkAddTagsRequest)
            affected_ids = list(
                await self._repo.bulk_add_tags([c.id for c in cases], tags=body.payload.tags)
            )
            audit_action = "test_case.bulk_tags_added"
            ws_event = "case.updated"
            extra_payload = {"tags": list(body.payload.tags)}
        elif action is BulkAction.REMOVE_TAGS:
            assert isinstance(body, BulkRemoveTagsRequest)
            affected_ids = list(
                await self._repo.bulk_remove_tags([c.id for c in cases], tags=body.payload.tags)
            )
            audit_action = "test_case.bulk_tags_removed"
            ws_event = "case.updated"
            extra_payload = {"tags": list(body.payload.tags)}
        else:
            raise TypeError(f"unsupported bulk action: {action!r}")

        # ------------------------------------------------------------------
        # Audit + WS payload assembly (one row per affected case)
        # ------------------------------------------------------------------
        audits: list[BulkPerCaseAudit] = []
        for case_id in affected_ids:
            case = by_id.get(case_id)
            if case is None:
                # Defensive — the repo only ever returns ids drawn from ``ids``.
                continue
            ws_payload: dict[str, object] = {
                "caseId": case.id,
                "publicId": case.public_id,
                "suiteId": case.suite_id,
                **extra_payload,
            }
            audit_row = AuditLog(
                id=new_id(),
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action=audit_action,
                resource_type="test_case",
                resource_id=case.id,
                metadata_json={"publicId": case.public_id, **extra_payload},
            )
            self._session.add(audit_row)
            audits.append(
                BulkPerCaseAudit(
                    audit_id=audit_row.id,
                    case_id=case.id,
                    public_id=case.public_id,
                    ws_event=ws_event,
                    ws_payload=ws_payload,
                )
            )
        # Flush so the audit rows + any deferred constraint checks settle
        # within the same transaction the router commits. The flush is
        # intentional so an audit-side IntegrityError (extremely unlikely —
        # ids are CUIDs) surfaces here, not at commit time.
        await self._session.flush()
        return BulkUpdateResult(affected_count=len(affected_ids), audits=audits)

    # ------------------------------------------------------------------
    # M1d-3 soft delete + restore
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def soft_delete(self, case_id: str) -> CaseLifecycleResult | None:
        """Tombstone an active test case.

        Returns ``None`` (router maps to 404) when the row is cross-workspace,
        does not exist, OR is already deleted. The "already deleted" branch
        also maps to 404 per ``docs/API.md §3.3`` (re-DELETE is not an
        idempotent 204 — the row is no longer visible to non-``includeDeleted``
        queries, so DELETE against it is indistinguishable from "no such row").
        """
        case = await self._load_case_in_scope_including_deleted(case_id)
        if case is None:
            return None
        deleted_at = datetime.now(UTC)
        transitioned = await self._repo.mark_deleted(case.id, deleted_at=deleted_at)
        if not transitioned:
            # Already tombstoned — DELETE against a soft-deleted row is 404
            # because LIST + GET hide tombstones by default.
            return None
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.soft_deleted",
            resource_type="test_case",
            resource_id=case.id,
            metadata={
                "publicId": case.public_id,
                "deletedAt": deleted_at.isoformat(),
            },
        )
        return CaseLifecycleResult(
            ws_event="case.deleted",
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "suiteId": case.suite_id,
            },
            audit_action="test_case.soft_deleted",
            transitioned=True,
        )

    @require_tier(TierFlag.ANY)
    async def restore(self, case_id: str) -> CaseLifecycleResult | None:
        """Revive a tombstoned test case.

        Returns ``None`` (router maps to 404) when the row is cross-workspace
        or never existed. Restoring an already-active row is idempotent — it
        returns a result with ``transitioned=False`` and no audit row, so the
        router still answers ``204 No Content``.
        """
        case = await self._load_case_in_scope_including_deleted(case_id)
        if case is None:
            return None
        restored_at = datetime.now(UTC)
        outcome = await self._repo.clear_deleted(case.id)
        if outcome is None:
            return None
        if not outcome:
            # Row exists + already active — idempotent restore, no audit row,
            # no WS event (nothing changed).
            return CaseLifecycleResult(
                ws_event="case.restored",
                ws_payload={},
                audit_action="test_case.restored",
                transitioned=False,
            )
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="test_case.restored",
            resource_type="test_case",
            resource_id=case.id,
            metadata={
                "publicId": case.public_id,
                "restoredAt": restored_at.isoformat(),
            },
        )
        return CaseLifecycleResult(
            ws_event="case.restored",
            ws_payload={
                "caseId": case.id,
                "publicId": case.public_id,
                "suiteId": case.suite_id,
            },
            audit_action="test_case.restored",
            transitioned=True,
        )


class StepReorderMismatchError(Exception):
    """``PATCH /test-cases/:id/steps/reorder`` body does not match the live step ids."""

    def __init__(
        self,
        *,
        duplicates: list[str],
        missing: list[str],
        unknown: list[str],
    ) -> None:
        super().__init__("reorder body must contain every step id exactly once")
        self.duplicates = duplicates
        self.missing = missing
        self.unknown = unknown


# Re-export the validator error types so routers can ``except`` from a single
# module — keeps the import surface narrow for the (already long) router file.
from suitest_api.services.test_case_validator import (  # noqa: E402
    McpProviderNotRegisteredError,
    StepsRequireCodeError,
)

__all__ = [
    "BulkLimitExceededError",
    "BulkPerCaseAudit",
    "BulkUpdateResult",
    "CaseLifecycleResult",
    "CaseWriteResult",
    "ConcurrentModificationError",
    "CrossWorkspaceIdsError",
    "InvalidBulkTargetSuiteError",
    "McpProviderNotRegisteredError",
    "StepReorderMismatchError",
    "StepsRequireCodeError",
    "TestCaseService",
]


# Unused import keeps SQLAlchemy from import-cycle complaints when this module
# is the only entrypoint that pulls :class:`CaseTag` — explicit re-export
# is not needed for callers but keeps the ORM registry hot when test
# collection imports just this service.
_ = CaseTag
