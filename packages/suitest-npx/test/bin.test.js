"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const { execFileSync } = require("node:child_process");
const path = require("node:path");

const BIN = path.join(__dirname, "..", "bin", "suitest.js");

test("no args prints usage, exit 1", () => {
  try {
    execFileSync(process.execPath, [BIN], { encoding: "utf8" });
    assert.fail("should exit non-zero");
  } catch (err) {
    assert.strictEqual(err.status, 1);
    assert.match(String(err.stdout) + String(err.stderr), /onboard.*up.*down.*init/s);
  }
});

test("unknown command exit 1", () => {
  try {
    execFileSync(process.execPath, [BIN, "frobnicate"], { encoding: "utf8" });
    assert.fail("should exit non-zero");
  } catch (err) {
    assert.strictEqual(err.status, 1);
    assert.match(String(err.stdout) + String(err.stderr), /Usage:/);
  }
});

test("--help exits 0 and prints usage to stdout", () => {
  const out = execFileSync(process.execPath, [BIN, "--help"], { encoding: "utf8" });
  assert.match(out, /Usage: suitest <command>/);
});
