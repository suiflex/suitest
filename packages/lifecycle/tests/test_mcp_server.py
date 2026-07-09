"""Credential gate: the MCP server must refuse to start without a valid
SUITEST_API_URL + SUITEST_API_KEY pair (the key pins the target workspace)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from types import TracebackType

import pytest
from suitest_lifecycle import mcp_server


def test_serve_refuses_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUITEST_API_URL", raising=False)
    monkeypatch.delenv("SUITEST_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        mcp_server.serve(stdin=io.StringIO(""), stdout=io.StringIO())


def test_serve_refuses_blank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_API_URL", "")
    monkeypatch.setenv("SUITEST_API_KEY", "")
    with pytest.raises(SystemExit):
        mcp_server.serve(stdin=io.StringIO(""), stdout=io.StringIO())


def test_serve_refuses_rejected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_API_URL", "http://localhost:4000")
    monkeypatch.setenv("SUITEST_API_KEY", "sk_suitest_bad")

    def reject(req: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    with pytest.raises(SystemExit):
        mcp_server.serve(stdin=io.StringIO(""), stdout=io.StringIO())


def test_serve_refuses_unreachable_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_API_URL", "http://localhost:9")
    monkeypatch.setenv("SUITEST_API_KEY", "sk_suitest_ok")

    def unreachable(req: urllib.request.Request, timeout: float = 0) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(SystemExit):
        mcp_server.serve(stdin=io.StringIO(""), stdout=io.StringIO())


class _OkResponse:
    def __enter__(self) -> _OkResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


def test_serve_starts_with_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_API_URL", "http://localhost:4000/")
    monkeypatch.setenv("SUITEST_API_KEY", "sk_suitest_ok")
    seen: list[str] = []

    def accept(req: urllib.request.Request, timeout: float = 0) -> _OkResponse:
        seen.append(req.full_url)
        assert req.get_header("Authorization") == "Bearer sk_suitest_ok"
        return _OkResponse()

    monkeypatch.setattr(urllib.request, "urlopen", accept)
    out = io.StringIO()
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
    mcp_server.serve(stdin=io.StringIO(line), stdout=out)
    assert seen == ["http://localhost:4000/api/v1/api-keys/whoami"]
    assert '"protocolVersion"' in out.getvalue()


def test_handle_answers_standard_probes() -> None:
    """Codex + GitHub Copilot CLI probe ping/resources/prompts on connect and
    health-check via ``ping``. Answering these (not -32601) is what keeps those
    clients from marking the server broken — the regression this guards."""
    cases = [
        ("ping", None),
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
        ("prompts/list", "prompts"),
    ]
    for method, empty_key in cases:
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": method})
        assert resp is not None
        assert "error" not in resp, f"{method} returned {resp.get('error')}"
        if empty_key is not None:
            assert resp["result"][empty_key] == []


def test_handle_unknown_method_still_errors() -> None:
    resp = mcp_server.handle({"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"})
    assert resp is not None
    assert resp["error"]["code"] == -32601
