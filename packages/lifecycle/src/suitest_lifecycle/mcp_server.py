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
    "blackbox_handle_gateway": "Blackbox: handle post-login intermediate gateway (role/tenant selection, terms dialog, OTP prompt).",
    "edit_test_case_inputs": "Inspect or update test case step input values, multiple file upload paths, and {{variable}} bindings programmatically.",
    "manage_test_case_dataset": "Inspect, define, or rename columns/rows of Data-Driven Testing (DDT) scenario matrices on a test case.",
    "get_workspace_variables": "List available workspace and suite variables for parameterization (secrets masked).",
    "set_workspace_variable": "Create or update a workspace variable with optional AES-GCM secret encryption.",
    "list_suites": "TCM: List test suites in a project (needs project_id).",
    "list_test_cases": "TCM: List test cases in a project or suite.",
    "get_test_case": "TCM: Retrieve complete details and executable steps for a test case by case_id.",
    "create_test_case": "TCM: Create a new test case with executable steps, generating a local Playwright script mirror and syncing to TCM.",
    "run_test_case": "TCM: Trigger an immediate ad-hoc test run for a test case by case_id.",
    "suitest_browser_open": (
        "Interactive: open a new stateful browser session. "
        "Important: Perform a pre-flight check for target credentials before opening to avoid Inactivity TTL Reaper timeout."
    ),
    "suitest_browser_navigate": "Interactive: navigate to URL in active browser session.",
    "suitest_browser_click": "Interactive: click element matching selector in active session.",
    "suitest_browser_type": "Interactive: type/fill text into input element in active session.",
    "suitest_browser_select": "Interactive: select option in select dropdown in active session.",
    "suitest_browser_solve_captcha": "Interactive: solve CAPTCHA image and fill input in active session.",
    "suitest_browser_snapshot": "Interactive: capture structured DOM elements and screenshot of active session.",
    "suitest_browser_close": "Interactive: close active browser session and optionally export action history as case.",
    "suitest_create_dummy_file": "Generate a physically valid dummy test fixture file (PDF, ZIP, SHP, Image, GeoJSON) on disk.",
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
        "storage_state_path": {
            "type": "string",
            "description": "Path to storage_state.json to reuse existing session and bypass login/captcha",
        },
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


_EDIT_INPUTS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": "Path to suitest.config.json",
            "default": "suitest.config.json",
        },
        "case_id": {
            "type": "string",
            "description": "Test case ID (e.g. TC001, title, or filename) to inspect or modify",
        },
        "action": {
            "type": "string",
            "description": "'get' to inspect inputs, 'update' to modify input values or file paths",
            "enum": ["get", "update"],
            "default": "get",
        },
        "updates": {
            "type": "array",
            "description": "List of update directives when action='update'",
            "items": {
                "type": "object",
                "properties": {
                    "step_order": {
                        "type": "integer",
                        "description": "1-based step index to modify",
                    },
                    "selector": {
                        "type": "string",
                        "description": "Target element selector if matching by locator",
                    },
                    "input_value": {
                        "type": "string",
                        "description": "New text value or {{variable}} binding",
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of local file paths for file upload steps",
                    },
                },
            },
        },
    },
    "required": [],
}


_DATASET_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "config_path": {
            "type": "string",
            "description": "Path to suitest.config.json",
            "default": "suitest.config.json",
        },
        "case_id": {
            "type": "string",
            "description": "Test case ID (e.g. TC001 or case public ID)",
        },
        "action": {
            "type": "string",
            "description": "'get', 'set', or 'rename_column'",
            "enum": ["get", "set", "rename_column"],
            "default": "get",
        },
        "schema": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of variable column names",
        },
        "rows": {
            "type": "array",
            "description": "List of scenario row objects with values dict",
        },
        "old_column": {
            "type": "string",
            "description": "Current column name when renaming",
        },
        "new_column": {
            "type": "string",
            "description": "New column name when renaming",
        },
    },
    "required": [],
}


_GATEWAY_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "gateway_type": {
            "type": "string",
            "enum": ["role_or_tenant", "terms_dialog", "otp_prompt", "custom_button"],
            "description": "Tipe interaksi gerbang pasca-login",
            "default": "role_or_tenant",
        },
        "action_trigger": {
            "type": "string",
            "description": "Selector Playwright untuk tombol/link pemicu (contoh: button[data-code='3100'])",
        },
        "target_value": {
            "type": "string",
            "description": "Nilai input opsional (misal kode tenant atau teks konfirmasi)",
        },
        "config_path": {"type": "string", "default": "suitest.config.json"},
        "url": {"type": "string", "description": "Target app URL (overrides config)"},
        "storage_state_path": {"type": "string", "description": "Path to storage_state.json"},
    },
    "required": ["action_trigger"],
}


