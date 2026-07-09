"""Unit tests for eval fixtures dir resolution (no DB, no harness).

Regression for the packaged-deploy 400 — uvicorn runs with an arbitrary cwd, so
the old cwd-relative ``eval/fixtures`` default raised "fixtures dir not found".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from suitest_api.routers.eval_runs import _fixtures_dir


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SUITEST_EVAL_FIXTURES_DIR", str(tmp_path))
    assert _fixtures_dir() == tmp_path


def test_resolves_cwd_relative(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SUITEST_EVAL_FIXTURES_DIR", raising=False)
    (tmp_path / "eval" / "fixtures").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert _fixtures_dir() == (tmp_path / "eval" / "fixtures").resolve()


def test_resolves_repo_checkout_when_cwd_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # cwd without eval/fixtures — must still resolve via the walk-up from __file__
    # (this repo checkout ships apps/api under a root that has eval/fixtures).
    monkeypatch.delenv("SUITEST_EVAL_FIXTURES_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    resolved = _fixtures_dir()
    assert resolved.is_dir()
    assert resolved.name == "fixtures"
