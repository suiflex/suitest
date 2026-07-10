"use strict";
const { test } = require("node:test");
const assert = require("node:assert");

const { redactKey, parsePort } = require("../lib/settings.js");

test("parsePort accepts 1024-65535 and rejects everything else", () => {
  assert.strictEqual(parsePort("4000"), 4000);
  assert.strictEqual(parsePort(" 8080 "), 8080);
  assert.strictEqual(parsePort("1024"), 1024);
  assert.strictEqual(parsePort("65535"), 65535);
  assert.strictEqual(parsePort("1023"), null); // below range
  assert.strictEqual(parsePort("65536"), null); // above range
  assert.strictEqual(parsePort("80"), null);
  assert.strictEqual(parsePort("abc"), null);
  assert.strictEqual(parsePort("40a0"), null);
  assert.strictEqual(parsePort(""), null);
});

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
