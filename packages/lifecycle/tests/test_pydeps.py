"""Unit tests for on-demand pip provisioning shared by the test runtimes.

Hermetic: no real pip. We assert the argv-selection logic (the money path: venv
vs system, PEP-668 fallback) and that ``ensure`` skips work when the module is
already importable.
"""

from __future__ import annotations

from suitest_lifecycle import pydeps


def test_pip_variants_in_venv_installs_into_venv(monkeypatch) -> None:
    # venv => prefix differs from base_prefix; no --user, no PEP-668 fight.
    monkeypatch.setattr(pydeps.sys, "prefix", "/tmp/venv")
    monkeypatch.setattr(pydeps.sys, "base_prefix", "/usr")
    variants = pydeps.pip_install_variants("playwright")
    assert len(variants) == 1
    assert "--user" not in variants[0]
    assert "--break-system-packages" not in variants[0]
    assert variants[0][-1] == "playwright"


def test_pip_variants_system_has_user_then_break_system(monkeypatch) -> None:
    # Non-venv => --user first, then --break-system-packages for PEP-668.
    monkeypatch.setattr(pydeps.sys, "prefix", "/usr")
    monkeypatch.setattr(pydeps.sys, "base_prefix", "/usr")
    variants = pydeps.pip_install_variants("requests")
    assert len(variants) == 2
    assert "--user" in variants[0] and "--break-system-packages" not in variants[0]
    assert "--user" in variants[1] and "--break-system-packages" in variants[1]


def test_ensure_is_a_noop_when_already_importable(monkeypatch) -> None:
    installs: list[str] = []
    monkeypatch.setattr(pydeps, "install", lambda pkg, *_: installs.append(pkg))
    status = pydeps.ensure("json", "json")
    assert status.ready is True
    assert installs == []  # already importable => never shells out to pip


def test_ensure_without_autoinstall_reports_the_missing_package(monkeypatch) -> None:
    monkeypatch.setattr(pydeps, "importable", lambda _: False)
    status = pydeps.ensure("requests", auto_install=False)
    assert status.ready is False
    assert "requests" in status.detail


def test_ensure_install_failure_names_the_manual_command(monkeypatch) -> None:
    monkeypatch.setattr(pydeps, "importable", lambda _: False)
    monkeypatch.setattr(pydeps, "ensure_pip", lambda: None)
    monkeypatch.setattr(pydeps, "pip_install_variants", lambda _: [])
    status = pydeps.ensure("requests")
    assert status.ready is False
    assert "-m pip install requests" in status.detail


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
