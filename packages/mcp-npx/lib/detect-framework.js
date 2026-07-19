"use strict";

/**
 * App-framework detection for `init` — a data table, one entry per framework.
 * The result seeds `suitest.config.json` (mode + baseUrl). Adding a framework =
 * one row here.
 */

const fs = require("node:fs");
const path = require("node:path");

// Order = priority. Meta-frameworks (nuxt, sveltekit) before `vite`: they ship
// vite as a dep, but their own dev-server port must win. `next` before
// `express`: a Next app often ships both.
const FRAMEWORKS = [
  { id: "nextjs", dep: "next", mode: "frontend", baseUrl: "http://localhost:3000" },
  { id: "nuxt", dep: "nuxt", mode: "frontend", baseUrl: "http://localhost:3000" },
  { id: "sveltekit", dep: "@sveltejs/kit", mode: "frontend", baseUrl: "http://localhost:5173" },
  { id: "vite", dep: "vite", mode: "frontend", baseUrl: "http://localhost:5173" },
  { id: "vue", dep: "@vue/cli-service", mode: "frontend", baseUrl: "http://localhost:8080" },
  { id: "express", dep: "express", mode: "backend", baseUrl: "http://localhost:3000" },
];

function detectFramework(cwd) {
  // Django has no package.json; a manage.py is the tell.
  if (fs.existsSync(path.join(cwd, "manage.py"))) {
    return { framework: "django", mode: "backend", baseUrl: "http://localhost:8000" };
  }
  const pkgPath = path.join(cwd, "package.json");
  if (!fs.existsSync(pkgPath)) return null;
  let pkg;
  try {
    pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  } catch {
    return null;
  }
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  for (const fw of FRAMEWORKS) {
    if (deps[fw.dep]) {
      return { framework: fw.id, mode: fw.mode, baseUrl: fw.baseUrl };
    }
  }
  return null;
}

module.exports = { detectFramework, FRAMEWORKS };
