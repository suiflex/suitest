"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { detectIdes, IDE_TARGETS } = require("../lib/detect-ide.js");

function tmpProject() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "suitest-init-"));
}

test("detects Claude Code from .mcp.json", () => {
  const dir = tmpProject();
  fs.writeFileSync(path.join(dir, ".mcp.json"), "{}");
  const found = detectIdes(dir);
  assert.deepStrictEqual(
    found.map((t) => t.id),
    ["claude-code"],
  );
});

test("detects Cursor from .cursor/mcp.json", () => {
  const dir = tmpProject();
  fs.mkdirSync(path.join(dir, ".cursor"));
  fs.writeFileSync(path.join(dir, ".cursor", "mcp.json"), "{}");
  const found = detectIdes(dir);
  assert.deepStrictEqual(
    found.map((t) => t.id),
    ["cursor"],
  );
});

test("empty project detects nothing", () => {
  assert.deepStrictEqual(detectIdes(tmpProject()), []);
});

test("every target declares id, label, configPath resolver", () => {
  for (const t of IDE_TARGETS) {
    assert.ok(t.id && t.label && typeof t.configPath === "function");
  }
});
