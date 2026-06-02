"""Tests for the eval harness service (M4-8) over the bundled fixtures (M4-8a)."""

from __future__ import annotations

from pathlib import Path

from suitest_api.services.eval_service import run_eval

# apps/api/tests/<this> → repo root is parents[3].
_FIXTURES = Path(__file__).resolve().parents[3] / "eval" / "fixtures"


def test_bundled_fixtures_are_complete() -> None:
    assert len(list((_FIXTURES / "prds").glob("prd-*.md"))) == 20
    assert len(list((_FIXTURES / "openapi").glob("api-*.yaml"))) == 10
    assert len(list((_FIXTURES / "failed_runs").glob("run-*.json"))) == 15


def test_zero_eval_is_green() -> None:
    result = run_eval(_FIXTURES, suite_name="zero-smoke")
    assert result.fixtures_count == 45
    # ZERO-tier eval MUST be fully green (DoD): every deterministic scorer passes.
    assert result.failed == 0
    assert result.passed == 45
