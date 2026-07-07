"use strict";
const { test } = require("node:test");
const assert = require("node:assert");

const { isNewer } = require("../lib/update-check.js");

test("isNewer compares semver numerically, not lexically", () => {
  assert.strictEqual(isNewer("0.1.10", "0.1.9"), true);
  assert.strictEqual(isNewer("0.2.0", "0.1.9"), true);
  assert.strictEqual(isNewer("1.0.0", "0.9.9"), true);
  assert.strictEqual(isNewer("0.1.3", "0.1.3"), false);
  assert.strictEqual(isNewer("0.1.2", "0.1.3"), false);
  assert.strictEqual(isNewer("0.1", "0.1.0"), false); // missing part = 0
});
