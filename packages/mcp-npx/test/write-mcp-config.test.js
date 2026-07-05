"use strict";

/**
 * Merge-safety regression for the MCP-config writer. `init` reuses the EXISTING
 * writer — `install.installClient` — so this pins its root-cause behavior:
 * writing the `suitest` entry must never drop a user's other mcpServers.
 *
 * We drive the `claude-code` file target through its env override
 * (CLAUDE_CODE_CONFIG, global scope) so the test writes to a tmp file and never
 * touches a real config. This is the same merge code path project scope uses.
 */

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const install = require("../lib/install.js");

function tmpCfg() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-mcpcfg-"));
  return path.join(dir, ".mcp.json");
}

test("preserves existing mcpServers entries (merge, not overwrite)", () => {
  const cfgPath = tmpCfg();
  fs.writeFileSync(
    cfgPath,
    JSON.stringify({
      mcpServers: {
        playwright: { command: "npx", args: ["-y", "@playwright/mcp"] },
      },
    }),
  );

  const prev = process.env.CLAUDE_CODE_CONFIG;
  process.env.CLAUDE_CODE_CONFIG = cfgPath;
  try {
    install.installClient("claude-code", {
      name: "suitest",
      scope: "global",
      env: { SUITEST_MODE: "local" },
      print: false,
      dryRun: false,
      force: false,
    });
  } finally {
    if (prev === undefined) delete process.env.CLAUDE_CODE_CONFIG;
    else process.env.CLAUDE_CODE_CONFIG = prev;
  }

  const out = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
  assert.ok(out.mcpServers.playwright, "user's other server was lost — merge broke");
  assert.strictEqual(out.mcpServers.suitest.command, "npx");
  assert.deepStrictEqual(out.mcpServers.suitest.args, ["-y", "@suiflex/suitest-mcp"]);
  assert.strictEqual(out.mcpServers.suitest.env.SUITEST_MODE, "local");
});

test("creates file when absent", () => {
  const cfgPath = tmpCfg();
  fs.rmSync(cfgPath, { force: true });

  const prev = process.env.CLAUDE_CODE_CONFIG;
  process.env.CLAUDE_CODE_CONFIG = cfgPath;
  try {
    install.installClient("claude-code", {
      name: "suitest",
      scope: "global",
      env: { SUITEST_API_URL: "http://localhost:4000", SUITEST_API_KEY: "sk_x" },
      print: false,
      dryRun: false,
      force: false,
    });
  } finally {
    if (prev === undefined) delete process.env.CLAUDE_CODE_CONFIG;
    else process.env.CLAUDE_CODE_CONFIG = prev;
  }

  const out = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
  assert.strictEqual(out.mcpServers.suitest.env.SUITEST_API_KEY, "sk_x");
});
