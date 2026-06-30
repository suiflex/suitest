"""``suitest`` CLI (M4-7) — thin argparse front-end over ``suitest-sdk``.

Connection is resolved from env (overridable per-flag):

    SUITEST_API_URL        e.g. https://suitest.example   (default http://localhost:4000)
    SUITEST_TOKEN          bearer token
    SUITEST_WORKSPACE_ID   workspace id (X-Workspace-Id)

Commands::

    suitest run --project <id> --case <id> [--case <id> ...] [--branch main] [--name "smoke"] [--wait]
    suitest cases list [--limit 50]
    suitest mcp ls

Exit code is non-zero on API error so it composes in CI pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:  # the SDK is only needed for run/cases/mcp commands, not the lifecycle ones
    from suitest_sdk import SuitestAPIError
except ImportError:  # pragma: no cover - SDK optional for lifecycle-only usage

    class SuitestAPIError(Exception):  # type: ignore[no-redef]
        """Fallback when suitest-sdk is not installed."""


def _client(args: argparse.Namespace) -> object:
    from suitest_sdk import SuitestClient

    base = args.api_url or os.environ.get("SUITEST_API_URL", "http://localhost:4000")
    token = args.token or os.environ.get("SUITEST_TOKEN")
    workspace = args.workspace or os.environ.get("SUITEST_WORKSPACE_ID")
    return SuitestClient(base, token=token, workspace_id=workspace)


def _cmd_run(args: argparse.Namespace) -> int:
    with _client(args) as client:
        run = client.create_run_selection(
            project_id=args.project,
            name=args.name or args.suite or "cli run",
            case_ids=args.case,
            branch=args.branch,
        )
        run_id = str(run.get("id", ""))
        print(f"run queued: {run_id} ({run.get('status', '?')})")
        if args.wait and run_id:
            final = client.wait_for_run(run_id)
            print(f"run finished: {final.get('status', '?')}")
            return 0 if str(final.get("status", "")).upper() == "PASSED" else 2
    return 0


def _cmd_cases_list(args: argparse.Namespace) -> int:
    with _client(args) as client:
        cases = client.list_cases(limit=args.limit)
    if args.json:
        print(json.dumps(cases, indent=2))
    else:
        for c in cases:
            print(f"{c.get('publicId', c.get('id', '?')):<12} {c.get('name', '')}")
    return 0


def _cmd_mcp_ls(args: argparse.Namespace) -> int:
    with _client(args) as client:
        providers = client.list_mcp_providers()
    if args.json:
        print(json.dumps(providers, indent=2))
    else:
        for p in providers:
            status = p.get("status", p.get("health", "?"))
            print(f"{p.get('name', '?'):<24} {status}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    """analyze → PRD → plan → export runnable test files (no execution)."""
    from suitest_lifecycle.config import load_config
    from suitest_lifecycle.orchestrator import generate_only

    config = load_config(args.config)
    summary, cases, paths = generate_only(config)
    print(f"analyzed {config.mode.value}: {len(summary.endpoints)} endpoint(s), {len(summary.pages)} page(s)")
    print(f"generated {len(cases)} test case(s) -> {paths.mode_dir}")
    for c in cases:
        print(f"  {c.id}  {c.title}")
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    """Full lifecycle: analyze → generate → start → wait ready → run → report."""
    from suitest_lifecycle.config import load_config
    from suitest_lifecycle.orchestrator import run_lifecycle

    config = load_config(args.config)
    if args.no_autostart:
        config.server.autostart = False
    if args.publish:
        config.publish.enabled = True
    if args.enrich:
        config.enrich = True
    result = run_lifecycle(config)
    if args.json:
        from suitest_lifecycle.serialize import summary_to_json

        payload = {
            "success": result.success,
            "summary": result.summary,
            "steps": result.steps,
            "errors": result.errors,
            "data": summary_to_json(result.run) if result.run else None,
            "artifacts": result.artifacts,
        }
        print(json.dumps(payload, indent=2))
    else:
        for step in result.steps:
            print(f"· {step}")
        print(result.summary)
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        print(f"artifacts: {len(result.artifacts)} file(s)")
    return 0 if result.success else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="suitest", description="Suitest CLI")
    parser.add_argument("--api-url", default=None, help="API base URL (or SUITEST_API_URL).")
    parser.add_argument("--token", default=None, help="Bearer token (or SUITEST_TOKEN).")
    parser.add_argument("--workspace", default=None, help="Workspace id (or SUITEST_WORKSPACE_ID).")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Trigger a run for a case selection.")
    run.add_argument("--project", required=True, help="Project id.")
    run.add_argument("--case", action="append", required=True, help="Case id (repeatable).")
    run.add_argument("--branch", default=None)
    run.add_argument("--suite", default=None, help="Suite name (used as the run name).")
    run.add_argument("--name", default=None, help="Run name.")
    run.add_argument("--wait", action="store_true", help="Block until the run finishes.")
    run.set_defaults(func=_cmd_run)

    cases = sub.add_parser("cases", help="Test-case commands.")
    cases_sub = cases.add_subparsers(dest="cases_command", required=True)
    cases_list = cases_sub.add_parser("list", help="List test cases.")
    cases_list.add_argument("--limit", type=int, default=50)
    cases_list.add_argument("--json", action="store_true")
    cases_list.set_defaults(func=_cmd_cases_list)

    mcp = sub.add_parser("mcp", help="MCP provider commands.")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_ls = mcp_sub.add_parser("ls", help="List MCP providers.")
    mcp_ls.add_argument("--json", action="store_true")
    mcp_ls.set_defaults(func=_cmd_mcp_ls)

    gen = sub.add_parser("generate", help="Analyze + generate test cases (no run).")
    gen.add_argument("--config", default="suitest.config.json", help="Path to suitest.config.json.")
    gen.set_defaults(func=_cmd_generate)

    test = sub.add_parser("test", help="Full lifecycle: generate, start, wait, run, report.")
    test.add_argument("--config", default="suitest.config.json", help="Path to suitest.config.json.")
    test.add_argument("--json", action="store_true", help="Emit a structured JSON result.")
    test.add_argument(
        "--no-autostart", action="store_true", help="Don't spawn the target; only wait for readiness."
    )
    test.add_argument(
        "--publish", action="store_true", help="Publish results into a running Suitest (REST ingest)."
    )
    test.add_argument(
        "--enrich", action="store_true", help="Add LLM edge-case enrichment (deterministic mock)."
    )
    test.set_defaults(func=_cmd_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except SuitestAPIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:  # ConfigError (ValueError), missing files
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
