"""Diff-selection service — orchestrates parse → LLM select → full-suite fallback.

Responsibilities:
  1. Accept a raw unified diff and a suite id.
  2. Call :func:`~suitest_agent.generators.diff_selector.parse_diff` (always —
     pure Python).
  3. Load :class:`~suitest_db.models.case.TestCase` rows for the suite and
     project them into :class:`~suitest_agent.generators.diff_selector.CaseSummary`
     objects.
  4. If a validated active :class:`~suitest_db.models.llm_config.LLMConfig` is
     present, call
     :func:`~suitest_agent.generators.diff_selector.select_relevant_cases` to get
     the LLM-reduced set.
  5. Otherwise return *all* cases in the suite
     so CI always has a safe fallback.

This service never persists state — every diff-select is ephemeral.  No audit
log is written because no resource is mutated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_agent.generators.diff_selector import (
    CaseSummary,
    DiffSelectionResult,
    parse_diff,
    select_relevant_cases,
)
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.test_cases import TestCaseRepo

from suitest_api.services.llm_credentials import provider_for_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Maximum unified diff size accepted (bytes / chars).  Checked at the
# router layer; repeated here as a defence-in-depth guard.
MAX_DIFF_CHARS: int = 50_000


class SuiteNotFoundError(Exception):
    """``suite_id`` does not exist in the DB (no cases returned)."""

    def __init__(self, suite_id: str) -> None:
        super().__init__(f"suite {suite_id} not found")
        self.suite_id = suite_id


class DiffTooLargeError(ValueError):
    """``diff_text`` exceeds :data:`MAX_DIFF_CHARS`."""

    def __init__(self, length: int) -> None:
        super().__init__(f"diff_text length {length} exceeds {MAX_DIFF_CHARS}")
        self.length = length


class DiffSelectionService:
    """Stateless orchestrator for diff-based test selection.  One instance per request."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def select(
        self,
        *,
        suite_id: str,
        diff_text: str,
        workspace_id: str,
    ) -> DiffSelectionResult:
        """Run diff-selection for ``suite_id`` using ``diff_text``.

        Raises:
            DiffTooLargeError: when ``diff_text`` exceeds :data:`MAX_DIFF_CHARS`.
            SuiteNotFoundError: when no non-deleted cases are found for ``suite_id``.
        """
        if len(diff_text) > MAX_DIFF_CHARS:
            raise DiffTooLargeError(len(diff_text))

        # 1. Parse the diff (always run).
        changed_files = parse_diff(diff_text)

        # 2. Load all non-deleted cases in the suite (with their steps eager-loaded).
        case_rows = await TestCaseRepo(self._session).list_with_steps_by_suite(suite_id)
        if not case_rows:
            raise SuiteNotFoundError(suite_id)
        all_case_ids = [row.id for row in case_rows]

        # 3. Build CaseSummary projections.
        summaries: list[CaseSummary] = []
        for row in case_rows:
            actions = " ".join(step.action for step in sorted(row.steps, key=lambda s: s.order))
            summaries.append(
                CaseSummary(
                    id=row.id,
                    public_id=row.public_id,
                    name=row.name,
                    step_summary=actions[:200],
                )
            )

        # 4. Use the workspace LLM only after its connection test succeeded.
        active_config = await LLMConfigRepo(self._session).get_active(workspace_id)
        llm_capable = active_config is not None and active_config.last_validated_at is not None

        if not llm_capable:
            return DiffSelectionResult(
                selected_case_ids=all_case_ids,
                rationale="No validated workspace LLM — returning full suite.",
                all_case_ids=all_case_ids,
                selection_mode="fallback_full",
            )

        # active_config is guaranteed non-None here (llm_capable is only True
        # when active_config is not None). Narrow explicitly for mypy strict.
        assert active_config is not None
        provider = await provider_for_config(self._session, active_config)

        # 5. LLM selection.
        return await select_relevant_cases(
            changed_files,
            summaries,
            provider,
            model=active_config.model,
        )
