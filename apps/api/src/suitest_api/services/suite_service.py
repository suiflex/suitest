"""SuiteService — read + M1d-4 write API for the suite domain.

Read path: suites are scoped through their parent project's workspace (a suite
has no ``workspace_id`` column). Methods return ``None`` for cross-workspace ids
so the router can map to 404 without leaking existence to non-owners.

Write path (M1d-4): ``create``, ``update`` (incl. atomic ``case_order``
reorder), ``soft_delete_with_cascade``, ``restore``. Each method opens a single
transaction owned by the caller (router commits), calls the repo, writes
audit, and stamps the WS event helper the router fires after the commit so
subscribers never see a phantom event for a rolled-back write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.project import Suite
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.schemas.responses import SuiteOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.schemas.suite import SuiteCreate, SuiteUpdate


class CaseOrderMismatchError(Exception):
    """Raised when ``case_order`` does not match the suite's active case set.

    The router translates this into a 400 with ``details.missing`` /
    ``details.unknown`` / ``details.duplicate`` per docs/API.md §326.
    """

    def __init__(
        self,
        *,
        missing: list[str],
        unknown: list[str],
        duplicates: list[str],
    ) -> None:
        super().__init__("case_order must contain every active case id exactly once")
        self.missing = missing
        self.unknown = unknown
        self.duplicates = duplicates


class ConfirmCascadeRequiredError(Exception):
    """Raised when a DELETE lacks ``confirmCascade=true`` and the suite has cases.

    The router translates this into a 409 ``CONFIRM_CASCADE_REQUIRED`` with
    ``details.childCount`` and ``details.resourceType="suite"`` per the M1d
    error matrix (plan-05b Appendix H).
    """

    def __init__(self, *, child_count: int) -> None:
        super().__init__("delete requires confirmCascade=true — suite has child cases")
        self.child_count = child_count


class SuiteWriteResult(NamedTuple):
    """Outcome bundle: read DTO + the WS event the router should emit.

    Keeping the WS event out-of-band (vs. having the service publish directly)
    lets the router wait for the transaction to commit before broadcasting —
    subscribers never observe a phantom event for a rolled-back write.
    """

    suite: SuiteOut
    ws_event: str
    ws_payload: dict[str, object]


class SuiteService:
    def __init__(self, ctx: TenantContext, repo: SuiteRepo, project_repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo

    @property
    def _session(self) -> AsyncSession:
        return self._repo.session

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def _load_active_suite_in_scope(self, suite_id: str) -> Suite | None:
        """Return an active (non-deleted) suite owned by the active workspace."""
        suite = await self._repo.get_active_by_id(suite_id)
        if suite is None or not await self._project_in_scope(suite.project_id):
            return None
        return suite

    # ------------------------------------------------------------------
    # Read path (M1a)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def list(self, project_id: str) -> list[SuiteOut] | None:
        if not await self._project_in_scope(project_id):
            return None
        rows = await self._repo.list_by_project(project_id)
        return [SuiteOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, suite_id: str) -> SuiteOut | None:
        row = await self._repo.get_by_id(suite_id)
        if row is None or not await self._project_in_scope(row.project_id):
            return None
        return SuiteOut.model_validate(row)

    # ------------------------------------------------------------------
    # Write path (M1d-4)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create(self, body: SuiteCreate) -> SuiteWriteResult | None:
        """Create a suite under the supplied project.

        Returns ``None`` when the target project is cross-workspace — the
        router maps to 404 (NEVER 403, to avoid an enumeration oracle).
        """
        if not await self._project_in_scope(body.project_id):
            return None

        suite = Suite(
            project_id=body.project_id,
            name=body.name,
            description=body.description,
            order=body.order,
        )
        self._session.add(suite)
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="suite.created",
            resource_type="suite",
            resource_id=suite.id,
            metadata={
                "projectId": suite.project_id,
                "name": suite.name,
            },
        )
        return SuiteWriteResult(
            suite=SuiteOut.model_validate(suite),
            ws_event="suite.created",
            ws_payload={
                "suiteId": suite.id,
                "projectId": suite.project_id,
                "name": suite.name,
            },
        )

    @require_tier(TierFlag.ANY)
    async def update(self, suite_id: str, body: SuiteUpdate) -> SuiteWriteResult | None:
        """Patch metadata; optional atomic ``case_order`` reorder in the same TX.

        ``case_order`` must contain every active case id in the suite exactly
        once — a mismatch raises :class:`CaseOrderMismatchError` and the router
        maps it to 400 with ``details.missing`` / ``details.unknown`` /
        ``details.duplicate``.

        Audit emits ``suite.case_order.reordered`` when ``case_order`` is
        supplied AND ``suite.updated`` when any metadata column moved. The
        router gets back one WS event — ``suite.case_order.reordered`` when
        the reorder fired, else ``suite.updated``.
        """
        suite = await self._load_active_suite_in_scope(suite_id)
        if suite is None:
            return None

        payload = body.model_dump(exclude_unset=True)
        changed_fields: list[str] = []
        for field in ("name", "description", "order"):
            if field in payload:
                setattr(suite, field, payload[field])
                changed_fields.append(field)

        reorder_emitted = False
        cascade_case_ids: list[str] = []
        if "case_order" in payload and payload["case_order"] is not None:
            submitted = list(payload["case_order"])
            live = await self._repo.active_case_ids_in_order(suite.id)
            live_set = set(live)
            submitted_set = set(submitted)
            duplicates = sorted(cid for cid in submitted_set if submitted.count(cid) > 1)
            missing = sorted(live_set - submitted_set)
            unknown = sorted(submitted_set - live_set)
            if duplicates or missing or unknown:
                raise CaseOrderMismatchError(
                    missing=missing, unknown=unknown, duplicates=duplicates
                )
            await self._repo.reorder_active_cases(suite.id, submitted)
            cascade_case_ids = submitted
            reorder_emitted = True
            # Mutate ``order`` to itself when no metadata changed so the
            # row's ``updated_at`` advances via the TimestampMixin onupdate
            # hook (the bulk UPDATE on test_cases does not bump the parent).
            if not changed_fields:
                suite.order = suite.order
            changed_fields.append("case_order")

        await self._session.flush()

        if reorder_emitted:
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="suite.case_order.reordered",
                resource_type="suite",
                resource_id=suite.id,
                metadata={"caseIds": cascade_case_ids},
            )
        if any(f for f in changed_fields if f != "case_order"):
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="suite.updated",
                resource_type="suite",
                resource_id=suite.id,
                metadata={"fields": [f for f in changed_fields if f != "case_order"]},
            )

        if reorder_emitted:
            ws_event = "suite.case_order.reordered"
            ws_payload: dict[str, object] = {
                "suiteId": suite.id,
                "caseIds": cascade_case_ids,
            }
        else:
            ws_event = "suite.updated"
            ws_payload = {
                "suiteId": suite.id,
                "fields": changed_fields,
            }
        return SuiteWriteResult(
            suite=SuiteOut.model_validate(suite),
            ws_event=ws_event,
            ws_payload=ws_payload,
        )

    @require_tier(TierFlag.ANY)
    async def soft_delete_with_cascade(
        self, suite_id: str, *, confirm_cascade: bool
    ) -> SuiteWriteResult | None:
        """Soft-delete the suite (+ cascade child cases when confirmed).

        Cascade pre-check runs against the live count of active children;
        if ``confirm_cascade`` is False AND the count is > 0,
        :class:`ConfirmCascadeRequiredError` raises with ``child_count`` so
        the router can build the canonical envelope. A suite with zero
        active cases soft-deletes immediately (no confirmation required —
        nothing to cascade).
        """
        suite = await self._load_active_suite_in_scope(suite_id)
        if suite is None:
            return None

        child_count = await self._repo.count_active_children(suite.id)
        if child_count > 0 and not confirm_cascade:
            raise ConfirmCascadeRequiredError(child_count=child_count)

        suite_touched, cascaded = await self._repo.soft_delete_with_cascade(suite.id)
        if not suite_touched:
            # Race: another writer tombstoned between the active-suite load
            # and the bulk UPDATE. Treat as not-found so the router emits
            # 404 (idempotent).
            return None

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="suite.soft_deleted_with_cascade",
            resource_type="suite",
            resource_id=suite.id,
            metadata={
                "childCaseIds": cascaded,
                "childCount": len(cascaded),
            },
        )
        # The repo bulk-UPDATE expired the ``deleted_at`` / ``updated_at``
        # attributes on the in-memory suite row; refresh so SuiteOut sees
        # post-mutation columns rather than triggering an implicit lazy load
        # (which raises ``MissingGreenlet`` under asyncpg).
        await self._session.refresh(suite)
        return SuiteWriteResult(
            suite=SuiteOut.model_validate(suite),
            ws_event="suite.deleted",
            ws_payload={
                "suiteId": suite.id,
                "cascadedCaseIds": cascaded,
            },
        )

    @require_tier(TierFlag.ANY)
    async def restore(self, suite_id: str) -> SuiteWriteResult | None:
        """Clear ``deleted_at`` on the suite (children stay tombstoned).

        Returns ``None`` for a non-existent suite or a suite in another
        workspace (router maps to 404). Returns the result when the suite
        is restored OR was already active (idempotent — re-POST after a
        successful restore returns the same 204 envelope on the wire).
        """
        # Load WITHOUT the deleted_at filter — restore needs to flip a
        # tombstoned row, not an active one. Cross-workspace 404 still wins.
        suite = await self._repo.get_by_id(suite_id)
        if suite is None or not await self._project_in_scope(suite.project_id):
            return None

        was_deleted = suite.deleted_at is not None
        if was_deleted:
            # Idempotency: if a race cleared the tombstone between load and
            # flip, ``restore`` simply no-ops (returns False); we still emit
            # the audit row so an operator can see the intent.
            await self._repo.restore(suite.id)
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="suite.restored",
                resource_type="suite",
                resource_id=suite.id,
                metadata={"projectId": suite.project_id},
            )
        # Refresh so SuiteOut reflects the cleared deleted_at if any.
        await self._session.refresh(suite)
        return SuiteWriteResult(
            suite=SuiteOut.model_validate(suite),
            ws_event="suite.restored",
            ws_payload={
                "suiteId": suite.id,
                "projectId": suite.project_id,
            },
        )
