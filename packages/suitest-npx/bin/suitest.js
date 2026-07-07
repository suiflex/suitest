#!/usr/bin/env node
"use strict";

const { parseArgs } = require("node:util");

const USAGE = `Usage: suitest <command> [options]

Commands:
  onboard   provision runtime + boot local stack + wire IDE MCP config
  up        boot local stack (API + supervisor + dashboard)
  down      stop local stack
  status    is the local stack running? (URL, version, health)
  upgrade   check for a newer version and how to switch to it
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

// Passive update nudge after successful commands; silent offline, cached 24h.
async function printUpdateNotice() {
  const { checkForUpdate, updateNotice } = require("../lib/update-check.js");
  const latest = await checkForUpdate();
  if (latest) console.log(updateNotice(latest));
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
      await printUpdateNotice();
      break;
    }
    case "up": {
      const { prepare } = require("../lib/onboard.js");
      const { up } = require("../lib/stack.js");
      const { webDist, python } = await prepare(cwd);
      await up(cwd, { webDist, python, port: opts.port });
      await printUpdateNotice();
      break;
    }
    case "down": {
      const { down } = require("../lib/stack.js");
      down(cwd);
      break;
    }
    case "status": {
      const { status } = require("../lib/stack.js");
      const s = await status(cwd);
      const line = {
        "not-onboarded": 'Not set up here — run "suitest onboard" in your project folder.',
        stopped: 'Stopped — run "suitest up" to start.',
        stale: `Not responding (was ${s.url}) — run "suitest down" then "suitest up".`,
        running: `Running: ${s.url} (version ${s.version || "unknown"})`,
      }[s.state];
      console.log(line);
      await printUpdateNotice();
      break;
    }
    case "upgrade": {
      const { fetchLatest, isNewer, updateNotice } = require("../lib/update-check.js");
      const current = require("../package.json").version;
      let latest;
      try {
        latest = await fetchLatest(5000);
      } catch (err) {
        fail(`Could not reach the npm registry (${err.message}) — are you online?`);
      }
      if (!isNewer(latest, current)) {
        console.log(`Already on the latest version (${current}).`);
        break;
      }
      // npx pins the version per invocation — "upgrading" = stop the old
      // server so the next @latest invocation actually takes over.
      const { down } = require("../lib/stack.js");
      down(cwd);
      console.log(updateNotice(latest));
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
