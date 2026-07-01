"""Deterministic review-gate state machine for generated automation code.

Phase 2b. Suitest's edge over flaky "translate a step with an LLM at run time"
is that generated/translated automation is **pinned and human-reviewed** before
the deterministic runner will execute it:

    (no automation) --translate--> draft --approve--> approved
                                     ^                    |
                                     +----re-translate----+   (any edit re-drafts)
                                     +----reject----------+

Rules enforced here (pure, no I/O — safe to unit-test and to call from the API
service AND the runner):

* Generating or (re)translating automation code ALWAYS lands in ``draft`` —
  even if the case was previously ``approved`` — because the reviewed artifact
  changed and must be re-reviewed. This is what keeps runs deterministic.
* Only ``draft`` may be approved (approving ``approved`` is a no-op; approving
  ``None`` is an error — there is nothing to approve).
* The runner MUST gate on :func:`is_runnable` — automation runs ONLY when
  ``approved``. ``draft``/``None`` are never auto-run.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AutomationReviewError",
    "AutomationStatus",
    "approve",
    "is_runnable",
    "normalize",
    "on_translated",
    "reject",
]


class AutomationStatus(StrEnum):
    """Review state of a test case's ``automation_code``.

    ``None`` (absent) is the implicit "no automation yet" state and is handled
    at the call sites — it is intentionally NOT a member here.
    """

    DRAFT = "draft"
    APPROVED = "approved"


class AutomationReviewError(ValueError):
    """Raised on an illegal review transition (e.g. approving nothing)."""


def normalize(status: str | None) -> AutomationStatus | None:
    """Coerce a stored string into :class:`AutomationStatus` (or ``None``).

    Unknown/blank values normalize to ``None`` so a corrupt column can never be
    mistaken for ``approved`` (fail-closed).
    """
    if status is None:
        return None
    value = status.strip().lower()
    if value in (AutomationStatus.DRAFT, AutomationStatus.APPROVED):
        return AutomationStatus(value)
    return None


def is_runnable(status: str | None) -> bool:
    """True only when the deterministic runner may execute the pinned code."""
    return normalize(status) is AutomationStatus.APPROVED


def on_translated(_previous: str | None = None) -> AutomationStatus:
    """State after (re)generating/translating code — always back to ``draft``.

    Takes the previous status only for symmetry/readability at call sites; the
    result is unconditional because a changed artifact must be re-reviewed.
    """
    return AutomationStatus.DRAFT


def approve(previous: str | None) -> AutomationStatus:
    """Approve pinned draft code. Idempotent for already-approved cases.

    Raises :class:`AutomationReviewError` when there is nothing to approve
    (``previous`` is ``None`` — no automation exists).
    """
    current = normalize(previous)
    if current is None:
        raise AutomationReviewError("cannot approve a case with no automation code")
    return AutomationStatus.APPROVED


def reject(previous: str | None) -> AutomationStatus:
    """Send approved/draft code back to ``draft`` for re-work.

    Raises :class:`AutomationReviewError` when there is nothing to reject.
    """
    current = normalize(previous)
    if current is None:
        raise AutomationReviewError("cannot reject a case with no automation code")
    return AutomationStatus.DRAFT
