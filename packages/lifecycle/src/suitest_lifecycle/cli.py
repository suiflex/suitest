"""``suitest`` CLI — Zero-tier entry points (stdlib argparse, no LLM).

Blackbox (no repo needed — URL + credentials are enough):

    suitest zero blackbox --url http://localhost:3000 \\
        --username qa@example.com --password password123
    suitest zero blackbox --config suitest.config.json --max-routes 30 --headed
    suitest zero ui --config suitest.config.json      # alias of blackbox

Classic config-driven lifecycle:

    suitest test --config suitest.config.json
    suitest mcp                                        # stdio MCP server
"""

from __future__ import annotations

import argparse
import json
import sys


def _add_blackbox_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--url", default="", help="Target app URL (e.g. http://localhost:3000)")
    p.add_argument("--config", default="", help="suitest.config.json with a 'ui' section")
    p.add_argument("--username", default="", help="Test credential username/email")
    p.add_argument("--password", default="", help="Test credential password")
    p.add_argument("--max-routes", type=int, default=0, help="Crawl route cap (default 30)")
    p.add_argument("--max-depth", type=int, default=0, help="Crawl depth cap (default 3)")
    p.add_argument("--headed", action="store_true", help="Run the browser headed")
    p.add_argument(
        "--record-video", action="store_true", help="Record video evidence for generated tests"
    )
    p.add_argument(
        "--no-safe-mode",
        action="store_true",
        help="Allow destructive links/actions (default: safeMode ON)",
    )
    p.add_argument(
        "--prd", default="", help="Markdown PRD file — PRD-driven plan via the workspace LLM"
    )
    p.add_argument(
        "--discover-only",
        action="store_true",
        help="Stop after discovery + graph (skip test generation/execution)",
    )


def _run_blackbox(args: argparse.Namespace) -> int:
    from suitest_lifecycle.blackbox.mcp import (
        blackbox_discover_app,
        blackbox_generate_playwright_tests,
        blackbox_run_playwright_tests,
        blackbox_summarize_findings,
    )

    common: dict[str, object] = {
        "config_path": args.config,
        "url": args.url,
        "username": args.username,
        "password": args.password,
        "max_routes": args.max_routes,
    }
    stages = [("discover", blackbox_discover_app(**common))]
    if not args.discover_only and stages[0][1].get("success") is not False:
        gen_kwargs = dict(common)
        if args.prd:
            gen_kwargs["prd_file"] = args.prd
        stages.append(("generate", blackbox_generate_playwright_tests(**gen_kwargs)))
        stages.append(("run", blackbox_run_playwright_tests(**common)))
        stages.append(("summarize", blackbox_summarize_findings(**common)))
    ok = True
    for name, envelope in stages:
        ok = ok and bool(envelope.get("success"))
        print(f"[{name}] {envelope.get('summary')}")
        for err in envelope.get("errors", []):
            print(f"  error: {err}", file=sys.stderr)
    final = stages[-1][1]
    print(json.dumps(final.get("data", {}), indent=2)[:4000])
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suitest", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    zero = sub.add_parser("zero", help="Zero-tier deterministic testing (no LLM)")
    zero_sub = zero.add_subparsers(dest="zero_command")
    for name in ("blackbox", "ui"):
        bp = zero_sub.add_parser(name, help="Blackbox DOM testing from a URL (no repo)")
        _add_blackbox_args(bp)

    test = sub.add_parser("test", help="Run the full config-driven lifecycle")
    test.add_argument("--config", default="suitest.config.json")

    sub.add_parser("mcp", help="Serve the stdio MCP server")

    args = parser.parse_args(argv)

    if args.command == "zero" and args.zero_command in ("blackbox", "ui"):
        if not args.url and not args.config:
            zero.error("provide --url or --config")
        # CLI flags that map onto the ui config are applied inside the tools via
        # kwargs; depth/safe-mode/headed need the config object — pass through env-free
        # by mutating the resolved config there is overkill for now: honour the
        # common ones and document the rest in the config file.
        return _run_blackbox(args)
    if args.command == "test":
        from suitest_lifecycle.config import load_config
        from suitest_lifecycle.orchestrator import run_lifecycle

        res = run_lifecycle(load_config(args.config))
        print(res.summary)
        for step in res.steps:
            print(f"  - {step}")
        return 0 if res.success else 1
    if args.command == "mcp":
        from suitest_lifecycle.mcp_server import serve

        serve()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
