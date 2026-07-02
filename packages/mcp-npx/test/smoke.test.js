#!/usr/bin/env node
/**
 * Package smoke test — proves the published artifact actually boots.
 *
 * Spawns the real bin (exactly what `npx @suitest/mcp` runs), performs a
 * JSON-RPC `initialize` handshake plus `tools/list` over stdio, and asserts
 * the Suitest tool surface is present. No network, no target app: this is a
 * boot-process test, not an e2e run.
 */

"use strict";

const { spawn } = require("node:child_process");
const path = require("node:path");

const BIN = path.resolve(__dirname, "..", "bin", "suitest-mcp.js");
const TIMEOUT_MS = 20000;

const EXPECTED_TOOLS = [
  "run_tests",
  "analyze_project",
  "bootstrap_project",
  "blackbox_discover_app",
  "blackbox_run_playwright_tests",
];

function fail(msg) {
  process.stderr.write(`SMOKE FAIL: ${msg}\n`);
  process.exit(1);
}

const child = spawn(process.execPath, [BIN], {
  stdio: ["pipe", "pipe", "inherit"],
});

const timer = setTimeout(() => {
  child.kill();
  fail(`no response within ${TIMEOUT_MS}ms`);
}, TIMEOUT_MS);

let buffer = "";
const responses = [];

child.stdout.on("data", (chunk) => {
  buffer += chunk.toString();
  let idx;
  while ((idx = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      fail(`non-JSON line on stdout: ${line.slice(0, 120)}`);
      return;
    }
    responses.push(msg);
    onMessage(msg);
  }
});

child.on("exit", (code) => {
  if (responses.length < 2) {
    clearTimeout(timer);
    fail(`server exited early (code ${code}) after ${responses.length} response(s)`);
  }
});

function send(obj) {
  child.stdin.write(JSON.stringify(obj) + "\n");
}

function onMessage(msg) {
  if (msg.id === 1) {
    const info = msg.result && msg.result.serverInfo;
    if (!info || !/suitest/i.test(String(info.name))) {
      clearTimeout(timer);
      child.kill();
      fail(`initialize: unexpected serverInfo: ${JSON.stringify(msg).slice(0, 200)}`);
    }
    send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
    return;
  }
  if (msg.id === 2) {
    clearTimeout(timer);
    const tools = ((msg.result && msg.result.tools) || []).map((t) => t.name);
    const missing = EXPECTED_TOOLS.filter((t) => !tools.includes(t));
    child.kill();
    if (missing.length > 0) {
      fail(`tools/list missing: ${missing.join(", ")} (got ${tools.length} tools)`);
    }
    process.stdout.write(
      `SMOKE OK: initialize + tools/list (${tools.length} tools, ` +
        `incl. ${EXPECTED_TOOLS.length} checked)\n`,
    );
    process.exit(0);
  }
}

send({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "smoke" } },
});
