"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  projectDirs,
  ensureProjectDirs,
  loadOrCreateCredentials,
  saveCredentials,
  dbUrl,
  cacheDir,
} = require("../lib/project.js");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-launcher-"));
}

test("ensureProjectDirs creates .suitest layout", () => {
  const cwd = tmp();
  const dirs = ensureProjectDirs(cwd);
  assert.ok(fs.statSync(dirs.artifacts).isDirectory());
  assert.ok(fs.statSync(dirs.logs).isDirectory());
  assert.strictEqual(dirs.root, path.join(cwd, ".suitest"));
});

test("credentials are generated once, persisted with mode 600", () => {
  const cwd = tmp();
  const dirs = ensureProjectDirs(cwd);
  const first = loadOrCreateCredentials(dirs.credentials);
  assert.strictEqual(first.email, "admin@suitest.local");
  assert.ok(first.password.length >= 24);
  assert.strictEqual(first.apiKey, null);
  // 32 bytes base64 = 44 chars, decodes back to 32 (crypto.py urlsafe_b64decode)
  assert.strictEqual(Buffer.from(first.encryptionKey, "base64").length, 32);
  const mode = fs.statSync(dirs.credentials).mode & 0o777;
  assert.strictEqual(mode, 0o600);
  const again = loadOrCreateCredentials(dirs.credentials);
  assert.strictEqual(again.password, first.password);
  assert.strictEqual(again.encryptionKey, first.encryptionKey);
  first.apiKey = "sk_suitest_x";
  saveCredentials(dirs.credentials, first);
  assert.strictEqual(loadOrCreateCredentials(dirs.credentials).apiKey, "sk_suitest_x");
});

test("pre-encryptionKey credential files are backfilled on load", () => {
  const cwd = tmp();
  const dirs = ensureProjectDirs(cwd);
  fs.writeFileSync(
    dirs.credentials,
    JSON.stringify({ email: "admin@suitest.local", password: "pw", apiKey: null }),
  );
  const creds = loadOrCreateCredentials(dirs.credentials);
  assert.strictEqual(Buffer.from(creds.encryptionKey, "base64").length, 32);
  // persisted, not just in-memory
  const reread = JSON.parse(fs.readFileSync(dirs.credentials, "utf8"));
  assert.strictEqual(reread.encryptionKey, creds.encryptionKey);
});

test("dbUrl is absolute sqlite+aiosqlite (4 slashes)", () => {
  const cwd = tmp();
  const url = dbUrl(cwd);
  assert.ok(url.startsWith("sqlite+aiosqlite:////") || /^sqlite\+aiosqlite:\/\/\/[A-Za-z]:/.test(url));
  assert.ok(url.endsWith("suitest.db"));
});

test("cacheDir is versioned under home", () => {
  assert.ok(cacheDir("1.2.3").includes(path.join(".suitest", "cache", "1.2.3")));
});
