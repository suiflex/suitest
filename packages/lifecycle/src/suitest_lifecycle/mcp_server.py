"""Minimal MCP stdio server exposing the Sutest lifecycle tools.

Speaks newline-delimited JSON-RPC 2.0 (the MCP stdio framing): ``initialize``,
``tools/list``, ``tools/call``. Stdlib-only so it runs anywhere ``python`` does::

    python -m suitest_lifecycle.mcp_server

Every tool takes a single ``config_path`` argument and returns the structured
``{success, summary, data, artifacts, errors}`` envelope as JSON text content.
"""

from __future__ import annotations

import json
import sys
from typing import Callable, TextIO

from suitest_lifecycle.tools import TOOLS

PROTOCOL_VERSION = "2024-11-05"

_TOOL_DESCRIPTIONS = {
    "analyze_project": "Static-analyze the target project; list endpoints (backend) or pages (frontend).",
    "generate_test_cases": "Analyze, build a PRD + test plan, and export runnable test files.",
    "generate_backend_tests": "Generate backend (requests) test files. Errors if config mode != backend.",
    "generate_frontend_tests": "Generate frontend (playwright) test files. Errors if config mode != frontend.",
    "run_backend_tests": "Full backend lifecycle: start, wait ready, run, report. Mode-guarded.",
    "run_frontend_tests": "Full frontend lifecycle: start, wait ready, run, report. Mode-guarded.",
    "run_tests": "Run the full lifecycle for whatever mode the config declares.",
    "sync_tcm": "Report the TCM mirror (case/run counts + file paths).",
    "generate_report": "Re-surface the last run's report artifacts without re-running.",
}


def _tool_schema(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": _TOOL_DESCRIPTIONS.get(name, name),
        "inputSchema": {
            "type": "object",
            "properties": {
                "config_path": {
                    "type": "string",
                    "description": "Path to suitest.config.json",
                    "default": "suitest.config.json",
                }
            },
            "required": ["config_path"],
        },
    }


def _ok(req_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, object]) -> dict[str, object] | None:
    method = message.get("method")
    req_id = message.get("id")
    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "suitest-lifecycle", "version": "0.1.0"},
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "tools/list":
        return _ok(req_id, {"tools": [_tool_schema(n) for n in TOOLS]})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _err(req_id, -32602, "invalid params")
        name = params.get("name")
        args = params.get("arguments") or {}
        tool: Callable[..., dict[str, object]] | None = TOOLS.get(str(name))
        if tool is None:
            return _err(req_id, -32601, f"unknown tool: {name}")
        config_path = str(args.get("config_path", "suitest.config.json")) if isinstance(args, dict) else "suitest.config.json"
        try:
            envelope = tool(config_path)
        except Exception as exc:  # defensive: never crash the server on a tool bug
            envelope = {"success": False, "summary": f"tool crashed: {exc}", "data": {}, "artifacts": [], "errors": [str(exc)]}
        return _ok(
            req_id,
            {
                "content": [{"type": "text", "text": json.dumps(envelope)}],
                "isError": not bool(envelope.get("success")),
            },
        )
    if req_id is not None:
        return _err(req_id, -32601, f"method not found: {method}")
    return None


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
