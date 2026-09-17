"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { runInit } = require("../lib/init.js");

test("init rejects removed local mode", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  fs.writeFileSync(path.join(dir, ".mcp.json"), "{}"); // simulate Claude Code
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({ dependencies: { next: "^15" } }),
  );

  await assert.rejects(
    () => runInit({ cwd: dir, mode: "local", ide: "claude-code", yes: true }),
    /local MCP mode was removed/,
  );
});

test("init preserves an existing mcpServers entry", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  fs.writeFileSync(
    path.join(dir, ".mcp.json"),
    JSON.stringify({
      mcpServers: { playwright: { command: "npx", args: ["-y", "@playwright/mcp"] } },
    }),
  );
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({ devDependencies: { vite: "^6" } }),
  );

  await runInit({
    cwd: dir,
    ide: "claude-code",
    apiUrl: "http://localhost:4000",
    apiKey: "sk_suitest_abc",
    yes: true,
  });

  const mcpCfg = JSON.parse(fs.readFileSync(path.join(dir, ".mcp.json"), "utf8"));
  assert.ok(mcpCfg.mcpServers.playwright, "user's other server was lost");
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_API_KEY, "sk_suitest_abc");
});

test("init server mode requires an API key", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  fs.writeFileSync(path.join(dir, ".mcp.json"), "{}");
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({ dependencies: { next: "^15" } }),
  );

  const result = await runInit({
    cwd: dir,
    mode: "server",
    ide: "claude-code",
    apiUrl: "http://localhost:4000",
    apiKey: "sk_suitest_abc",
    yes: true,
  });

  assert.strictEqual(result.mode, "server");
  const mcpCfg = JSON.parse(fs.readFileSync(path.join(dir, ".mcp.json"), "utf8"));
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_API_KEY, "sk_suitest_abc");
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_MODE, undefined);
});

test("init server mode with --yes but no key errors, never blocks", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  fs.writeFileSync(path.join(dir, ".mcp.json"), "{}");
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({ dependencies: { next: "^15" } }),
  );
  await assert.rejects(
    () => runInit({ cwd: dir, mode: "server", ide: "claude-code", yes: true }),
    /SUITEST_API_KEY/,
  );
});

test("init with no IDE detected and no --ide errors clearly", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  await assert.rejects(
    () => runInit({ cwd: dir, yes: true }),
    /IDE/,
  );
});
