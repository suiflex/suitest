#!/usr/bin/env node
/**
 * suitest-mcp — run the Suitest MCP server via npx, or install it into an IDE agent.
 *
 * The server itself is `suitest_lifecycle.mcp_server`, a stdlib-only Python
 * module bundled inside this npm package (synced from packages/lifecycle at
 * pack time). The only host requirement is Python >= 3.11 on PATH (or set
 * SUITEST_PYTHON). Frontend test execution provisions Playwright/Chromium on
 * demand inside the target project's environment — nothing global.
 *
 * Usage:
 *   npx @suiflex/suitest-mcp                    # start the stdio MCP server
 *   npx @suiflex/suitest-mcp mcp                # same (explicit subcommand)
 *   npx @suiflex/suitest-mcp init               # zero-config: detect IDE + framework, write config
 *   npx @suiflex/suitest-mcp install            # interactive: pick a client (TTY)
 *   npx @suiflex/suitest-mcp install --client claude-code
 *   npx @suiflex/suitest-mcp login              # save API URL + key once
 *   npx @suiflex/suitest-mcp doctor             # check client config targets
 *   npx @suiflex/suitest-mcp --help
 */

"use strict";

const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const { findPython } = require("../lib/python.js");

const PKG_ROOT = path.resolve(__dirname, "..");
const PYTHON_DIR = path.join(PKG_ROOT, "python");

function printHelp() {
  process.stdout.write(
    [
      "suitest-mcp — Suitest MCP server (stdio) + installer",
      "",
      "Usage:",
      "  npx @suiflex/suitest-mcp                    start the MCP server (default)",
      "  npx @suiflex/suitest-mcp mcp                same, explicit",
      "  npx @suiflex/suitest-mcp init               zero-config onboarding (detect IDE + framework)",
      "  npx @suiflex/suitest-mcp install            interactive picker (TTY)",
      "  npx @suiflex/suitest-mcp install --client <target>",
      "  npx @suiflex/suitest-mcp login              save API URL + key once",
      "  npx @suiflex/suitest-mcp doctor             check client config targets",
      "  npx @suiflex/suitest-mcp --version          bundled server version",
      "",
      "Init flags:    --ide claude-code|cursor|windsurf, --mode local|server,",
      "               --base-url, --api-url, --api-key, --yes",
      "Install flags: --client, --name, --scope global|project, --api-url,",
      "               --api-key, --print, --dry-run, --force",
      "",
      "Requires Python >= 3.11 on PATH (override with SUITEST_PYTHON).",
      "Docs: https://github.com/suiflex/suitest/blob/main/docs/MCP_PLUGINS.md",
      "",
    ].join("\n"),
  );
}

function parseInitFlags(argv) {
  const out = { yes: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--ide":
        out.ide = argv[++i];
        break;
      case "--mode":
        out.mode = argv[++i];
        break;
      case "--base-url":
        out.baseUrl = argv[++i];
        break;
      case "--api-url":
        out.apiUrl = argv[++i];
        break;
      case "--api-key":
        out.apiKey = argv[++i];
        break;
      case "--yes":
      case "-y":
        out.yes = true;
        break;
      default:
        throw new Error(`unknown flag: ${a}`);
    }
  }
  return out;
}

function printVersion() {
  const pkg = JSON.parse(
    fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"),
  );
  process.stdout.write(`${pkg.name} ${pkg.version}\n`);
}

function startServer() {
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

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    return 0;
  }
  if (args.includes("--version") || args.includes("-v")) {
    printVersion();
    return 0;
  }

  const sub = args[0];
  const rest = args.slice(1);

  if (sub === "init") {
    const { runInit } = require("../lib/init.js");
    const flags = parseInitFlags(rest);
    try {
      const r = await runInit({ cwd: process.cwd(), ...flags });
      process.stdout.write(
        `\n✔ Done — ${r.ide}, ${r.mode} mode, ${r.framework} app.\n` +
          `  wrote ${r.mcpConfigPath}\n` +
          `  ${r.configCreated ? "wrote" : "kept existing"} ${r.suitestConfigPath}\n` +
          `Restart your IDE, then tell the agent: "test my app".\n`,
      );
      return 0;
    } catch (err) {
      process.stderr.write(`init failed: ${err.message}\n`);
      return 1;
    }
  }

  if (sub === "install" || sub === "doctor" || sub === "login") {
    const installer = require("../lib/install.js");
    try {
      if (sub === "install") await installer.handleInstall(rest);
      else if (sub === "doctor") installer.handleDoctor(rest);
      else await installer.handleLogin();
      return 0;
    } catch (err) {
      process.stderr.write(`${err.message}\n`);
      return 1;
    }
  }

  if (sub && sub !== "mcp") {
    process.stderr.write(`unknown command: ${sub} (try --help)\n`);
    return 2;
  }

  return startServer();
}

main().then((rc) => {
  if (rc !== undefined) process.exit(rc);
});
