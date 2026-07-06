"use strict";

// prepack: copy the built bundle assets (repo dist/bundle/{web,wheels}) into
// the package's assets/ dir so they ship inside the npm tarball (~3 MB).
// Run scripts/build-bundle-assets.sh at the repo root first.

const fs = require("node:fs");
const path = require("node:path");

const pkgRoot = path.join(__dirname, "..");
const bundle = path.join(pkgRoot, "..", "..", "dist", "bundle");
const dest = path.join(pkgRoot, "assets");

for (const name of ["web", "wheels"]) {
  const src = path.join(bundle, name);
  if (!fs.existsSync(src)) {
    console.error(
      `sync-assets: ${src} missing — run scripts/build-bundle-assets.sh first.`,
    );
    process.exit(1);
  }
}

fs.rmSync(dest, { recursive: true, force: true });
for (const name of ["web", "wheels"]) {
  fs.cpSync(path.join(bundle, name), path.join(dest, name), { recursive: true });
}
// Strip build leftovers: cache sentinels + the .gitignore uv drops into -o dirs.
for (const name of ["web", "wheels"]) {
  fs.rmSync(path.join(dest, name, ".complete"), { force: true });
  fs.rmSync(path.join(dest, name, ".gitignore"), { force: true });
}

const count = (d) => fs.readdirSync(d).length;
console.log(
  `sync-assets: bundled web (${count(path.join(dest, "web"))} entries) + ` +
    `wheels (${count(path.join(dest, "wheels"))} wheels)`,
);
