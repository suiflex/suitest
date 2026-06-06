"""Rule-based defect auto-filer (M1d-10).

On runner step failure (``StepOutcome.FAIL``) the runner's
:func:`suitest_runner.handlers.step_handler.on_run_step_failed` calls
:meth:`DefectAutoFiler.file_for_failed_step`, which:

1. Loads the ``RunStep`` + parent ``Run`` + originating ``TestCase`` from the
   database.
2. Categorises the failure via :class:`DefectCategorizer` — a deterministic
   regex matcher over ``stderr`` + ``stdout`` + assertion message that returns
   one of :class:`DiagnosisKind` (``INFRA`` / ``FLAKE`` / ``REGRESSION`` /
   ``SPEC_DRIFT`` / ``MANUAL_TRIAGE`` fallback).
3. Maps the test case ``Priority`` to a defect ``Severity`` via
   :data:`_SEVERITY_BY_PRIORITY` (P0→CRITICAL, P1→HIGH, P2→MEDIUM, P3→LOW).
4. Inserts the defect with ``created_by='system'``. Dedup is enforced by the
   ``uq_defects_auto_dedup`` partial unique index (revision
   ``0021_m1d_06_defect_dedup``) on ``(run_id, test_case_id) WHERE
   created_by = 'system'`` — a second call for the same ``(run, case)``
   triggers an :class:`IntegrityError` which the filer catches and returns
   ``None`` from. The partial predicate scopes the constraint to
   ``system``-filed rows only, so a QA can still hand-file additional defects
   on the same failure.
5. Writes a ``defect.auto_filed`` audit row carrying the chosen ``kind`` +
   ``severity`` in metadata.
6. Publishes a ``defect.created`` event on the ``workspace:<wsId>`` Redis
   channel exactly once (only on the success branch; the dedup branch is
   silent because the original creation already broadcast).
7. Enqueues an ARQ ``file_external_issue`` job per active issue-tracker
   integration in the workspace (M1d-12..14 ship the adapters; this filer
   just enqueues).
8. Enqueues an ARQ ``send_slack_notification`` job per active Slack
   integration in the workspace (M1d-15 ships the adapter; same pattern).

The auto-filer is the **only** path that writes ``created_by='system'``;
human-filed defects (M1d-9 endpoints) always set the actor's ``user_id``
string as the value.

M3 will swap :class:`DefectCategorizer` for an LLM-backed implementation
behind the same Protocol; the rest of the surface stays unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NamedTuple, Protocol

import structlog
from sqlalchemy.exc import IntegrityError
from suitest_db.audit import write_audit
from suitest_db.models.case import TestCase
from suitest_db.models.defect import Defect
from suitest_db.models.integration import Integration
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
from suitest_db.public_id import set_workspace_id
from suitest_shared.domain.enums import (
    DefectStatus,
    DiagnosisKind,
    IntegrationKind,
    Priority,
    Severity,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class LlmDiagnosis(NamedTuple):
    """LLM diagnosis result (M3-11) — supplants the regex bucket when present."""

    kind: DiagnosisKind
    confidence: float
    text: str


# Resolves a failed-step ``evidence`` blob into an :class:`LlmDiagnosis`, or
# ``None`` when no LLM is configured / the call fails (regex fallback then wins).
# The runner wires :func:`build_llm_diagnoser`; tests pass a stub or ``None``.
DefectDiagnoser = Callable[["AsyncSession", str, str], Awaitable["LlmDiagnosis | None"]]


# ---------------------------------------------------------------------------
# Categorizer
# ---------------------------------------------------------------------------


# Ordered list of ``(pattern, kind)`` pairs. The first pattern that matches
# the concatenated ``stderr`` + ``stdout`` + assertion message wins. Order is
# load-bearing — INFRA precedes FLAKE because "ECONNREFUSED" can otherwise be
# misclassified as a timeout, and REGRESSION precedes SPEC_DRIFT because
# "expected N got M" applies to both API status mismatches and JSON path
# mismatches but the former is the more common (and more actionable) bucket.
_RULES: Final[tuple[tuple[re.Pattern[str], DiagnosisKind], ...]] = (
    (
        re.compile(
            r"(econnrefused|connection refused|503 service unavailable|"
            r"5\d\d.*db|database is starting up|no route to host|"
            r"network is unreachable)",
            re.IGNORECASE,
        ),
        DiagnosisKind.INFRA,
    ),
    (
        re.compile(
            r"(timeout|timed?\s*out|exceeded.*deadline|intermittent|flaky|retry)",
            re.IGNORECASE,
        ),
        DiagnosisKind.FLAKE,
    ),
    (
        re.compile(
            r"(expected\s+.*\s+(got|but got|to be)|status\s+\d+\s*!=\s*\d+|"
            r"response code mismatch|assertion\s*error)",
            re.IGNORECASE,
        ),
        DiagnosisKind.REGRESSION,
    ),
    (
        re.compile(
            r"(jsonpath.*no match|header.*missing|schema.*mismatch|"
            r"missing field|unexpected key|selector\s+.*\s+not found)",
            re.IGNORECASE,
        ),
        DiagnosisKind.SPEC_DRIFT,
    ),
)


# Priority → Severity mapping for system-filed defects. The test case author
# pins the business priority on the case row; we lift it onto the auto-filed
# defect so workspace readiness dashboards (M1d-26) bucket the failure by the
# same dial QA already curated.
_SEVERITY_BY_PRIORITY: Final[dict[Priority, Severity]] = {
    Priority.P0: Severity.CRITICAL,
    Priority.P1: Severity.HIGH,
    Priority.P2: Severity.MEDIUM,
    Priority.P3: Severity.LOW,
}


class DefectCategorizer:
    """Pure regex categorizer used by :class:`DefectAutoFiler`.

    Stateless — safe to share one instance across the entire runner process.
    The categorisation order mirrors :data:`_RULES` so adding a new rule means
    inserting one tuple at the right priority position.
    """

    def categorize(
        self,
        *,
        stderr: str,
        stdout: str,
        assertion_message: str | None,
    ) -> DiagnosisKind:
        """Return the first matching :class:`DiagnosisKind` or MANUAL_TRIAGE.

        The three inputs are concatenated with newlines so a pattern that
        spans channels (e.g. assertion message saying ``timeout`` while
        ``stderr`` is empty) still matches. Empty / None inputs become empty
        strings — the regex engine handles that cleanly.
        """
        blob = "\n".join(
            part for part in (stderr or "", stdout or "", assertion_message or "") if part
        )
        for pattern, kind in _RULES:
            if pattern.search(blob):
                return kind
        return DiagnosisKind.MANUAL_TRIAGE


def severity_for_priority(priority: Priority | None) -> Severity:
    """Lift the case ``priority`` onto the defect ``severity`` axis.

    Defaults to MEDIUM when the case has no priority pinned — the schema
    defaults to ``P2`` so this only fires for tests that explicitly null it
    out via legacy migrations.
    """
    if priority is None:
        return Severity.MEDIUM
    return _SEVERITY_BY_PRIORITY.get(priority, Severity.MEDIUM)


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


class CategorizedDefect(NamedTuple):
    """The shape :class:`DefectAutoFiler` projects from a failed step.

    Kept as a :class:`NamedTuple` (rather than a dataclass) so it slots
    cleanly into the runner's existing observability spans without dragging
    a Pydantic dep in.
    """

    title: str
    description: str
    severity: Severity
    diagnosis_kind: DiagnosisKind
    labels: list[str]
    metadata: dict[str, object]
    # M3-11: populated only on the LLM path; None keeps the regex path's shape.
    confidence: float | None = None
    diagnosis_text: str | None = None


# ---------------------------------------------------------------------------
# Auto-filer
# ---------------------------------------------------------------------------


class _ArqEnqueueCapable(Protocol):
    """Subset of :class:`arq.connections.ArqRedis` :meth:`enqueue_job` we need.

    Declared as a Protocol so tests can pass a recorder that just captures
    ``(name, args, kwargs)`` tuples — no ARQ install required to unit-test
    the filer.
    """

    async def enqueue_job(
        self,
        name: str,
        *args: object,
        **kwargs: object,
    ) -> object: ...


class _PublishCapable(Protocol):
    """Minimum Redis publish surface (matches the runner's ``_Publisher``)."""

    async def publish(self, channel: str, message: str | bytes) -> int: ...


@dataclass
class DefectAutoFiler:
    """Service that turns a failed ``RunStep`` into a ``defects`` row.

    Constructed once per runner process — the dependencies passed in
    (session factory, redis publisher, ARQ pool, categorizer) are all
    long-lived. Every call to :meth:`file_for_failed_step` opens its own
    short-lived session so concurrency-safe SQLAlchemy semantics hold.
    """

    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    publisher: _PublishCapable | None
    arq_pool: _ArqEnqueueCapable | None
    categorizer: DefectCategorizer
    # M3-11: optional LLM diagnoser. None → pure regex (ZERO-tier behavior).
    diagnoser: DefectDiagnoser | None = None

    async def file_for_failed_step(self, run_step_id: str) -> Defect | None:
        """File one defect for a failed ``RunStep`` (idempotent on retry).

        Returns the inserted :class:`Defect` row, or ``None`` when:

        * the ``run_step_id`` doesn't exist or isn't actually FAILed,
        * the parent ``Run`` / ``TestCase`` / ``Project`` chain is missing,
        * the partial unique idx fires (someone else already filed for
          ``(run_id, test_case_id, created_by='system')``).

        The function NEVER raises into the caller — every failure mode is
        absorbed into a structured log + ``None`` return so the runner can
        keep the run record clean even if the defect pipeline is degraded.
        """
        try:
            return await self._file_impl(run_step_id)
        except Exception as exc:  # pragma: no cover — last-resort safety
            log.exception(
                "defect.auto_filer.error",
                run_step_id=run_step_id,
                error=str(exc),
            )
            return None

    async def _file_impl(self, run_step_id: str) -> Defect | None:
        """The hot path. Separated from the wrapper so the wrapper stays trivial."""
        async with self.session_factory() as session:
            run_step = await session.get(RunStep, run_step_id)
            if run_step is None:
                log.info("defect.auto_filer.missing_run_step", run_step_id=run_step_id)
                return None

            run = await session.get(Run, run_step.run_id)
            if run is None:
                log.info("defect.auto_filer.missing_run", run_step_id=run_step_id)
                return None

            case = await session.get(TestCase, run_step.case_id)
            if case is None:
                log.info("defect.auto_filer.missing_case", run_step_id=run_step_id)
                return None

            # Look up the workspace via the suite → project chain. We do this
            # via ``session.get`` (not a join) because the chain is at most
            # two hops and the rows are already hot in the buffer pool from
            # the run lookup.
            suite = await session.get(Suite, case.suite_id)
            if suite is None:
                log.info("defect.auto_filer.missing_suite", run_step_id=run_step_id)
                return None
            project = await session.get(Project, suite.project_id)
            if project is None:
                log.info("defect.auto_filer.missing_project", run_step_id=run_step_id)
                return None
            workspace_id = project.workspace_id
            if workspace_id is None:
                log.info("defect.auto_filer.no_workspace", run_step_id=run_step_id)
                return None

            # M3-11: when an LLM is wired + configured, classify the failure
            # (REGRESSION / FLAKE / INFRA / SPEC_DRIFT / MANUAL_TRIAGE +
            # confidence + root cause). Any failure falls back to the regex
            # bucket so the defect still files (ZERO-first).
            llm_diag: LlmDiagnosis | None = None
            if self.diagnoser is not None:
                try:
                    llm_diag = await self.diagnoser(
                        session, workspace_id, _assemble_evidence(run_step, case)
                    )
                except Exception as exc:  # pragma: no cover — logged, swallowed
                    log.warning(
                        "defect.auto_filer.diagnose_skip",
                        run_step_id=run_step_id,
                        reason=str(exc),
                    )

            categorized = self._categorize_for_step(
                run_step=run_step,
                case=case,
                llm=llm_diag,
            )

            defect = Defect(
                workspace_id=workspace_id,
                test_case_id=case.id,
                run_id=run.id,
                title=categorized.title,
                description=categorized.description,
                severity=categorized.severity,
                status=DefectStatus.OPEN,
                agent_diagnosis_kind=categorized.diagnosis_kind,
                agent_confidence=categorized.confidence,
                agent_diagnosis=categorized.diagnosis_text,
                created_by="system",
                stack_trace=run_step.error_message,
            )
            set_workspace_id(defect, workspace_id)
            session.add(defect)
            try:
                await session.flush()
            except IntegrityError as exc:
                # ``uq_defects_auto_dedup`` partial unique idx fired — another
                # invocation of this filer (or a runner retry) already filed
                # the canonical system-defect for this (run, case). Roll the
                # session back so the in-flight transaction stays usable, and
                # return ``None`` so the caller treats it as a no-op.
                await session.rollback()
                log.info(
                    "defect.auto_filer.dedup",
                    run_id=run.id,
                    test_case_id=case.id,
                    reason=str(exc.orig) if exc.orig else "unique_violation",
                )
                return None

            await write_audit(
                session,
                workspace_id=workspace_id,
                user_id=None,
                action="defect.auto_filed",
                resource_type="defect",
                resource_id=defect.id,
                metadata={
                    "kind": categorized.diagnosis_kind.value,
                    "severity": categorized.severity.value,
                    "diagnosis_source": "ai" if llm_diag is not None else "rule-based",
                    "confidence": categorized.confidence,
                    "run_id": run.id,
                    "test_case_id": case.id,
                    "run_step_id": run_step.id,
                },
            )

            # Snapshot the integrations BEFORE commit so we can enqueue
            # outside the transaction (avoid holding a DB connection across
            # the ARQ enqueue round-trip).
            issue_tracker_ints, slack_ints = await _load_active_integrations(session, workspace_id)

            await session.commit()
            # Refresh from the now-committed row so the public_id (assigned
            # by the ``before_insert`` listener) is reflected on the returned
            # object. ``refresh`` issues a single SELECT.
            await session.refresh(defect)

        # ---- post-commit side effects ----------------------------------
        await self._publish_defect_created(defect, workspace_id)
        await self._enqueue_external_issue_jobs(defect.id, issue_tracker_ints)
        await self._enqueue_slack_jobs(defect.id, slack_ints)

        return defect

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _categorize_for_step(
        self, *, run_step: RunStep, case: TestCase, llm: LlmDiagnosis | None = None
    ) -> CategorizedDefect:
        """Project a failed ``RunStep`` into a :class:`CategorizedDefect`.

        Uses the LLM diagnosis (``llm``) when present — its ``kind`` +
        ``confidence`` + root-cause text — otherwise the deterministic regex
        bucket. Description is templated: ``[Auto]`` prefix, the case public id,
        the diagnosis (+ source), and the first 200 chars of ``stderr`` so the
        operator gets actionable context without scrolling the full step log.
        """
        if llm is not None:
            kind = llm.kind
            confidence: float | None = llm.confidence
            diagnosis_text: str | None = llm.text
            source = "ai"
        else:
            kind = self.categorizer.categorize(
                stderr=run_step.stderr or "",
                stdout=run_step.stdout or "",
                assertion_message=run_step.error_message,
            )
            confidence = None
            diagnosis_text = None
            source = "rule-based"

        severity = severity_for_priority(case.priority)
        title = f"[Auto] {case.public_id} failed: {kind.value}"
        stderr_excerpt = (run_step.stderr or "")[:200]
        error_excerpt = (run_step.error_message or "")[:200]
        description_lines = [
            f"Automatic defect filed by runner after step {run_step.step_order} failed.",
            f"Test case: {case.public_id} — {case.name}",
            f"Diagnosis ({source}): {kind.value}"
            + (f" (confidence {confidence:.2f})" if confidence is not None else ""),
            f"Severity (from case priority): {severity.value}",
        ]
        if diagnosis_text:
            description_lines.append(f"Root cause: {diagnosis_text}")
        if error_excerpt:
            description_lines.append(f"Error: {error_excerpt}")
        if stderr_excerpt:
            description_lines.append(f"Stderr (first 200 chars): {stderr_excerpt}")
        description = "\n".join(description_lines)

        metadata: dict[str, object] = {
            "run_step_id": run_step.id,
            "step_order": run_step.step_order,
            "outcome": run_step.outcome.value,
            "diagnosis_source": source,
        }
        if confidence is not None:
            metadata["confidence"] = confidence
        return CategorizedDefect(
            title=title,
            description=description,
            severity=severity,
            diagnosis_kind=kind,
            labels=[f"diagnosis:{kind.value.lower()}", f"severity:{severity.value.lower()}"],
            metadata=metadata,
            confidence=confidence,
            diagnosis_text=diagnosis_text,
        )

    async def _publish_defect_created(self, defect: Defect, workspace_id: str) -> None:
        """Broadcast ``defect.created`` exactly once on success.

        Best-effort: a transient redis failure logs a warning but never
        bubbles into the caller (the defect row is already committed).
        """
        if self.publisher is None:
            return
        import json as _json

        payload = _json.dumps(
            {
                "event": "defect.created",
                "data": {
                    "defectId": defect.id,
                    "publicId": defect.public_id,
                    "title": defect.title,
                    "severity": defect.severity.value,
                    "kind": defect.agent_diagnosis_kind.value,
                    "runId": defect.run_id,
                    "testCaseId": defect.test_case_id,
                    "createdBy": defect.created_by,
                },
            }
        )
        try:
            await self.publisher.publish(f"workspace:{workspace_id}", payload)
        except Exception as exc:  # pragma: no cover — logged, swallowed
            log.warning(
                "defect.auto_filer.publish_skip",
                defect_id=defect.id,
                reason=str(exc),
            )

    async def _enqueue_external_issue_jobs(
        self, defect_id: str, integrations: list[Integration]
    ) -> None:
        """Enqueue ``file_external_issue`` per registered issue-tracker integration.

        Done outside the DB transaction so a slow / unreachable ARQ broker
        can never roll back the defect row.
        """
        if self.arq_pool is None or not integrations:
            return
        for integration in integrations:
            try:
                await self.arq_pool.enqueue_job(
                    "file_external_issue",
                    integration_id=integration.id,
                    defect_id=defect_id,
                )
            except Exception as exc:  # pragma: no cover — logged, swallowed
                log.warning(
                    "defect.auto_filer.arq_external_skip",
                    defect_id=defect_id,
                    integration_id=integration.id,
                    kind=integration.kind.value,
                    reason=str(exc),
                )

    async def _enqueue_slack_jobs(self, defect_id: str, integrations: list[Integration]) -> None:
        """Enqueue ``send_slack_notification`` per active Slack integration."""
        if self.arq_pool is None or not integrations:
            return
        for integration in integrations:
            try:
                await self.arq_pool.enqueue_job(
                    "send_slack_notification",
                    integration_id=integration.id,
                    defect_id=defect_id,
                )
            except Exception as exc:  # pragma: no cover — logged, swallowed
                log.warning(
                    "defect.auto_filer.arq_slack_skip",
                    defect_id=defect_id,
                    integration_id=integration.id,
                    reason=str(exc),
                )


# ---------------------------------------------------------------------------
# LLM diagnosis (M3-11)
# ---------------------------------------------------------------------------


def _assemble_evidence(run_step: RunStep, case: TestCase) -> str:
    """Build the evidence blob fed to the diagnosis LLM.

    Logs + assertion message + the case identity. Bounded so a runaway step log
    can't blow the prompt budget; richer signals (recent commits, prior-run
    history) are a follow-up.
    """
    parts = [
        f"Test case: {case.public_id} — {case.name}",
        f"Failed step order: {run_step.step_order}",
    ]
    if run_step.error_message:
        parts.append(f"Error / assertion: {run_step.error_message[:1000]}")
    if run_step.stderr:
        parts.append(f"Stderr:\n{run_step.stderr[:2000]}")
    if run_step.stdout:
        parts.append(f"Stdout:\n{run_step.stdout[:2000]}")
    return "\n\n".join(parts)


def build_llm_diagnoser() -> DefectDiagnoser:
    """Return a :data:`DefectDiagnoser` backed by the DIAGNOSIS graph (M3-11).

    Resolves the workspace's active ``LLMConfig`` per call; ZERO / no-LLM
    workspaces yield ``None`` so the filer keeps its regex bucket. Agent imports
    are deferred into the closure so the api package stays ZERO-import-clean.
    """

    async def _diagnose(
        session: AsyncSession, workspace_id: str, evidence: str
    ) -> LlmDiagnosis | None:
        from suitest_agent.graphs.diagnosis import build_diagnosis_graph
        from suitest_agent.providers.litellm_router import get_provider
        from suitest_db.repositories.llm_configs import LLMConfigRepo

        llm = await LLMConfigRepo(session).get_active(workspace_id)
        if llm is None:
            return None
        base_url = llm.config_json.get("base_url")
        provider = get_provider(
            llm.provider,
            api_key=llm.api_key_encrypted,
            base_url=base_url if isinstance(base_url, str) else None,
        )
        graph = build_diagnosis_graph(provider)
        state = await graph.ainvoke({"evidence": evidence, "model": llm.model})
        diagnosis = state.get("diagnosis")
        if diagnosis is None:
            return None
        text = diagnosis.root_cause
        if diagnosis.suggested_fix:
            text = f"{text} Suggested fix: {diagnosis.suggested_fix}"
        return LlmDiagnosis(
            kind=DiagnosisKind(diagnosis.category),
            confidence=diagnosis.confidence,
            text=text,
        )

    return _diagnose


# ---------------------------------------------------------------------------
# Integration lookup
# ---------------------------------------------------------------------------


# Which IntegrationKind values are issue-tracker adapters (vs notifier).
# Mirrors the split in ``apps/api/src/suitest_api/integrations/base.py``
# (Issue-tracker Protocol vs Notifier Protocol).
_ISSUE_TRACKER_KINDS: Final[frozenset[IntegrationKind]] = frozenset(
    {
        IntegrationKind.JIRA,
        IntegrationKind.LINEAR,
        IntegrationKind.GITHUB,
        IntegrationKind.GITLAB,
    }
)


async def _load_active_integrations(
    session: AsyncSession, workspace_id: str
) -> tuple[list[Integration], list[Integration]]:
    """Return ``(issue_tracker_integrations, slack_integrations)`` filtered to ``active``.

    The split keeps the auto-filer call sites separate (different ARQ job
    name + adapter Protocol) and is cheaper than two queries because the
    in-memory partition over a single result set is O(n) — n is bounded by
    the number of integrations per workspace (typically < 5).
    """
    from sqlalchemy import select

    stmt = select(Integration).where(
        Integration.workspace_id == workspace_id,
        Integration.status == "active",
    )
    rows = (await session.scalars(stmt)).all()
    issue_trackers: list[Integration] = []
    slack: list[Integration] = []
    for row in rows:
        if row.kind is IntegrationKind.SLACK:
            # Slack is a notifier — only enqueue when the config opts in via
            # ``default_for_notifications=true`` (the FE's "send defect
            # notifications here" checkbox sets it). Missing key defaults to
            # True so the legacy seed data still fires.
            cfg = row.config or {}
            if bool(cfg.get("default_for_notifications", True)):
                slack.append(row)
        elif row.kind in _ISSUE_TRACKER_KINDS:
            cfg = row.config or {}
            # Workspace can opt OUT per-integration by setting
            # ``default_for_issues=false``; defaults to True for the same
            # backwards-compat reason as Slack above.
            if bool(cfg.get("default_for_issues", True)):
                issue_trackers.append(row)
    return issue_trackers, slack


__all__ = [
    "CategorizedDefect",
    "DefectAutoFiler",
    "DefectCategorizer",
    "LlmDiagnosis",
    "build_llm_diagnoser",
    "severity_for_priority",
]
