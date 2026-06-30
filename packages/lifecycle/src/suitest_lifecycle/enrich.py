"""LLM enrichment — additive edge-case proposals on top of the deterministic plan.

ZERO-safe and additive: with no enrichment the plan is byte-for-byte the
deterministic baseline. With the built-in deterministic **mock** it gains
edge-case cases (validation / boundary / auth-negative) tagged ``llm``, each
still traceable to a `source_ref`.

LLM providers are configured per-workspace from the web UI (not env). A real
provider bridge that consumes that config lands later; until then enrichment uses
the deterministic mock, so the lifecycle stays stdlib-only and a run never
hard-depends on a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from suitest_lifecycle.models import CodeSummary, Mode, PlanCase, PlanStep, Priority

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config


@dataclass(frozen=True)
class EdgeSuggestion:
    archetype: str
    title: str
    description: str
    category: str
    priority: Priority
    source_ref: str
    steps: list[tuple[str, str]]


class LlmClient(Protocol):
    def propose_edge_cases(
        self, summary: CodeSummary, existing_titles: set[str]
    ) -> list[EdgeSuggestion]: ...


class MockLlmClient:
    """Deterministic stand-in. Same input → same proposals (no randomness)."""

    def propose_edge_cases(
        self, summary: CodeSummary, existing_titles: set[str]
    ) -> list[EdgeSuggestion]:
        out: list[EdgeSuggestion] = []
        if summary.mode is Mode.BACKEND:
            for ep in summary.endpoints:
                if ep.method == "POST" and ":" not in ep.path and ep.path.rstrip("/").split("/")[-1] not in {"login"}:
                    res = [p for p in ep.path.strip("/").split("/") if p and p != "api"][-1]
                    title = f"post_{res}_with_missing_required_field_returns_validation_error"
                    if title in existing_titles:
                        continue
                    out.append(
                        EdgeSuggestion(
                            archetype="validation",
                            title=title,
                            description=f"POST {ep.path} with a missing required field is rejected (4xx).",
                            category=res.title(),
                            priority=Priority.MEDIUM,
                            source_ref=f"{ep.method} {ep.path}",
                            steps=[
                                ("action", "Log in to obtain a token"),
                                ("action", f"Send authenticated POST {ep.path} with an incomplete payload"),
                                ("assertion", "Expect HTTP 400/422 (validation error)"),
                            ],
                        )
                    )
        return out


def resolve_client(config: Config) -> LlmClient | None:
    """None → no enrichment (deterministic baseline); the deterministic mock when
    ``config.enrich`` is set.

    LLM providers are configured per-workspace from the web UI (not env). A real
    provider bridge that consumes that workspace config lands later; until then
    enrichment uses :class:`MockLlmClient` so a run never hard-depends on a key.
    """
    if not config.enrich:
        return None
    return MockLlmClient()


def enrich_plan(
    summary: CodeSummary, cases: list[PlanCase], config: Config, client: LlmClient | None
) -> list[PlanCase]:
    """Return cases plus any LLM-proposed edge cases (tagged ``llm``).

    Idempotent: proposals whose title already exists are skipped, so re-running
    never duplicates. With ``client is None`` the input list is returned unchanged.
    """
    if client is None:
        return cases
    existing = {c.title for c in cases}
    next_n = _max_tc(cases)
    enriched = list(cases)
    for sug in client.propose_edge_cases(summary, existing):
        if sug.title in existing:
            continue
        next_n += 1
        enriched.append(
            PlanCase(
                id=f"TC{next_n:03d}",
                title=sug.title,
                description=sug.description,
                category=sug.category,
                priority=sug.priority,
                source_ref=sug.source_ref,
                steps=[PlanStep(type=t, description=d) for t, d in sug.steps],
                tags=["llm"],
            )
        )
        existing.add(sug.title)
    return enriched


def _max_tc(cases: list[PlanCase]) -> int:
    best = 0
    for c in cases:
        if c.id.startswith("TC") and c.id[2:].isdigit():
            best = max(best, int(c.id[2:]))
    return best


__all__ = ["EdgeSuggestion", "LlmClient", "MockLlmClient", "enrich_plan", "resolve_client"]
