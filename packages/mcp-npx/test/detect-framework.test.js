"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { detectFramework } = require("../lib/detect-framework.js");

function projectWith(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-fw-"));
  for (const [rel, content] of Object.entries(files)) {
    fs.writeFileSync(path.join(dir, rel), content);
  }
  return dir;
}

test("next.js -> frontend :3000", () => {
  const dir = projectWith({
    "package.json": JSON.stringify({ dependencies: { next: "^15" } }),
  });
  assert.deepStrictEqual(detectFramework(dir), {
    framework: "nextjs",
    mode: "frontend",
    baseUrl: "http://localhost:3000",
  });
});

test("vite -> frontend :5173", () => {
  const dir = projectWith({
    "package.json": JSON.stringify({ devDependencies: { vite: "^6" } }),
  });
  assert.strictEqual(detectFramework(dir).baseUrl, "http://localhost:5173");
});

test("express -> backend :3000", () => {
  const dir = projectWith({
    "package.json": JSON.stringify({ dependencies: { express: "^4" } }),
  });
  assert.strictEqual(detectFramework(dir).mode, "backend");
});

test("django (manage.py) -> backend :8000", () => {
  const dir = projectWith({ "manage.py": "" });
  assert.deepStrictEqual(detectFramework(dir), {
    framework: "django",
    mode: "backend",
    baseUrl: "http://localhost:8000",
  });
});

test("unknown -> null (init akan tanya manual)", () => {
  assert.strictEqual(detectFramework(projectWith({})), null);
});
