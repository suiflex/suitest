"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const { ensureWebDist, ensureWheels } = require("../lib/assets.js");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-assets-"));
}

test("override env returns the local dir, no network", async () => {
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
    await assert.rejects(() => ensureWheels(), /SUITEST_BUNDLE_WHEELS_DIR/);
  } finally {
    delete process.env.SUITEST_BUNDLE_WHEELS_DIR;
  }
});

test("cache hit (sentinel .complete) skips download", async () => {
  const home = tmp();
  const prevHome = process.env.HOME;
  process.env.HOME = home;
  try {
    const version = require("../package.json").version;
    const cached = path.join(home, ".suitest", "cache", version, "web");
    fs.mkdirSync(cached, { recursive: true });
    fs.writeFileSync(path.join(cached, ".complete"), "");
    assert.strictEqual(await ensureWebDist(), cached);
  } finally {
    process.env.HOME = prevHome;
  }
});

test("404 from release host = clear error naming version + override", async () => {
  const home = tmp();
  const prevHome = process.env.HOME;
  process.env.HOME = home;
  const srv = http.createServer((req, res) => {
    res.statusCode = 404;
    res.end("nope");
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  process.env.SUITEST_BUNDLE_BASE_URL = `http://127.0.0.1:${srv.address().port}`;
  try {
    await assert.rejects(
      () => ensureWebDist(),
      /404.*SUITEST_BUNDLE_WEB_DIST/s,
    );
  } finally {
    delete process.env.SUITEST_BUNDLE_BASE_URL;
    process.env.HOME = prevHome;
    srv.close();
  }
});
