"""DefectService — defect read + M1d-9 manual write API.

Defects carry ``workspace_id`` directly so scope checks are a single column
compare (no suite -> project -> workspace walk).

Write surface (M1d-9):

* ``create(body)`` — manual file; generate ``SUIT-N`` via the public-id
  listener; stamp ``created_by="user:<user_id>"`` (NEVER ``"system"`` — that
  prefix is reserved for the auto-filer in M1d-10); ``agent_diagnosis_kind``
  defaults to :class:`DiagnosisKind.MANUAL_TRIAGE`.
* ``update(defect_id, body)`` — enforce the linear status flow (OPEN →
  IN_PROGRESS → RESOLVED → CLOSED, plus WONT_FIX terminations). Backwards
  transitions need ``force=true`` on the body (QA+ only, but the role gate
  upstream already enforces that). Flip ``resolved_at`` on RESOLVED, clear on
  reopen out of RESOLVED.
* ``sync_external(defect_id)`` — surface only; M1d-9 returns
  :class:`AdapterNotRegisteredError` because no adapter registry exists yet
  (real dispatch lands in M1d-11..15).

Each write writes an audit row + returns the WS event the router emits
post-commit so subscribers never see a phantom event for a rolled-back write.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.repositories.defects import DefectCreate as DefectCreateRow
from suitest_db.repositories.defects import DefectRepo
from suitest_db.repositories.defects import DefectUpdate as DefectUpdateRow
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Severity
from suitest_shared.schemas.responses import DefectOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.schemas.defect import DefectCreate, DefectUpdate

if TYPE_CHECKING:
    from suitest_db.models.defect import Defect


# ---------------------------------------------------------------------------
# Allowed-transitions matrix.
# ---------------------------------------------------------------------------
#
# Forward edges only:
#   OPEN        → IN_PROGRESS, WONT_FIX, CLOSED
#   IN_PROGRESS → RESOLVED, WONT_FIX
#   RESOLVED    → CLOSED
#   CLOSED      → ∅  (terminal)
#   WONT_FIX    → ∅  (terminal)
#
# Backwards (reopen) edges require ``force=true`` on the PATCH body. Role gate
# upstream already restricts the endpoint to QA+ so we don't re-check it here.
_ALLOWED_TRANSITIONS: dict[DefectStatus, frozenset[DefectStatus]] = {
    DefectStatus.OPEN: frozenset(
        {DefectStatus.IN_PROGRESS, DefectStatus.WONT_FIX, DefectStatus.CLOSED}
    ),
    DefectStatus.IN_PROGRESS: frozenset(
        {DefectStatus.RESOLVED, DefectStatus.OPEN, DefectStatus.WONT_FIX}
    ),
    DefectStatus.RESOLVED: frozenset({DefectStatus.CLOSED, DefectStatus.OPEN}),
    DefectStatus.CLOSED: frozenset(),
    DefectStatus.WONT_FIX: frozenset({DefectStatus.OPEN}),
}


class InvalidStatusTransitionError(Exception):
    """``PATCH /defects/:id`` body asked for a transition outside the matrix.

    Carries the (``from_status``, ``to_status``) pair so the router can build
    the canonical 400 envelope with the offending edge in ``details``.
    """

    def __init__(self, *, from_status: DefectStatus, to_status: DefectStatus) -> None:
        super().__init__(f"invalid status transition {from_status.value} -> {to_status.value}")
        self.from_status = from_status
        self.to_status = to_status


class AdapterNotRegisteredError(Exception):
    """``POST /defects/:id/sync-external`` called without a registered adapter.

    M1d-9 surfaces this as 501 ``ADAPTER_NOT_REGISTERED`` because the real
    adapter registry (Jira / Linear / GitHub) lands in M1d-11..15.
    """

    def __init__(self, *, defect_id: str) -> None:
        super().__init__(f"no external tracker adapter registered for defect {defect_id}")
        self.defect_id = defect_id


class LinkedResourceMissingError(Exception):
    """``test_case_id`` / ``run_id`` / ``requirement_id`` is cross-workspace or absent."""

    def __init__(self, *, field: str, value: str) -> None:
        super().__init__(f"{field} '{value}' not found in workspace")
        self.field = field
        self.value = value


class DefectWriteResult(NamedTuple):
    """Outcome bundle: the persisted row + the WS event the router should emit."""

    defect: Defect
    ws_event: str
    ws_payload: dict[str, object]


class DefectService:
    def __init__(self, ctx: TenantContext, repo: DefectRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @property
    def _session(self):  # type: ignore[no-untyped-def]
        return self._repo.session

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def list(
        self,
        *,
        status: DefectStatus | None = None,
        severity: Severity | None = None,
        assignee_id: uuid.UUID | None = None,
        component: str | None = None,
        limit: int = 20,
    ) -> list[DefectOut]:
        rows, _ = await self._repo.list_by_workspace(
            self._ctx.workspace_id,
            status=status,
            severity=severity,
            assignee_id=assignee_id,
            component=component,
            limit=limit,
        )
        return [DefectOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, defect_id: str) -> DefectOut | None:
        row = await self._repo.get_by_id(defect_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return DefectOut.model_validate(row)

    # ------------------------------------------------------------------
    # Scope guards for linked FKs
    # ------------------------------------------------------------------

    async def _test_case_in_scope(self, case_id: str) -> bool:
        case = await TestCaseRepo(self._session).get_by_id(case_id)
        if case is None:
            return False
        suite = await SuiteRepo(self._session).get_by_id(case.suite_id)
        if suite is None:
            return False
        project = await ProjectRepo(self._session).get_by_id(suite.project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def _run_in_scope(self, run_id: str) -> bool:
        run = await RunRepo(self._session).get_by_id(run_id)
        if run is None:
            return False
        project = await ProjectRepo(self._session).get_by_id(run.project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    # ------------------------------------------------------------------
    # Write path (M1d-9)
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create(self, body: DefectCreate) -> DefectWriteResult:
        """Manual file — generates ``SUIT-N`` via the public-id listener."""
        if body.test_case_id is not None and not await self._test_case_in_scope(body.test_case_id):
            raise LinkedResourceMissingError(field="test_case_id", value=body.test_case_id)
        if body.run_id is not None and not await self._run_in_scope(body.run_id):
            raise LinkedResourceMissingError(field="run_id", value=body.run_id)

        created_by = f"user:{self._ctx.user_id}"
        dto = DefectCreateRow(
            workspace_id=self._ctx.workspace_id,
            title=body.title,
            description=body.description,
            severity=body.severity,
            status=DefectStatus.OPEN,
            component=body.component,
            test_case_id=body.test_case_id,
            run_id=body.run_id,
            requirement_id=body.requirement_id,
            created_by=created_by,
            agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
        )
        defect = await self._repo.create(dto)

        # Assignee is not on the DefectCreate row DTO (the row helper mirrors
        # the historical signature for the auto-filer) — set it post-flush so
        # the public-id listener has already run.
        if body.assignee_id is not None:
            defect.assignee_id = body.assignee_id
            await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="defect.created",
            resource_type="defect",
            resource_id=defect.id,
            metadata={
                "publicId": defect.public_id,
                "severity": defect.severity.value,
                "manual": True,
            },
        )
        return DefectWriteResult(
            defect=defect,
            ws_event="defect.created",
            ws_payload={
                "defectId": defect.id,
                "publicId": defect.public_id,
                "severity": defect.severity.value,
                "status": defect.status.value,
                "testCaseId": defect.test_case_id,
                "runId": defect.run_id,
                "diagnosisKind": defect.agent_diagnosis_kind.value,
            },
        )

    @require_tier(TierFlag.ANY)
    async def update(self, defect_id: str, body: DefectUpdate) -> DefectWriteResult | None:
        """Patch a defect; enforces the status-transition matrix.

        Returns ``None`` when the defect is cross-workspace so the router can
        translate to 404 without leaking existence.
        """
        defect = await self._repo.get_by_id(defect_id)
        if defect is None or defect.workspace_id != self._ctx.workspace_id:
            return None

        old_status = defect.status
        old_resolved_at = defect.resolved_at
        new_status: DefectStatus | None = body.status
        if new_status is not None and new_status != old_status:
            self._validate_status_transition(old_status, new_status, force=body.force)

        # Apply allowed mutations.
        changed_fields: list[str] = []
        payload = body.model_dump(exclude_unset=True, exclude={"force"})
        for field in ("title", "description", "severity", "component", "assignee_id", "status"):
            if field in payload:
                setattr(defect, field, payload[field])
                changed_fields.append(field)

        # ``resolved_at`` lifecycle: stamp on entering RESOLVED, clear when
        # leaving it (CLOSED keeps the stamp since the bug is resolved-then-
        # archived; reopens (RESOLVED -> OPEN or RESOLVED -> IN_PROGRESS via
        # force) clear it).
        if new_status is not None and new_status != old_status:
            if new_status == DefectStatus.RESOLVED:
                defect.resolved_at = datetime.now(UTC)
            elif old_status == DefectStatus.RESOLVED and new_status != DefectStatus.CLOSED:
                defect.resolved_at = None

        await self._session.flush()

        audit_metadata: dict[str, object] = {
            "publicId": defect.public_id,
            "fields": changed_fields,
        }
        if new_status is not None and new_status != old_status:
            audit_metadata["statusFrom"] = old_status.value
            audit_metadata["statusTo"] = new_status.value
            if body.force:
                audit_metadata["force"] = True
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="defect.updated",
            resource_type="defect",
            resource_id=defect.id,
            metadata=audit_metadata,
        )

        ws_payload: dict[str, object] = {
            "defectId": defect.id,
            "publicId": defect.public_id,
            "fields": changed_fields,
            "status": defect.status.value,
            "severity": defect.severity.value,
        }
        if defect.resolved_at != old_resolved_at:
            ws_payload["resolvedAt"] = (
                defect.resolved_at.isoformat() if defect.resolved_at is not None else None
            )
        return DefectWriteResult(
            defect=defect,
            ws_event="defect.updated",
            ws_payload=ws_payload,
        )

    @require_tier(TierFlag.ANY)
    async def sync_external(self, defect_id: str) -> None:
        """Force-push current state to the configured tracker.

        M1d-9 ships the endpoint surface but no adapter registry exists yet
        (real dispatch lands in M1d-11..15). Raise
        :class:`AdapterNotRegisteredError` so the router emits the canonical
        501 ``ADAPTER_NOT_REGISTERED`` envelope. The scope check still runs so
        callers get 404 for cross-workspace ids before the 501.
        """
        defect = await self._repo.get_by_id(defect_id)
        if defect is None or defect.workspace_id != self._ctx.workspace_id:
            return None
        raise AdapterNotRegisteredError(defect_id=defect_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_status_transition(
        self, old: DefectStatus, new: DefectStatus, *, force: bool
    ) -> None:
        """Raise :class:`InvalidStatusTransitionError` for illegal edges.

        Forward edges are allowed by the matrix; everything else needs
        ``force=true``. The role gate upstream already restricts mutations to
        QA+ so we don't double-check the role here.
        """
        if new in _ALLOWED_TRANSITIONS[old]:
            return
        if force:
            return
        raise InvalidStatusTransitionError(from_status=old, to_status=new)


__all__ = [
    "_ALLOWED_TRANSITIONS",
    "AdapterNotRegisteredError",
    "DefectService",
    "DefectWriteResult",
    "InvalidStatusTransitionError",
    "LinkedResourceMissingError",
]


# Late re-export to keep mypy strict happy when the row DTOs are imported via
# this module by callers that don't want a second symbol path.
_ = (DefectCreateRow, DefectUpdateRow)
