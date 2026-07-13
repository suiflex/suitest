"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  checkTool,
  uvBinCandidates,
  refreshUvPath,
  installerFor,
  preflight,
} = require("../lib/preflight.js");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-preflight-"));
}

test("checkTool returns false for a nonexistent binary", () => {
  assert.strictEqual(checkTool("definitely-not-a-real-binary-xyz"), false);
});

test("installerFor is platform-specific with a prereq", () => {
  const unix = installerFor("darwin");
  assert.strictEqual(unix.file, "sh");
  assert.strictEqual(unix.prereq, "curl");
  assert.match(unix.args.join(" "), /astral\.sh\/uv\/install\.sh/);

  const win = installerFor("win32");
  assert.strictEqual(win.prereq, "powershell");
  assert.match(win.args.join(" "), /install\.ps1/);
});

test("uvBinCandidates filters to existing dirs only", () => {
  const dir = tmp();
  const cands = uvBinCandidates("linux", { UV_INSTALL_DIR: dir, XDG_BIN_HOME: "/no/such/dir/x" });
  assert.ok(cands.includes(dir));
  assert.ok(!cands.includes("/no/such/dir/x"));
});

test("refreshUvPath prepends an existing candidate dir to PATH", () => {
  const dir = tmp();
  const env = { UV_INSTALL_DIR: dir, PATH: "/usr/bin" };
  refreshUvPath("linux", env);
  assert.ok(env.PATH.startsWith(dir + ":"));
  assert.ok(env.PATH.includes("/usr/bin"));
});

test("preflight throws the manual hint when non-TTY and uv missing", async () => {
  const prev = process.env.PATH;
  process.env.PATH = tmp(); // empty dir: no uv, no curl
  try {
    // Non-interactive (node --test has no TTY) and no --yes → must fall back to the hint.
    await assert.rejects(() => preflight({}, "linux"), /astral\.sh\/uv/);
  } finally {
    process.env.PATH = prev;
  }
});
