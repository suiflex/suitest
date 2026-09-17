"""Minimal MCP stdio server exposing the Suitest lifecycle tools.

Speaks newline-delimited JSON-RPC 2.0 (the MCP stdio framing): ``initialize``,
``tools/list``, ``tools/call``. Stdlib-only so it runs anywhere ``python`` does::

    python -m suitest_lifecycle.mcp_server

Every tool takes a single ``config_path`` argument and returns the structured
``{success, summary, data, artifacts, errors}`` envelope as JSON text content.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, TextIO, cast

from suitest_lifecycle.tools import KWARG_TOOLS, TOOLS

if TYPE_CHECKING:
    from collections.abc import Callable

PROTOCOL_VERSION = "2024-11-05"

_out_stream: TextIO | None = None  # set by serve()


def _write_message(message: dict[str, object]) -> None:
    """Write one JSON-RPC message to the client stream."""
    assert _out_stream is not None
    _out_stream.write(json.dumps(message) + "\n")
    _out_stream.flush()


# Run tools accept the explicit recreate opt-in (goal: recreate NEVER happens
# implicitly — only via this flag or the publish.recreateProject config key).
RECREATE_TOOLS = frozenset({"run_tests", "run_backend_tests", "run_frontend_tests"})

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
    "get_failure_context": (
        "Call this WHENEVER a run reports failing test(s) and you intend to fix "
        "the code. Returns a compact markdown bundle for the last run's failures "
        "(error + failed step + DOM excerpt around the failed selector + "
        "error/warning console + non-2xx network + evidence links), sized to fit "
        "an agent context window (<= 8 KB) so you can diagnose and fix WITHOUT "
        "opening screenshots/videos by hand. No prior run -> error; run with no "
        "failures -> empty context."
    ),
    "whitebox_discover_tests": (
        "White-box: detect pytest or Vitest/Jest targets through the "
        "suitest.whitebox.v1 normalized contract."
    ),
    "whitebox_run_tests": (
        "White-box: run native repository tests, normalize results/coverage into "
        "suitest-output, and publish through the standard lifecycle pipeline."
    ),
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
        "recreate_project": {
            "type": "boolean",
            "description": (
                "EXPLICIT opt-in: recreate the project when the configured/passed "
                "project id no longer exists and repair finds no match "
                "(blackbox_publish_results). Without it a stale binding fails the publish."
            ),
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
    properties: dict[str, object] = {
        "config_path": {
            "type": "string",
            "description": "Path to suitest.config.json",
            "default": "suitest.config.json",
        }
    }
    if name in RECREATE_TOOLS:
        properties["recreate_project"] = {
            "type": "boolean",
            "description": (
                "EXPLICIT opt-in: recreate the project when the configured "
                "publish.projectId no longer exists and repair finds no match. "
                "Without this flag a stale binding FAILS the run (nothing is inserted)."
            ),
            "default": False,
        }
    return {
        "name": name,
        "description": _TOOL_DESCRIPTIONS.get(name, name),
        "inputSchema": {
            "type": "object",
            "properties": properties,
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
                "serverInfo": {"name": "suitest-lifecycle", "version": "0.1.2"},
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "tools/list":
        return _ok(req_id, {"tools": [_tool_schema(n) for n in TOOLS]})
    # Standard utility/discovery methods that strict clients (Codex, GitHub
    # Copilot CLI) send on connect and as health checks. We expose no
    # resources/prompts, but MUST answer these instead of returning -32601:
    # a JSON-RPC error to ``ping`` makes those clients mark the server broken
    # (works in Cursor/Claude Code/Antigravity only because they never ping).
    if method == "ping":
        return _ok(req_id, {})
    if method == "resources/list":
        return _ok(req_id, {"resources": []})
    if method == "resources/templates/list":
        return _ok(req_id, {"resourceTemplates": []})
    if method == "prompts/list":
        return _ok(req_id, {"prompts": []})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _err(req_id, -32602, "invalid params")
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = cast("Callable[..., dict[str, object]] | None", TOOLS.get(str(name)))
        if tool is None:
            return _err(req_id, -32601, f"unknown tool: {name}")
        arguments = args if isinstance(args, dict) else {}
        try:
            if str(name) in KWARG_TOOLS:
                envelope = tool(**arguments)
            elif str(name) in RECREATE_TOOLS:
                envelope = tool(
                    str(arguments.get("config_path", "suitest.config.json")),
                    bool(arguments.get("recreate_project", False)),
                )
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


def verify_credentials() -> str | None:
    """Check SUITEST_API_URL + SUITEST_API_KEY; return an error string if unusable.

    Both must be set, and the key must authenticate against the URL
    (``GET /api/v1/api-keys/whoami`` — the key pins the workspace/project every
    tool publishes into). Any failure must abort the connection: a server that
    accepts empty or mismatched credentials silently drops all publishes.

    The response must also report a validated workspace LLM. MCP execution is
    unavailable until Settings → LLM has completed its connection test.
    """
    api_url = os.environ.get("SUITEST_API_URL", "").strip().rstrip("/")
    api_key = os.environ.get("SUITEST_API_KEY", "").strip()
    if not api_url or not api_key:
        return (
            "SUITEST_API_URL and SUITEST_API_KEY are both required "
            "(set them in the mcpServers env block); refusing to start"
        )
    req = urllib.request.Request(
        f"{api_url}/api/v1/api-keys/whoami",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read())
        llm_status = payload.get("llmStatus") if isinstance(payload, dict) else None
        if llm_status != "ready":
            return (
                f"workspace LLM is {llm_status or 'not_configured'}; connect and validate it "
                f"at {api_url}/settings before starting MCP"
            )
        return None
    except urllib.error.HTTPError as exc:
        return f"SUITEST_API_KEY rejected by {api_url} (HTTP {exc.code}); refusing to start"
    except (urllib.error.URLError, OSError) as exc:
        return f"SUITEST_API_URL {api_url} unreachable ({exc}); refusing to start"


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    global _out_stream
    _out_stream = stdout
    error = verify_credentials()
    if error is not None:
        sys.stderr.write(f"suitest-mcp: {error}\n")
        raise SystemExit(1)

    for line in stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    serve()
