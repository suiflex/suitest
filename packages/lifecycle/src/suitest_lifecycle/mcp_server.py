"""Minimal MCP stdio server exposing the Suitest lifecycle tools.

Speaks newline-delimited JSON-RPC 2.0 (the MCP stdio framing): ``initialize``,
``tools/list``, ``tools/call``. Stdlib-only so it runs anywhere ``python`` does::

    python -m suitest_lifecycle.mcp_server

Every tool takes a single ``config_path`` argument and returns the structured
``{success, summary, data, artifacts, errors}`` envelope as JSON text content.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, TextIO

from suitest_lifecycle.tools import KWARG_TOOLS, TOOLS

if TYPE_CHECKING:
    from collections.abc import Callable

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
    "bootstrap_project": "Open a browser setup wizard (target URL, credentials, crawl scope, optional markdown PRD upload); writes suitest.config.json into the project and returns its path. Call this FIRST when no config exists.",
    "blackbox_discover_app": "Blackbox: open the app URL, detect+perform login, crawl routes, capture evidence, save discovery/graph/report JSON. No repo needed.",
    "blackbox_detect_login": "Blackbox: detect the login form (username/password/submit locators) on the target — heuristics, no data-testid required.",
    "blackbox_perform_login": "Blackbox: detect the login form and actually log in with the given credentials; reports the landing route.",
    "blackbox_crawl_routes": "Blackbox: login + safe BFS crawl; returns the route map (safeMode skips destructive links).",
    "blackbox_analyze_page": "Blackbox: classify one page (login/dashboard/list/form/…); returns its interactive elements + evidence screenshot.",
    "blackbox_build_interaction_graph": "Blackbox: build the serializable interaction graph (page/form/table/modal nodes) from the saved discovery.",
    "blackbox_generate_playwright_tests": "Blackbox: deterministically generate Playwright tests (smoke/auth/navigation/lists/forms) from the saved discovery.",
    "blackbox_run_playwright_tests": "Blackbox: execute the generated tests; per-case outcomes + video/screenshot evidence.",
    "blackbox_collect_evidence": "Blackbox: index all evidence (screenshots, videos, traces, report JSONs).",
    "blackbox_publish_results": "Publish the blackbox suite + latest run (video/screenshot evidence) into the Suitest web TCM. Needs project_id (or publish.projectId in config).",
    "blackbox_summarize_findings": "Blackbox: one JSON summary — route map, bug candidates, test outcomes — for agent reasoning.",
}


_BLACKBOX_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": "Optional suitest.config.json with a 'ui' blackbox section",
        },
        "url": {"type": "string", "description": "Target app URL (overrides config)"},
        "username": {"type": "string", "description": "Test credential username/email"},
        "password": {"type": "string", "description": "Test credential password"},
        "max_routes": {"type": "integer", "description": "Crawl route cap"},
        "page_url": {
            "type": "string",
            "description": "Route or absolute URL (blackbox_analyze_page only)",
        },
        "project_path": {
            "type": "string",
            "description": "Project directory for the setup wizard (bootstrap_project)",
        },
        "timeout_sec": {
            "type": "integer",
            "description": "How long to wait for the user to submit the wizard (bootstrap_project)",
        },
        "project_id": {
            "type": "string",
            "description": "Suitest project id to publish into (blackbox_publish_results)",
        },
        "prd_file": {
            "type": "string",
            "description": "Markdown PRD path — PRD-driven semantic plan via the workspace LLM (blackbox_generate_playwright_tests)",
        },
    },
    "required": [],
}


def _tool_schema(name: str) -> dict[str, object]:
    if name in KWARG_TOOLS:
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BLACKBOX_INPUT_SCHEMA,
        }
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
        arguments = args if isinstance(args, dict) else {}
        try:
            if str(name) in KWARG_TOOLS:
                envelope = tool(**arguments)
            else:
                envelope = tool(str(arguments.get("config_path", "suitest.config.json")))
        except Exception as exc:  # defensive: never crash the server on a tool bug
            envelope = {
                "success": False,
                "summary": f"tool crashed: {exc}",
                "data": {},
                "artifacts": [],
                "errors": [str(exc)],
            }
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
