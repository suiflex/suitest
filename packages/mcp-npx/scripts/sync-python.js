#!/usr/bin/env node
/**
 * Sync the bundled Python sources from packages/lifecycle into ./python.
 *
 * Runs on `prepack` so the published tarball always carries the exact
 * suitest_lifecycle tree from this commit. The module is stdlib-only, so
 * copying sources (minus caches/tests) is the whole "build".
 *
 * In an npm-installed copy (no monorepo around it) the source dir does not
 * exist — that's fine: ./python was already bundled in the tarball, so the
 * script becomes a no-op instead of failing postinstall-style.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const PKG_ROOT = path.resolve(__dirname, "..");
const SRC = path.resolve(PKG_ROOT, "..", "lifecycle", "src", "suitest_lifecycle");
const DEST = path.join(PKG_ROOT, "python", "suitest_lifecycle");
const ROOT_LICENSE = path.resolve(PKG_ROOT, "..", "..", "LICENSE");

const SKIP = new Set(["__pycache__", ".pytest_cache", ".DS_Store"]);

function copyTree(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyTree(s, d);
    else if (entry.isFile()) fs.copyFileSync(s, d);
  }
}

if (!fs.existsSync(SRC)) {
  if (fs.existsSync(DEST)) {
    process.stdout.write("sync-python: monorepo source absent, bundled copy kept\n");
    process.exit(0);
  }
  process.stderr.write(`sync-python: source not found: ${SRC}\n`);
  process.exit(1);
}

fs.rmSync(path.join(PKG_ROOT, "python"), { recursive: true, force: true });
copyTree(SRC, DEST);
if (fs.existsSync(ROOT_LICENSE)) {
  fs.copyFileSync(ROOT_LICENSE, path.join(PKG_ROOT, "LICENSE"));
}
const count = fs.readdirSync(DEST).length;
process.stdout.write(`sync-python: bundled suitest_lifecycle (${count} top-level entries)\n`);
