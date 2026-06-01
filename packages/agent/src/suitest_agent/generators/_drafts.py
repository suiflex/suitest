"""Shared raw-LLM-cases → :class:`TestCaseDraft` mapping (M3-6/M3-8).

Both the PRD generator and the OpenAPI edge-case enricher ask the model for the
same minimal shape (``{title, priority, steps:[{action, expected}]}``) and map it
to canonical drafts. Steps carry NO executable ``code`` — they are *agentic*
(translated to an MCP call at execution time, M3-10). Unusable cases (no title /
no usable step) are skipped rather than raising.
"""

from __future__ import annotations

from suitest_shared.domain.enums import CaseSource, Priority, TargetKind
from suitest_shared.schemas.generator_input import TestCaseDraft, TestStepDraft


def coerce_priority(value: object) -> Priority:
    """Coerce a raw priority value to a :class:`Priority`; default ``P2``."""
    try:
        return Priority(str(value).strip().upper())
    except ValueError:
        return Priority.P2


def map_raw_cases(
    raws: list[dict[str, object]],
    *,
    target_kind: TargetKind,
    mcp_provider: str,
    strategy: str,
    case_kind: str,
    tags: list[str],
    source: CaseSource = CaseSource.AI,
    max_cases: int = 20,
) -> list[TestCaseDraft]:
    """Map raw LLM case dicts to TestCaseDrafts (agentic steps, ``code=""``)."""
    drafts: list[TestCaseDraft] = []
    for raw in raws[:max_cases]:
        if not isinstance(raw, dict):
            continue
        draft = _to_draft(
            raw,
            target_kind=target_kind,
            mcp_provider=mcp_provider,
            strategy=strategy,
            case_kind=case_kind,
            tags=tags,
            source=source,
        )
        if draft is not None:
            drafts.append(draft)
    return drafts


def _to_draft(
    raw: dict[str, object],
    *,
    target_kind: TargetKind,
    mcp_provider: str,
    strategy: str,
    case_kind: str,
    tags: list[str],
    source: CaseSource,
) -> TestCaseDraft | None:
    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    steps: list[TestStepDraft] = []
    raw_steps = raw.get("steps")
    if isinstance(raw_steps, list):
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            action = str(raw_step.get("action") or "").strip()
            if not action:
                continue
            steps.append(
                TestStepDraft(
                    order=len(steps) + 1,
                    action=action,
                    expected=str(raw_step.get("expected") or "").strip(),
                    code="",
                    mcp_provider=mcp_provider,
                    target_kind=target_kind,
                )
            )
    if not steps:
        return None

    return TestCaseDraft(
        name=title[:255],
        description=str(raw.get("description") or "").strip(),
        priority=coerce_priority(raw.get("priority")),
        source=source,
        target_kind=target_kind,
        tags=tags,
        generated_from={"strategy": strategy, "case_kind": case_kind},
        steps=steps,
    )
