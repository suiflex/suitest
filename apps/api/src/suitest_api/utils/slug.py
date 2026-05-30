"""Inline slugifier used by the project create endpoint (M1d-5).

Inlined (no ``python-slugify`` dep) per CLAUDE §2.2 "no new dependencies
without ARCHITECTURE.md update". Handles the ASCII subset only — the project
name field is constrained to 120 chars and the slug column to 64, so we don't
attempt unicode transliteration. Callers should treat the result as a hint:
the service still has to retry on collision (slug uniqueness is workspace-
scoped via :class:`UniqueConstraint`).
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MULTI_HYPHEN = re.compile(r"-{2,}")


def slugify(name: str, *, max_length: int = 64) -> str:
    """Return a kebab-case slug derived from ``name``.

    Rules:

    * Lowercased.
    * Non-alphanumeric runs collapse to a single hyphen.
    * Leading / trailing hyphens stripped.
    * Truncated to ``max_length`` (right-trimmed at a hyphen when possible
      so we never leave a partial token).
    * Empty input (or input that slugifies to ``""``) returns ``"project"``
      as a stable fallback so the create endpoint never sees an empty slug.
    """
    lower = name.strip().lower()
    if not lower:
        return "project"
    hyphenated = _NON_ALNUM.sub("-", lower)
    hyphenated = _MULTI_HYPHEN.sub("-", hyphenated).strip("-")
    if not hyphenated:
        return "project"
    if len(hyphenated) <= max_length:
        return hyphenated
    cut = hyphenated[:max_length]
    # Avoid a dangling token (``-``-terminated): trim back to the last hyphen
    # so the slug ends on a real word boundary.
    if "-" in cut:
        last = cut.rfind("-")
        if last > 0:
            return cut[:last]
    return cut
