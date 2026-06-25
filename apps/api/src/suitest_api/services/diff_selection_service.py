"""Diff-selection service — orchestrates parse → LLM select → ZERO fallback (M6-1).

Responsibilities:
  1. Accept a raw unified diff and a suite id.
  2. Call :func:`~suitest_agent.generators.diff_selector.parse_diff` (always —
     pure Python, ZERO-safe).
  3. Load :class:`~suitest_db.models.case.TestCase` rows for the suite and
     project them into :class:`~suitest_agent.generators.diff_selector.CaseSummary`
     objects.
  4. If the deployment tier is CLOUD or LOCAL *and* an active
     :class:`~suitest_db.models.llm_config.LLMConfig` is present, call
     :func:`~suitest_agent.generators.diff_selector.select_relevant_cases` to get
     the LLM-reduced set.
  5. Otherwise (ZERO tier or no LLM configured) return *all* cases in the suite
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
from suitest_agent.providers.litellm_router import get_provider
from suitest_core.capabilities import Tier, TierFlag, resolve_tier, tier_in
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.test_cases import TestCaseRepo

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

        # 1. Parse the diff (ZERO-safe, always run).
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

        # 4. Determine whether LLM is available for this workspace.
        #    Primary signal: an active LLMConfig in the DB (workspace-scoped).
        #    Secondary guard: the deployment tier must be CLOUD or LOCAL — at
        #    ZERO tier there can never be a real LLMConfig, but during tests the
        #    env-tier may be ZERO while a `mock` config is active; we let the
        #    config existence win so tests work without faking the env.
        active_config = await LLMConfigRepo(self._session).get_active(workspace_id)
        current_tier: Tier = resolve_tier()
        env_allows_llm = tier_in(current_tier, TierFlag.CLOUD | TierFlag.LOCAL)

        # Use LLM path when either:
        #   a) an active config exists AND the env tier is non-ZERO, OR
        #   b) an active config with provider="mock" exists (test scenario).
        llm_capable = active_config is not None and (
            env_allows_llm or active_config.provider == "mock"
        )

        if not llm_capable:
            # ZERO tier or no LLM — return full suite immediately.
            return DiffSelectionResult(
                selected_case_ids=all_case_ids,
                rationale="ZERO tier or no LLM configured — returning full suite.",
                all_case_ids=all_case_ids,
                tier_used="fallback_full",
            )

        # active_config is guaranteed non-None here (llm_capable is only True
        # when active_config is not None). Narrow explicitly for mypy strict.
        assert active_config is not None
        base_url_raw = (
            active_config.config_json.get("base_url") if active_config.config_json else None
        )
        base_url = base_url_raw if isinstance(base_url_raw, str) else None

        provider = get_provider(
            active_config.provider,
            api_key=active_config.api_key_encrypted,
            base_url=base_url,
        )

        # 5. LLM selection.
        return await select_relevant_cases(
            changed_files,
            summaries,
            provider,
            model=active_config.model,
        )
