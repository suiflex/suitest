"""Review-gate state machine — pure, deterministic, no I/O."""

import pytest
from suitest_shared.domain.automation_review import (
    AutomationReviewError,
    AutomationStatus,
    approve,
    is_runnable,
    normalize,
    on_translated,
    reject,
)


def test_normalize_known_and_unknown_values() -> None:
    assert normalize("draft") is AutomationStatus.DRAFT
    assert normalize("approved") is AutomationStatus.APPROVED
    assert normalize("  APPROVED  ") is AutomationStatus.APPROVED  # trims + lowers
    assert normalize(None) is None
    # Fail-closed: garbage never masquerades as approved.
    assert normalize("running") is None
    assert normalize("") is None


def test_is_runnable_only_when_approved() -> None:
    assert is_runnable("approved") is True
    assert is_runnable("draft") is False
    assert is_runnable(None) is False
    assert is_runnable("bogus") is False  # fail-closed


def test_translate_always_drafts_even_from_approved() -> None:
    # A changed artifact must be re-reviewed — approval never survives a re-translate.
    assert on_translated(None) is AutomationStatus.DRAFT
    assert on_translated("draft") is AutomationStatus.DRAFT
    assert on_translated("approved") is AutomationStatus.DRAFT


def test_approve_draft_then_runnable() -> None:
    assert approve("draft") is AutomationStatus.APPROVED
    assert is_runnable(approve("draft")) is True


def test_approve_is_idempotent() -> None:
    assert approve("approved") is AutomationStatus.APPROVED


def test_approve_nothing_raises() -> None:
    with pytest.raises(AutomationReviewError):
        approve(None)


def test_reject_sends_back_to_draft() -> None:
    assert reject("approved") is AutomationStatus.DRAFT
    assert reject("draft") is AutomationStatus.DRAFT
    assert is_runnable(reject("approved")) is False


def test_reject_nothing_raises() -> None:
    with pytest.raises(AutomationReviewError):
        reject(None)


def test_full_lifecycle() -> None:
    status: str | None = None
    assert is_runnable(status) is False
    status = on_translated(status)  # generate -> draft
    assert status == "draft"
    assert is_runnable(status) is False
    status = approve(status)  # human approves -> approved
    assert is_runnable(status) is True
    status = on_translated(status)  # edited/re-translated -> back to draft
    assert is_runnable(status) is False
