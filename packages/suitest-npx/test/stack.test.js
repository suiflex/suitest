"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const { pickPort, buildEnv, down, isAlive } = require("../lib/stack.js");
const { ensureProjectDirs } = require("../lib/project.js");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-stack-"));
}

test("pickPort skips an occupied port", async () => {
  const blocker = net.createServer();
  await new Promise((r) => blocker.listen(0, "127.0.0.1", r));
  const busy = blocker.address().port;
  try {
    const port = await pickPort(busy);
    assert.notStrictEqual(port, busy);
    assert.ok(port > busy && port < busy + 10);
  } finally {
    blocker.close();
  }
});

test("buildEnv composes the full local env for both processes", () => {
  const cwd = tmp();
  const creds = { email: "admin@suitest.local", password: "pw", encryptionKey: "a2V5", apiKey: null };
  const env = buildEnv(cwd, { port: 4321, webDist: "/cache/web", creds });
  assert.strictEqual(env.SUITEST_ENCRYPTION_KEY, "a2V5");
  assert.strictEqual(env.PYTHONUNBUFFERED, "1");
  assert.strictEqual(env.SUITEST_MODE, "local");
  assert.ok(env.SUITEST_DATABASE_URL.startsWith("sqlite+aiosqlite:///"));
  assert.strictEqual(env.SUITEST_ARTIFACTS_BACKEND, "local");
  assert.strictEqual(env.SUITEST_ARTIFACTS_DIR, path.join(cwd, ".suitest", "artifacts"));
  assert.strictEqual(env.SUITEST_WEB_DIST, "/cache/web");
  assert.strictEqual(env.SUITEST_OTEL_DISABLED, "1");
  assert.strictEqual(env.SUITEST_SUPERADMIN_EMAIL, "admin@suitest.local");
  assert.strictEqual(env.SUITEST_SUPERADMIN_PASSWORD, "pw");
  assert.strictEqual(env.SUITEST_API_URL, "http://127.0.0.1:4321");
});

test("down with stale pidfile cleans up and returns true", () => {
  const cwd = tmp();
  const dirs = ensureProjectDirs(cwd);
  fs.writeFileSync(dirs.pids, JSON.stringify({ api: 99999999, supervisor: 99999998, port: 4000 }));
  assert.strictEqual(down(cwd), true);
  assert.strictEqual(fs.existsSync(dirs.pids), false);
});

test("down without pidfile returns false", () => {
  assert.strictEqual(down(tmp()), false);
});

test("isAlive: own pid true, bogus pid false", () => {
  assert.strictEqual(isAlive(process.pid), true);
  assert.strictEqual(isAlive(99999999), false);
});
