"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { scaffoldConfig } = require("../lib/scaffold-config.js");

test("writes minimal valid config", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-cfg-"));
  const result = scaffoldConfig(dir, {
    mode: "frontend",
    projectName: "my-app",
    baseUrl: "http://localhost:3000",
  });
  assert.strictEqual(result.created, true);
  const written = JSON.parse(
    fs.readFileSync(path.join(dir, "suitest.config.json"), "utf8"),
  );
  assert.strictEqual(written.mode, "frontend"); // required by python loader
  assert.strictEqual(written.baseUrl, "http://localhost:3000"); // required by python loader
  assert.strictEqual(written.projectName, "my-app");
  assert.strictEqual(written.server.autostart, false); // autostart=false -> no startCommand needed
});

test("refuses to overwrite existing config", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "suitest-cfg-"));
  fs.writeFileSync(
    path.join(dir, "suitest.config.json"),
    '{"mode":"backend"}',
  );
  const result = scaffoldConfig(dir, {
    mode: "frontend",
    projectName: "x",
    baseUrl: "http://localhost:3000",
  });
  assert.strictEqual(result.created, false);
  // user's file is untouched
  assert.match(
    fs.readFileSync(path.join(dir, "suitest.config.json"), "utf8"),
    /backend/,
  );
});
