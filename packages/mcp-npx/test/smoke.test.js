#!/usr/bin/env node
/**
 * Package smoke test — proves the published artifact actually boots.
 *
 * Spawns the real bin (exactly what `npx @suiflex/suitest-mcp` runs), performs a
 * JSON-RPC `initialize` handshake, the discovery probes used by strict MCP
 * clients (including Codex), and `tools/list` over stdio. No network, no
 * target app: this is a boot-process test, not an e2e run.
 */

"use strict";

const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

const BIN = path.resolve(__dirname, "..", "bin", "suitest-mcp.js");
const TIMEOUT_MS = 20000;
const SMOKE_KEY = "sk_suitest_smoke";

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

// The server refuses to start unless SUITEST_API_URL/KEY verify against
// /api/v1/api-keys/whoami, so the smoke test runs a local stub of it.
const stub = http.createServer((req, res) => {
  const ok =
    req.url === "/api/v1/api-keys/whoami" &&
    req.headers.authorization === `Bearer ${SMOKE_KEY}`;
  res.writeHead(ok ? 200 : 401, { "content-type": "application/json" });
  res.end(ok ? '{"workspaceId":"smoke"}' : '{"detail":"invalid key"}');
});

stub.listen(0, "127.0.0.1", () => {
  boot(`http://127.0.0.1:${stub.address().port}`);
});

function boot(apiUrl) {
  const child = spawn(process.execPath, [BIN], {
    stdio: ["pipe", "pipe", "inherit"],
    env: { ...process.env, SUITEST_API_URL: apiUrl, SUITEST_API_KEY: SMOKE_KEY },
  });

  const timer = setTimeout(() => {
    child.kill();
    fail(`no response within ${TIMEOUT_MS}ms`);
  }, TIMEOUT_MS);

  let buffer = "";
  const responses = [];
  const probes = [
    [2, "ping", null],
    [3, "resources/list", "resources"],
    [4, "resources/templates/list", "resourceTemplates"],
    [5, "prompts/list", "prompts"],
  ];

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
      send({ jsonrpc: "2.0", method: "notifications/initialized" });
      send({ jsonrpc: "2.0", id: probes[0][0], method: probes[0][1] });
      return;
    }
    const probeIndex = probes.findIndex(([id]) => id === msg.id);
    if (probeIndex >= 0) {
      const [, method, emptyKey] = probes[probeIndex];
      if (msg.error || (emptyKey && !Array.isArray(msg.result && msg.result[emptyKey]))) {
        clearTimeout(timer);
        child.kill();
        fail(`${method}: unexpected response: ${JSON.stringify(msg).slice(0, 200)}`);
      }
      const next = probes[probeIndex + 1];
      if (next) send({ jsonrpc: "2.0", id: next[0], method: next[1] });
      else send({ jsonrpc: "2.0", id: 6, method: "tools/list" });
      return;
    }
    if (msg.id === 6) {
      clearTimeout(timer);
      const tools = ((msg.result && msg.result.tools) || []).map((t) => t.name);
      const missing = EXPECTED_TOOLS.filter((t) => !tools.includes(t));
      child.kill();
      if (missing.length > 0) {
        fail(`tools/list missing: ${missing.join(", ")} (got ${tools.length} tools)`);
      }
      process.stdout.write(
        `SMOKE OK: initialize + client probes + tools/list (${tools.length} tools, ` +
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
}
