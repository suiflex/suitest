"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { requireUv, ensureVenv, venvPython } = require("../lib/venv.js");
const pkg = require("../package.json");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-venv-"));
}

test("requireUv throws helpful error when uv missing from PATH", () => {
  const prev = process.env.PATH;
  process.env.PATH = tmp(); // empty dir: no uv
  try {
    assert.throws(() => requireUv(), /astral\.sh\/uv/);
  } finally {
    process.env.PATH = prev;
  }
});

test("venvPython points into bin/ (posix) or Scripts/ (win)", () => {
  const p = venvPython("/x/.venv");
  if (process.platform === "win32") assert.match(p, /Scripts.python\.exe$/);
  else assert.strictEqual(p, "/x/.venv/bin/python");
});

test("ensureVenv short-circuits when marker matches package version", () => {
  const venvDir = path.join(tmp(), ".venv");
  const python = venvPython(venvDir);
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.writeFileSync(python, "");
  fs.writeFileSync(path.join(venvDir, ".bundle-version"), pkg.version);
  // wheelsDir unused on the cache-hit path — bogus path proves the short-circuit
  assert.strictEqual(ensureVenv(venvDir, "/nonexistent"), python);
});

test("ensureVenv with empty wheels dir throws", () => {
  const dir = tmp();
  const venvDir = path.join(dir, ".venv");
  const wheels = path.join(dir, "wheels");
  fs.mkdirSync(wheels);
  // uv is installed on dev machines; if not, requireUv throws first — both throw
  assert.throws(() => ensureVenv(venvDir, wheels), /No wheels|astral\.sh/);
});

test("uvInstallHint is platform-specific and says to reopen the terminal", () => {
  const { uvInstallHint } = require("../lib/venv.js");
  assert.match(uvInstallHint("win32"), /powershell/);
  assert.match(uvInstallHint("win32"), /install\.ps1/);
  assert.match(uvInstallHint("darwin"), /curl/);
  assert.match(uvInstallHint("linux"), /install\.sh/);
  assert.match(uvInstallHint("darwin"), /new one/i);
});
