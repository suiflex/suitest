import pytest
from pydantic import ValidationError

from suitest_api.settings import Settings


def test_mode_defaults_to_server(monkeypatch) -> None:
    monkeypatch.delenv("SUITEST_MODE", raising=False)
    assert Settings().mode == "server"


def test_mode_local_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SUITEST_MODE", "local")
    assert Settings().mode == "local"


def test_mode_typo_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SUITEST_MODE", "locaal")
    with pytest.raises(ValidationError):
        Settings()
