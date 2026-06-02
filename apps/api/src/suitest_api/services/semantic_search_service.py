"""SemanticSearchService — embedding-ranked test-case search (M4-2).

Embeds the query + candidate case texts with the configured local
:class:`~suitest_core.embeddings.Embedder` (fastembed in ``ZERO + fastembed``,
deterministic mock in tests) and ranks by cosine similarity. When no embedder is
configured (``SUITEST_EMBEDDINGS`` unset) it degrades to a lexical substring
score so ZERO-tier search still returns results — just without semantic recall.

Embedding on demand (rather than a persisted pgvector column) keeps M4-2 free of
a schema migration + backfill; persisting vectors for large suites is a v1.x
optimisation tracked separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from suitest_core.embeddings import Embedder, cosine_similarity


@dataclass(frozen=True)
class SearchHit:
    """One ranked candidate: case id, display name, and 0..1 relevance score."""

    case_id: str
    name: str
    score: float


@dataclass(frozen=True)
class Candidate:
    """A searchable test case projected to its embeddable text."""

    case_id: str
    name: str
    text: str


class SemanticSearchService:
    """Rank test-case candidates against a query, semantically or lexically."""

    def __init__(self, embedder: Embedder | None) -> None:
        self._embedder = embedder

    @property
    def mode(self) -> str:
        return "semantic" if self._embedder is not None else "lexical"

    def rank(self, query: str, candidates: list[Candidate], *, top_k: int = 10) -> list[SearchHit]:
        """Return up to ``top_k`` hits ordered by descending relevance."""
        query = query.strip()
        if not query or not candidates:
            return []
        scored = (
            self._rank_semantic(query, candidates)
            if self._embedder is not None
            else self._rank_lexical(query, candidates)
        )
        scored.sort(key=lambda h: h.score, reverse=True)
        return [h for h in scored if h.score > 0.0][:top_k]

    def _rank_semantic(self, query: str, candidates: list[Candidate]) -> list[SearchHit]:
        embedder = self._embedder
        assert embedder is not None
        vectors = embedder.embed([query, *[c.text for c in candidates]])
        query_vec = vectors[0]
        return [
            SearchHit(c.case_id, c.name, cosine_similarity(query_vec, vec))
            for c, vec in zip(candidates, vectors[1:], strict=True)
        ]

    def _rank_lexical(self, query: str, candidates: list[Candidate]) -> list[SearchHit]:
        terms = {t for t in query.lower().split() if t}
        hits: list[SearchHit] = []
        for c in candidates:
            haystack = c.text.lower()
            matched = sum(1 for t in terms if t in haystack)
            score = matched / len(terms) if terms else 0.0
            hits.append(SearchHit(c.case_id, c.name, score))
        return hits
