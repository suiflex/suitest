"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { runInit } = require("../lib/init.js");

test("init local mode: config + mcp entry written, no API key", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  fs.writeFileSync(path.join(dir, ".mcp.json"), "{}"); // simulate Claude Code
  fs.writeFileSync(
    path.join(dir, "package.json"),
    JSON.stringify({ dependencies: { next: "^15" } }),
  );

  const result = await runInit({
    cwd: dir,
    mode: "local",
    ide: "claude-code",
    yes: true,
  });

  assert.strictEqual(result.ide, "claude-code");
  const suitestCfg = JSON.parse(
    fs.readFileSync(path.join(dir, "suitest.config.json"), "utf8"),
  );
  assert.strictEqual(suitestCfg.baseUrl, "http://localhost:3000");
  assert.strictEqual(suitestCfg.mode, "frontend");
  const mcpCfg = JSON.parse(fs.readFileSync(path.join(dir, ".mcp.json"), "utf8"));
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_MODE, "local");
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_API_KEY, undefined);
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

  await runInit({ cwd: dir, mode: "local", ide: "claude-code", yes: true });

  const mcpCfg = JSON.parse(fs.readFileSync(path.join(dir, ".mcp.json"), "utf8"));
  assert.ok(mcpCfg.mcpServers.playwright, "user's other server was lost");
  assert.strictEqual(mcpCfg.mcpServers.suitest.env.SUITEST_MODE, "local");
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

test("init with no IDE detected and no --ide errors clearly", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-e2e-"));
  await assert.rejects(
    () => runInit({ cwd: dir, mode: "local", yes: true }),
    /IDE/,
  );
});
