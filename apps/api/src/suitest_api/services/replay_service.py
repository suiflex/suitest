"""Time-travel replay state-delta computation (M5-1).

Pure, deterministic, ZERO-tier: given the per-step ``state_snapshot`` dicts the
runner captured (normalized MCP output), compute the key-level delta between
consecutive steps so the replay UI can render a diff viewer ("what changed at
this step"). No LLM, no DB — the router loads the steps and feeds their snapshots
through :func:`compute_state_delta`.

Snapshots are flattened to dotted paths (``a.b.c``) so nested objects diff at a
stable granularity; list values are compared by their JSON encoding (a list edit
shows up as a single changed path rather than noisy positional churn).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# A delta op: a key was added, removed, or its value changed between two steps.
DeltaOp = str  # "added" | "removed" | "changed"


@dataclass(frozen=True)
class StateChange:
    """One key-level change between the previous and current step snapshot."""

    path: str
    op: DeltaOp
    before: str | None
    after: str | None


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Flatten a snapshot into ``{dotted_path: json_scalar}``.

    Nested dicts recurse; everything else (scalars, lists) is JSON-encoded at its
    path so two snapshots compare by stable string values.
    """
    out: dict[str, str] = {}
    if isinstance(value, dict):
        if not value:
            out[prefix or "."] = "{}"
            return out
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(child, child_prefix))
        return out
    out[prefix or "."] = json.dumps(value, sort_keys=True, default=str)
    return out


def compute_state_delta(
    previous: dict[str, Any] | None, current: dict[str, Any] | None
) -> list[StateChange]:
    """Return the sorted key-level delta from ``previous`` to ``current``.

    ``None`` snapshots are treated as empty. The result is deterministic
    (sorted by path) so the same run always renders an identical diff.
    """
    prev_flat = _flatten(previous) if previous else {}
    cur_flat = _flatten(current) if current else {}
    changes: list[StateChange] = []
    for path in sorted(set(prev_flat) | set(cur_flat)):
        before = prev_flat.get(path)
        after = cur_flat.get(path)
        if before == after:
            continue
        if before is None:
            changes.append(StateChange(path=path, op="added", before=None, after=after))
        elif after is None:
            changes.append(StateChange(path=path, op="removed", before=before, after=None))
        else:
            changes.append(StateChange(path=path, op="changed", before=before, after=after))
    return changes
