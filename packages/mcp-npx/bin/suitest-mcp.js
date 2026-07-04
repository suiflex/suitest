#!/usr/bin/env node
/**
 * suitest-mcp — run the Suitest MCP server via npx.
 *
 * The server itself is `suitest_lifecycle.mcp_server`, a stdlib-only Python
 * module bundled inside this npm package (synced from packages/lifecycle at
 * pack time). The only host requirement is Python >= 3.11 on PATH (or set
 * SUITEST_PYTHON). Frontend test execution provisions Playwright/Chromium on
 * demand inside the target project's environment — nothing global.
 *
 * Usage:
 *   npx @suiflex/suitest-mcp            # start the stdio MCP server
 *   npx @suiflex/suitest-mcp mcp        # same (explicit subcommand)
 *   npx @suiflex/suitest-mcp --help
 */

"use strict";

const { spawnSync, spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const PKG_ROOT = path.resolve(__dirname, "..");
const PYTHON_DIR = path.join(PKG_ROOT, "python");
const MIN_PY = [3, 11];

function findPython() {
  const candidates = process.env.SUITEST_PYTHON
    ? [process.env.SUITEST_PYTHON]
    : ["python3", "python"];
  for (const cmd of candidates) {
    const probe = spawnSync(cmd, [
      "-c",
      "import sys; print('%d.%d' % sys.version_info[:2])",
    ]);
    if (probe.status !== 0) continue;
    const [maj, min] = String(probe.stdout).trim().split(".").map(Number);
    if (maj > MIN_PY[0] || (maj === MIN_PY[0] && min >= MIN_PY[1])) {
      return { cmd, version: `${maj}.${min}` };
    }
  }
  return null;
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    process.stdout.write(
      [
        "suitest-mcp — Suitest MCP server (stdio)",
        "",
        "Usage:",
        "  npx @suiflex/suitest-mcp            start the MCP server (default)",
        "  npx @suiflex/suitest-mcp mcp        same, explicit",
        "  npx @suiflex/suitest-mcp --version  bundled server version",
        "",
        "Add to your IDE agent (e.g. .mcp.json):",
        "  {",
        '    "mcpServers": {',
        '      "suitest": {',
        '        "command": "npx",',
        '        "args": ["-y", "@suiflex/suitest-mcp"],',
        '        "env": { "SUITEST_API_URL": "...", "SUITEST_API_KEY": "..." }',
        "      }",
        "    }",
        "  }",
        "",
        "Requires Python >= 3.11 on PATH (override with SUITEST_PYTHON).",
        "Docs: https://github.com/suiflex/suitest/blob/main/docs/MCP_PLUGINS.md",
        "",
      ].join("\n"),
    );
    return 0;
  }
  if (args.includes("--version") || args.includes("-v")) {
    const pkg = JSON.parse(
      fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"),
    );
    process.stdout.write(`${pkg.name} ${pkg.version}\n`);
    return 0;
  }
  const sub = args[0];
  if (sub && sub !== "mcp") {
    process.stderr.write(`unknown command: ${sub} (try --help)\n`);
    return 2;
  }
  if (!fs.existsSync(path.join(PYTHON_DIR, "suitest_lifecycle"))) {
    process.stderr.write(
      "bundled python sources missing — this is a packaging bug; " +
        "run `npm run sync-python` in a checkout, or reinstall the package.\n",
    );
    return 1;
  }
  const py = findPython();
  if (!py) {
    process.stderr.write(
      "suitest-mcp needs Python >= 3.11 on PATH (or set SUITEST_PYTHON " +
        "to an interpreter). Install from https://python.org and retry.\n",
    );
    return 1;
  }

  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH
    ? `${PYTHON_DIR}${path.delimiter}${env.PYTHONPATH}`
    : PYTHON_DIR;

  const child = spawn(py.cmd, ["-m", "suitest_lifecycle.mcp_server"], {
    stdio: "inherit",
    env,
  });
  child.on("exit", (code, signal) => {
    process.exit(signal ? 1 : (code ?? 0));
  });
  child.on("error", (err) => {
    process.stderr.write(`failed to start python: ${err.message}\n`);
    process.exit(1);
  });
  return undefined;
}

const rc = main();
if (rc !== undefined) process.exit(rc);
