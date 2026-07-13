#!/usr/bin/env node
/**
 * Installer unit checks — no framework, just node:assert, mirroring smoke.test.js.
 * Exercises the pure logic (spec shape, JSON merge, idempotency, JSONC, paths)
 * without touching real client configs: every target is redirected via env.
 */

"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const install = require("../lib/install.js");
const creds = require("../lib/creds.js");

const ENV = { SUITEST_API_URL: "http://localhost:4000", SUITEST_API_KEY: "sk_test" };

function tmp(name) {
  const p = path.join(
    os.tmpdir(),
    `suitest-mcp-test-${process.pid}-${name}`,
  );
  fs.rmSync(p, { recursive: true, force: true });
  return p;
}

function silence(fn) {
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = () => true;
  try {
    return fn();
  } finally {
    process.stdout.write = orig;
  }
}

// 1. serverSpec shape (default mcpServers client)
{
  const { entry, snippet } = install.serverSpec("claude-code", ENV);
  assert.strictEqual(entry.command, "npx");
  assert.deepStrictEqual(entry.args, ["-y", "@suiflex/suitest-mcp"]);
  assert.deepStrictEqual(entry.env, ENV);
  assert.ok(snippet.mcpServers.suitest, "snippet has mcpServers.suitest");
}

// 2. opencode variant uses `mcp` + command array + environment
{
  const { entry, snippet } = install.serverSpec("opencode", ENV);
  assert.strictEqual(entry.type, "local");
  assert.deepStrictEqual(entry.command, ["npx", "-y", "@suiflex/suitest-mcp"]);
  assert.deepStrictEqual(entry.environment, ENV);
  assert.ok(snippet.mcp.suitest, "snippet has mcp.suitest");
}

// 3. Codex delegates the exact stdio command and env expected by its CLI.
{
  const steps = install.CLIENTS.codex.steps("suitest", ENV, false);
  assert.deepStrictEqual(steps, [
    [
      "mcp",
      "add",
      "suitest",
      "--env",
      "SUITEST_API_URL=http://localhost:4000",
      "--env",
      "SUITEST_API_KEY=sk_test",
      "--",
      "npx",
      "-y",
      "@suiflex/suitest-mcp",
    ],
  ]);
}

// 4. Antigravity uses the same portable mcpServers stdio shape as Claude.
{
  const antigravity = install.serverSpec("antigravity", ENV);
  const claude = install.serverSpec("claude-code", ENV);
  assert.deepStrictEqual(antigravity, claude);

  const target = tmp("antigravity.json");
  process.env.ANTIGRAVITY_CONFIG = target;
  silence(() => install.installClient("antigravity", {
    name: "suitest",
    scope: "global",
    env: ENV,
    print: false,
    dryRun: false,
    force: false,
  }));
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(target, "utf8")), antigravity.snippet);
  fs.rmSync(target, { force: true });
  delete process.env.ANTIGRAVITY_CONFIG;
}

// 5. write into an empty claude-code config, then idempotency + conflict
{
  const target = tmp("claude.json");
  process.env.CLAUDE_CODE_CONFIG = target;
  const opts = {
    name: "suitest",
    scope: "global",
    env: ENV,
    print: false,
    dryRun: false,
    force: false,
  };

  silence(() => install.installClient("claude-code", opts));
  const written = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.strictEqual(written.mcpServers.suitest.command, "npx");

  // second identical run is a no-op (no throw)
  silence(() => install.installClient("claude-code", opts));

  // different env without --force -> throws
  const conflict = { ...opts, env: { ...ENV, SUITEST_API_KEY: "sk_other" } };
  assert.throws(
    () => silence(() => install.installClient("claude-code", conflict)),
    /already exists/,
  );

  // with --force -> overwrites
  silence(() =>
    install.installClient("claude-code", { ...conflict, force: true }),
  );
  const after = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.strictEqual(after.mcpServers.suitest.env.SUITEST_API_KEY, "sk_other");

  fs.rmSync(target, { force: true });
  fs.rmSync(`${target}.bak`, { force: true });
  delete process.env.CLAUDE_CODE_CONFIG;
}

// 6. stripJsonComments handles JSONC (opencode config)
{
  const parsed = install.loadJsonObject; // ensure export present
  assert.strictEqual(typeof parsed, "function");
  const jsonc = '// top\n{\n  /* block */\n  "mcp": { "a": 1 }\n}\n';
  const stripped = install.stripJsonComments(jsonc);
  assert.deepStrictEqual(JSON.parse(stripped), { mcp: { a: 1 } });
}

// 7. credsPath honours XDG_CONFIG_HOME
{
  const prev = process.env.XDG_CONFIG_HOME;
  const prevDir = process.env.SUITEST_CONFIG_DIR;
  delete process.env.SUITEST_CONFIG_DIR;
  process.env.XDG_CONFIG_HOME = "/tmp/xdg-test";
  assert.strictEqual(
    creds.credsPath(),
    path.join("/tmp/xdg-test", "suitest", "credentials.json"),
  );
  if (prev === undefined) delete process.env.XDG_CONFIG_HOME;
  else process.env.XDG_CONFIG_HOME = prev;
  if (prevDir !== undefined) process.env.SUITEST_CONFIG_DIR = prevDir;
}

process.stdout.write("install.test.js OK\n");