_GET_VARS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "workspace_id": {
            "type": "string",
            "description": "Target workspace ID (defaults to current)",
        },
        "config_path": {
            "type": "string",
            "description": "Path to suitest.config.json",
        },
    },
    "required": [],
}


_SET_VAR_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "Variable key (e.g. admin_password or api_url)",
        },
        "value": {
            "type": "string",
            "description": "Plaintext or secret value to store",
        },
        "is_secret": {
            "type": "boolean",
            "description": "True to encrypt with AES-GCM and mask in UI",
            "default": False,
        },
        "description": {
            "type": "string",
            "description": "Optional human description",
        },
        "workspace_id": {
            "type": "string",
            "description": "Target workspace ID (defaults to current)",
        },
        "config_path": {
            "type": "string",
            "description": "Path to suitest.config.json",
        },
    },
    "required": ["key", "value"],
}

_CREATE_CASE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "suite_id": {
            "type": "string",
            "description": "Target suite ID in TCM (optional; auto-resolved if omitted)",
        },
        "name": {"type": "string", "description": "Test case title / name (required)"},
        "project_id": {"type": "string", "description": "Optional target project ID in TCM"},
        "target_url": {
            "type": "string",
            "description": "Optional target URL to derive project/suite",
        },
        "description": {"type": "string", "description": "Optional human description"},
        "preconditions": {
            "type": "string",
            "description": "Optional prerequisites (e.g. VPN or credentials)",
        },
        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "default": "P2"},
        "steps": {
            "type": "array",
            "description": "List of step objects: {action, expected, code, mcp_provider, target_kind}",
            "items": {"type": "object"},
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "output_dir": {
            "type": "string",
            "description": "Local directory for Playwright test script mirror",
        },
        "config_path": {"type": "string", "description": "Path to suitest.config.json"},
    },
    "required": ["name"],
}

_RUN_CASE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "case_id": {
            "type": "string",
            "description": "Test case ID or public ID to run (e.g. TC-6017)",
        },
        "config_path": {"type": "string", "description": "Path to suitest.config.json"},
    },
    "required": ["case_id"],
}

_GET_CASE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "case_id": {"type": "string", "description": "Test case ID or public ID (e.g. TC-6017)"},
        "config_path": {"type": "string", "description": "Path to suitest.config.json"},
    },
    "required": ["case_id"],
}

_LIST_CASES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "Optional project ID to filter"},
        "suite_id": {"type": "string", "description": "Optional suite ID to filter"},
        "config_path": {"type": "string", "description": "Path to suitest.config.json"},
    },
    "required": [],
}

_LIST_SUITES_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "Target project ID in TCM (required)"},
        "config_path": {"type": "string", "description": "Path to suitest.config.json"},
    },
    "required": ["project_id"],
}

_BROWSER_OPEN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "headless": {
            "type": "boolean",
            "default": True,
            "description": "Run Chromium in headless mode",
        },
        "viewport": {"type": "object", "description": "Viewport dimensions {width, height}"},
        "storage_state_path": {
            "type": "string",
            "description": "Optional path to storage_state.json",
        },
        "require_auth": {
            "type": "boolean",
            "default": False,
            "description": "Enforce pre-flight check for target credentials before opening session",
        },
        "credentials": {
            "type": "object",
            "description": "Optional dictionary with target username and password",
        },
    },
    "required": [],
}

_BROWSER_NAVIGATE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "url": {"type": "string", "description": "Target URL to navigate to"},
        "wait_strategy": {
            "type": "string",
            "enum": ["domcontentloaded", "commit", "networkidle", "load"],
            "default": "domcontentloaded",
        },
    },
    "required": ["session_id", "url"],
}

_BROWSER_CLICK_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "target": {"type": "string", "description": "Playwright selector for the target element"},
        "timeout_ms": {"type": "integer", "default": 10000},
    },
    "required": ["session_id", "target"],
}

_BROWSER_TYPE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "target": {"type": "string", "description": "Playwright selector for the input element"},
        "text": {"type": "string", "description": "Text to fill into the input"},
        "timeout_ms": {"type": "integer", "default": 10000},
    },
    "required": ["session_id", "target", "text"],
}

