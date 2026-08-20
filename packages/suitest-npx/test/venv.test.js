"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { requireUv, ensureVenv, venvPython, wheelsFingerprint } = require("../lib/venv.js");

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

test("ensureVenv short-circuits when the marker matches the wheel set", () => {
  const dir = tmp();
  const venvDir = path.join(dir, ".venv");
  const wheels = path.join(dir, "wheels");
  fs.mkdirSync(wheels);
  fs.writeFileSync(path.join(wheels, "suitest_api-0.1.0-py3-none-any.whl"), "a");
  const python = venvPython(venvDir);
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.writeFileSync(python, "");
  fs.writeFileSync(path.join(venvDir, ".bundle-version"), wheelsFingerprint(wheels));
  assert.strictEqual(ensureVenv(venvDir, wheels), python);
});

test("wheelsFingerprint changes when a wheel is rebuilt at the same version", () => {
  const dir = tmp();
  const wheels = path.join(dir, "wheels");
  fs.mkdirSync(wheels);
  const whl = path.join(wheels, "suitest_api-0.1.0-py3-none-any.whl");
  fs.writeFileSync(whl, "old build");
  const before = wheelsFingerprint(wheels);
  // Same package version, same filename — only the built artifact changed. This
  // is the case that used to reuse a stale venv and serve an API without the
  // routes the freshly built dashboard calls.
  fs.writeFileSync(whl, "new build, different size");
  assert.notStrictEqual(wheelsFingerprint(wheels), before);
  assert.strictEqual(wheelsFingerprint(wheels), wheelsFingerprint(wheels));
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
