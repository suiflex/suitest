"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { ensureWebDist, ensureWheels } = require("../lib/assets.js");

const ASSETS_DIR = path.join(__dirname, "..", "assets");
const BUNDLED_WEB = path.join(ASSETS_DIR, "web");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-assets-"));
}

test("override env returns the local dir", async () => {
  const dir = tmp();
  process.env.SUITEST_BUNDLE_WEB_DIST = dir;
  try {
    assert.strictEqual(await ensureWebDist(), dir);
  } finally {
    delete process.env.SUITEST_BUNDLE_WEB_DIST;
  }
});

test("override env pointing nowhere throws", async () => {
  process.env.SUITEST_BUNDLE_WHEELS_DIR = "/nonexistent/xyz";
  try {
    await assert.rejects(async () => ensureWheels(), /SUITEST_BUNDLE_WHEELS_DIR/);
  } finally {
    delete process.env.SUITEST_BUNDLE_WHEELS_DIR;
  }
});

test("bundled assets dir is used when present", async () => {
  const existed = fs.existsSync(BUNDLED_WEB);
  if (!existed) fs.mkdirSync(BUNDLED_WEB, { recursive: true });
  try {
    assert.strictEqual(await ensureWebDist(), BUNDLED_WEB);
  } finally {
    if (!existed) fs.rmSync(ASSETS_DIR, { recursive: true, force: true });
  }
});

test("missing bundled assets = actionable error naming the override", async () => {
  const backup = ASSETS_DIR + ".bak";
  const existed = fs.existsSync(ASSETS_DIR);
  if (existed) fs.renameSync(ASSETS_DIR, backup);
  try {
    await assert.rejects(
      async () => ensureWheels(),
      /sync-assets.*SUITEST_BUNDLE_WHEELS_DIR/s,
    );
  } finally {
    if (existed) fs.renameSync(backup, ASSETS_DIR);
  }
});
