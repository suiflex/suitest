import io
import json

from suitest_lifecycle.mcp_server import serve


def _run_server(lines: list[dict]) -> list[dict]:
    stdin = io.StringIO("\n".join(json.dumps(m) for m in lines) + "\n")
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    return [json.loads(l) for l in stdout.getvalue().splitlines()]


def test_initialize_and_tools_list(monkeypatch) -> None:
    monkeypatch.setenv("SUITEST_MODE", "local")  # lolos credential gate (plan #1)
    out = _run_server(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    assert out[0]["id"] == 1
    assert out[0]["result"]["protocolVersion"] == "2024-11-05"
    assert any(t["name"] == "generate_test_cases" for t in out[1]["result"]["tools"])


def test_unknown_tool_errors(monkeypatch) -> None:
    monkeypatch.setenv("SUITEST_MODE", "local")
    out = _run_server(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            },
        ]
    )
    assert out[0]["error"]["code"] == -32601


def test_initialize_records_client_sampling_capability(monkeypatch) -> None:
    monkeypatch.setenv("SUITEST_MODE", "local")
    from suitest_lifecycle import mcp_server

    _run_server(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"capabilities": {"sampling": {}}},
            }
        ]
    )
    assert mcp_server.client_supports_sampling() is True

    _run_server([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}])
    assert mcp_server.client_supports_sampling() is False
