"use strict";
const { test } = require("node:test");
const assert = require("node:assert");

const { loadMcpLib } = require("../lib/onboard.js");

test("loadMcpLib resolves mcp-npx modules (monorepo fallback)", () => {
  const { runInit } = loadMcpLib("init.js");
  assert.strictEqual(typeof runInit, "function");
  const { IDE_TARGETS } = loadMcpLib("detect-ide.js");
  assert.ok(IDE_TARGETS.some((t) => t.id === "claude-code"));
});
