"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const { PassThrough } = require("node:stream");

const { askSecret } = require("../lib/prompt.js");

test("askSecret returns the typed secret without echoing plaintext", async () => {
  // Note: per-keystroke `*` masking only fires under a real TTY (keystroke echo).
  // A PassThrough is line-buffered, so here we assert the two guarantees that
  // hold regardless of TTY: the exact value comes back and it never hits output.
  const input = new PassThrough();
  const output = new PassThrough();
  let seen = "";
  output.on("data", (b) => {
    seen += b.toString();
  });

  const p = askSecret("KEY: ", { input, output });
  input.write("sk_secret_123\n");
  const answer = await p;

  assert.strictEqual(answer, "sk_secret_123");
  assert.ok(!seen.includes("sk_secret_123"), "raw secret leaked to output");
});

test("askSecret returns empty string on a bare enter", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const p = askSecret("KEY: ", { input, output });
  input.write("\n");
  assert.strictEqual(await p, "");
});
