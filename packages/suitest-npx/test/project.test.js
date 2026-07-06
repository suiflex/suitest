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
  const mode = fs.statSync(dirs.credentials).mode & 0o777;
  assert.strictEqual(mode, 0o600);
  const again = loadOrCreateCredentials(dirs.credentials);
  assert.strictEqual(again.password, first.password);
  first.apiKey = "sk_suitest_x";
  saveCredentials(dirs.credentials, first);
  assert.strictEqual(loadOrCreateCredentials(dirs.credentials).apiKey, "sk_suitest_x");
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
