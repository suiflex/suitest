"""Prompt loader + drift guard (M3-5, docs/AI_AGENT.md §6).

A prompt is addressed by ``(name, version)`` and read from
``prompts/{version}/{name}.md``. :func:`prompt_hash` is ``sha256(content)``;
:func:`prompt_id` renders the canonical reproducibility id
``"{version}/{name}@sha256:{hash}"`` persisted on ``AgentSession.prompt_version_id``.

The DB is intentionally NOT imported here (agent package stays storage-agnostic).
Drift is detected by passing the DB-stored hash into :func:`load` as
``stored_hash``; a mismatch raises :class:`PromptDriftError`, forcing a version
bump instead of an in-place edit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_PROMPTS_ROOT = Path(__file__).resolve().parent


class PromptDriftError(RuntimeError):
    """On-disk prompt SHA-256 disagrees with the stored ``prompt_versions.hash``."""


class PromptNotFoundError(FileNotFoundError):
    """No ``{version}/{name}.md`` file exists for the requested prompt."""


def prompt_hash(content: str) -> str:
    """Return ``sha256(content)`` hex digest — the prompt's content address."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def prompt_id(name: str, version: str, content: str) -> str:
    """Render the canonical id ``"{version}/{name}@sha256:{hash}"`` (§6)."""
    return f"{version}/{name}@sha256:{prompt_hash(content)}"


def read_prompt(name: str, version: str = "v1") -> str:
    """Read raw prompt text from disk. Raises :class:`PromptNotFoundError`."""
    path = _PROMPTS_ROOT / version / f"{name}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"No prompt {version}/{name} at {path}")
    return path.read_text(encoding="utf-8")


def list_prompts(version: str = "v1") -> list[str]:
    """Return the sorted base names of every ``{version}/*.md`` default prompt.

    Used by the workspace prompt-fork UI (M5-3) to enumerate which prompts can be
    overridden. Returns an empty list when the version directory does not exist.
    """
    version_dir = _PROMPTS_ROOT / version
    if not version_dir.is_dir():
        return []
    return sorted(p.stem for p in version_dir.glob("*.md"))


def load(name: str, version: str = "v1", *, stored_hash: str | None = None) -> str:
    """Load ``{version}/{name}`` and guard against drift.

    When ``stored_hash`` is provided (from ``prompt_versions.hash``) and differs
    from the on-disk content hash, raise :class:`PromptDriftError`. The message
    instructs bumping the version rather than editing in place.
    """
    content = read_prompt(name, version)
    computed = prompt_hash(content)
    if stored_hash is not None and stored_hash != computed:
        nxt = _bump(version)
        raise PromptDriftError(
            f"Prompt {version}/{name} drifted: disk={computed[:8]}, db={stored_hash[:8]}. "
            f"Bump the version (create {nxt}) instead of editing in place."
        )
    return content


def _bump(version: str) -> str:
    """``v1`` → ``v2``; non-``vN`` versions get a ``-next`` suffix."""
    if version.startswith("v") and version[1:].isdigit():
        return f"v{int(version[1:]) + 1}"
    return f"{version}-next"
