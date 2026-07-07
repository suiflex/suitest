#!/usr/bin/env node
"use strict";

const { parseArgs } = require("node:util");

const USAGE = `Usage: suitest <command> [options]

Commands:
  onboard   provision runtime + boot local stack + wire IDE MCP config
  up        boot local stack (API + supervisor + dashboard)
  down      stop local stack
  init      wire MCP config only (delegates to @suiflex/suitest-mcp)

Options:
  --port <n>       preferred dashboard port (default 4000)
  --ide <id>       claude-code | cursor | windsurf
  --base-url <u>   app-under-test base URL (init/onboard)
  --email <e>      admin account email (onboard, non-interactive)
  --password <p>   admin account password (onboard, non-interactive)
`;

function fail(msg) {
  process.stderr.write(msg + "\n");
  process.exit(1);
}

async function main() {
  // Pre-parse: strict parseArgs would throw on unknown --help/--version (mcp-npx convention).
  const rawArgs = process.argv.slice(2);
  if (rawArgs.includes("--help")) {
    process.stdout.write(USAGE);
    process.exit(0);
  }
  if (rawArgs.includes("--version")) {
    process.stdout.write(require("../package.json").version + "\n");
    process.exit(0);
  }

  const cmd = process.argv[2];
  const { values: opts } = parseArgs({
    args: process.argv.slice(3),
    options: {
      port: { type: "string" },
      ide: { type: "string" },
      "base-url": { type: "string" },
      email: { type: "string" },
      password: { type: "string" },
      yes: { type: "boolean" },
    },
    strict: true,
  });
  if (opts.port) opts.port = Number(opts.port);
  // Note: both opts["base-url"] and opts.baseUrl stay set on opts — handlers should read baseUrl.
  opts.baseUrl = opts["base-url"];

  const cwd = process.cwd();
  switch (cmd) {
    case "onboard": {
      const { onboard } = require("../lib/onboard.js");
      await onboard(cwd, opts);
      break;
    }
    case "up": {
      const { prepare } = require("../lib/onboard.js");
      const { up } = require("../lib/stack.js");
      const { webDist, python } = await prepare(cwd);
      await up(cwd, { webDist, python, port: opts.port });
      break;
    }
    case "down": {
      const { down } = require("../lib/stack.js");
      down(cwd);
      break;
    }
    case "init": {
      const { loadMcpLib } = require("../lib/onboard.js");
      const { runInit } = loadMcpLib("init.js");
      const result = await runInit({
        cwd,
        ide: opts.ide,
        yes: Boolean(opts.yes),
        baseUrl: opts.baseUrl,
      });
      console.log(`MCP config written: ${result.mcpConfigPath}`);
      break;
    }
    default:
      fail(USAGE);
  }
}

main().catch((err) => fail(err && err.message ? err.message : String(err)));
