"use strict";
const { test } = require("node:test");
const assert = require("node:assert");

const { redactKey } = require("../lib/settings.js");

test("redactKey hides all but a short prefix/suffix", () => {
  assert.strictEqual(redactKey(null), "(none)");
  assert.strictEqual(redactKey(""), "(none)");
  assert.strictEqual(redactKey("shortk"), "****");
  assert.strictEqual(redactKey("sk_suitest_abcdef1234"), "sk_sui…34");
});

test("settings module loads the shared picker via the mcp-npx bridge", () => {
  const { loadMcpLib } = require("../lib/onboard.js");
  const { select } = loadMcpLib("picker.js");
  assert.strictEqual(typeof select, "function");
});