_BROWSER_SELECT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "target": {"type": "string", "description": "Playwright selector for the select element"},
        "value": {"type": "string", "description": "Value of the option to select"},
        "timeout_ms": {"type": "integer", "default": 10000},
    },
    "required": ["session_id", "target", "value"],
}

_BROWSER_CAPTCHA_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "image_target": {
            "type": "string",
            "default": "#img-captcha",
            "description": "Selector for the CAPTCHA image/canvas",
        },
        "input_target": {
            "type": "string",
            "default": "#captcha",
            "description": "Selector for the CAPTCHA input field to fill",
        },
    },
    "required": ["session_id"],
}

_BROWSER_SNAPSHOT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "include_screenshot": {
            "type": "boolean",
            "default": True,
            "description": "Include base64 PNG screenshot",
        },
    },
    "required": ["session_id"],
}

_BROWSER_CLOSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string", "description": "Active session ID"},
        "save_as_case": {
            "type": "boolean",
            "default": False,
            "description": "Save action history as a structured TCM test case JSON file on disk",
        },
        "auto_publish": {
            "type": "boolean",
            "default": False,
            "description": "Automatically publish recorded steps to Suitest TCM web platform",
        },
        "case_name": {
            "type": "string",
            "description": "Optional custom name for published test case",
        },
        "target_url": {
            "type": "string",
            "description": "Optional target URL to resolve project and suite during auto-publish",
        },
        "project_id": {
            "type": "string",
            "description": "Optional target project ID in TCM",
        },
        "suite_id": {
            "type": "string",
            "description": "Optional target suite ID in TCM",
        },
        "output_dir": {"type": "string", "default": "suitest-output/cases"},
    },
    "required": ["session_id"],
}


_DUMMY_FILE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["pdf", "zip", "shp", "image", "png", "jpg", "jpeg", "geojson"],
            "default": "pdf",
            "description": "File format type",
        },
        "size_kb": {
            "type": "integer",
            "default": 1024,
            "maximum": 51200,
            "description": "Target size in KB",
        },
        "filename": {"type": "string", "description": "Target filename e.g. proposal_teknis.pdf"},
        "output_dir": {
            "type": "string",
            "default": "suitest-output/fixtures/",
            "description": "Output directory",
        },
        "metadata": {"type": "object", "description": "Optional file metadata (title, author)"},
    },
    "required": ["type", "filename"],
}


def _tool_schema(name: str) -> dict[str, object]:
    if name == "suitest_create_dummy_file":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _DUMMY_FILE_SCHEMA,
        }
    if name == "suitest_browser_open":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_OPEN_SCHEMA,
        }
    if name == "suitest_browser_navigate":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_NAVIGATE_SCHEMA,
        }
    if name == "suitest_browser_click":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_CLICK_SCHEMA,
        }
    if name == "suitest_browser_type":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_TYPE_SCHEMA,
        }
    if name == "suitest_browser_select":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_SELECT_SCHEMA,
        }
    if name == "suitest_browser_solve_captcha":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_CAPTCHA_SCHEMA,
        }
    if name == "suitest_browser_snapshot":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_SNAPSHOT_SCHEMA,
        }
    if name == "suitest_browser_close":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _BROWSER_CLOSE_SCHEMA,
        }
    if name == "blackbox_handle_gateway":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _GATEWAY_INPUT_SCHEMA,
        }
    if name == "create_test_case":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _CREATE_CASE_SCHEMA,
        }
    if name == "run_test_case":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _RUN_CASE_SCHEMA,
        }
    if name == "get_test_case":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _GET_CASE_SCHEMA,
        }
    if name == "list_test_cases":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _LIST_CASES_SCHEMA,
        }
    if name == "list_suites":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _LIST_SUITES_SCHEMA,
        }
    if name == "edit_test_case_inputs":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _EDIT_INPUTS_SCHEMA,
        }
    if name == "manage_test_case_dataset":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _DATASET_SCHEMA,
        }
    if name == "get_workspace_variables":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _GET_VARS_SCHEMA,
        }
    if name == "set_workspace_variable":
        return {
            "name": name,
            "description": _TOOL_DESCRIPTIONS.get(name, name),
            "inputSchema": _SET_VAR_SCHEMA,
        }
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
        with urllib.request.urlopen(req, timeout=10):
            pass
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
