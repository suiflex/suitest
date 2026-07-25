"""Load selected cases + their latest-run results/evidence and build a UAT PDF.

Thin IO layer over the pure assembler: repositories fetch cases/suites/steps/tags
and each case's latest-run RunSteps + SCREENSHOT artifacts; artifact bytes become
base64 data-URIs via file_storage. ZERO-tier, deterministic.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import TierFlag
from suitest_db.repositories.runs import RunRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_shared.domain.enums import ArtifactKind, StepOutcome

from suitest_api.deps.tier import require_tier
from suitest_api.services import file_storage
from suitest_api.services.uat_document import (
    CaseInput,
    Locale,
    StepInput,
    UatDocument,
    assemble_document,
)
from suitest_api.services.uat_renderer import render_pdf


class UatExportError(Exception):
    """A selected case does not exist in / belong to the target project/workspace."""


class UatDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._cases = TestCaseRepo(session)
        self._suites = SuiteRepo(session)
        self._runs = RunRepo(session)

    @require_tier(TierFlag.ANY)
    async def build_pdf(
        self,
        *,
        project_id: str,
        workspace_id: str,
        case_ids: list[str],
        title: str,
        locale: Locale,
    ) -> bytes:
        cases = await self._cases.list_active_by_ids(case_ids)
        found = {c.id for c in cases}
        missing = [cid for cid in case_ids if cid not in found]
        if missing:
            raise UatExportError(f"unknown case(s): {missing}")

        by_id = {c.id: c for c in cases}
        inputs: list[CaseInput] = []
        for cid in case_ids:  # preserve caller order
            case = by_id[cid]
            if case.workspace_id != workspace_id:
                raise UatExportError(f"case {cid} outside workspace")
            suite = await self._suites.get_active_by_id(case.suite_id)
            if suite is None or suite.project_id != project_id:
                raise UatExportError(f"case {cid} not in project {project_id}")
            steps = await self._cases.get_steps(case.id)
            tags = await self._cases.get_tags(case.id)
            outcomes, evidence = await self._latest_run(case.last_run_id, case.id)
            inputs.append(
                CaseInput(
                    title=case.title,
                    suite_name=suite.name,
                    modul_fitur=tags[0] if tags else suite.name,
                    steps=[StepInput(order=s.order, action=s.action, expected=s.expected) for s in steps],
                    run_outcomes=outcomes,
                    evidence=evidence,
                )
            )

        doc: UatDocument = assemble_document(
            title=title,
            locale=locale,
            generated_at=datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
            cases=inputs,
        )
        return render_pdf(doc)

    async def _latest_run(
        self, run_id: str | None, case_id: str
    ) -> tuple[list[StepOutcome], list[str]]:
        """Return (this case's ordered run-step outcomes, screenshot data-URIs)."""
        if run_id is None:
            return [], []
        run_steps = [s for s in await self._runs.get_steps(run_id) if s.case_id == case_id]
        run_steps.sort(key=lambda s: s.step_order)
        outcomes = [s.outcome for s in run_steps]
        step_ids = {s.id for s in run_steps}
        # ponytail: loads all artifacts of the run per case; group by run_id if this
        # ever shows up in profiling for large multi-case selections.
        artifacts = [
            a
            for a in await self._runs.get_artifacts(run_id)
            if a.kind == ArtifactKind.SCREENSHOT and a.run_step_id in step_ids
        ]
        evidence: list[str] = []
        for a in artifacts:
            raw = await file_storage.read_bytes(a.url)
            if raw is None:
                continue
            b64 = base64.b64encode(raw).decode("ascii")
            evidence.append(f"data:{a.mime_type};base64,{b64}")
        return outcomes, evidence
