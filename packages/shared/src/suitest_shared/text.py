"""Text helpers shared across backend packages.

Canonical slug → title derivation for test cases (docs/DATA_MODEL.md §3.4):
``test_cases.title`` is the human-readable display title and ``test_cases.slug``
is the technical key (automation function name, publish match key). Publishers
SHOULD send both; these helpers are the server-side fallback so a payload that
only carries a technical ``name`` still lands with a readable title — the
frontend never has to humanize.
"""

from __future__ import annotations

import re

# Tokens that read better fully upper-cased when they stand alone. Mirrors the
# frontend list in apps/web/src/lib/test-case-format.ts — keep in sync.
_ACRONYMS = frozenset({"api", "url", "id", "ui", "ux", "http", "sql", "ok", "sso", "mcp"})

_SEPARATORS = re.compile(r"[-_]+")
_WHITESPACE = re.compile(r"\s+")


def looks_like_slug(value: str) -> bool:
    """True when ``value`` is a technical key (has ``_``/``-``, no spaces)."""
    v = value.strip()
    if not v or _WHITESPACE.search(v):
        return False
    return "_" in v or "-" in v


def humanize_slug(value: str) -> str:
    """``successful_login_opens_the_dashboard`` → ``Successful login opens the dashboard``.

    Sentence case (only the first word capitalized) — these slugs are full
    sentences, so Title Case would read unnaturally. Known acronyms stay upper.
    """
    words = [w for w in _WHITESPACE.split(_SEPARATORS.sub(" ", value).strip()) if w]
    if not words:
        return value.strip()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if lower in _ACRONYMS:
            out.append(lower.upper())
        elif i == 0:
            out.append(word[:1].upper() + word[1:].lower())
        else:
            out.append(lower)
    return " ".join(out)


def derive_title(name: str) -> str:
    """Display title for a case whose payload carried only a technical name."""
    return humanize_slug(name) if looks_like_slug(name) else name


def derive_slug(name: str) -> str | None:
    """Technical key from a legacy ``name`` — only when it actually is one."""
    return name.strip() if looks_like_slug(name) else None
