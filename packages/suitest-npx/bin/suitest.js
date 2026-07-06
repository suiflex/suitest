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
`;

function fail(msg) {
  process.stderr.write(msg + "\n");
  process.exit(1);
}

async function main() {
  const cmd = process.argv[2];
  const { values: opts } = parseArgs({
    args: process.argv.slice(3),
    options: {
      port: { type: "string" },
      ide: { type: "string" },
      "base-url": { type: "string" },
      yes: { type: "boolean" },
    },
    strict: true,
  });
  if (opts.port) opts.port = Number(opts.port);
  opts.baseUrl = opts["base-url"];

  switch (cmd) {
    case "onboard":
    case "up":
    case "down":
    case "init":
      fail(`${cmd}: not implemented yet`); // diisi Task 8
      break;
    default:
      fail(USAGE);
  }
}

main().catch((err) => fail(err && err.message ? err.message : String(err)));
