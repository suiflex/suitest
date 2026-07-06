"use strict";

const fs = require("node:fs");
const path = require("node:path");

// Assets (web dist + wheels) ship INSIDE the npm package under assets/,
// copied from the repo's dist/bundle at pack time (scripts/sync-assets.js,
// prepack). Total ~3 MB — small enough that download-on-first-run from
// GitHub Releases was dropped (the repo is private; release assets 404
// for anonymous users). Env overrides remain for monorepo dev/tests.
function ensureAsset(name, overrideEnv) {
  const override = process.env[overrideEnv];
  if (override) {
    if (!fs.existsSync(override)) {
      throw new Error(`${overrideEnv}=${override} does not exist`);
    }
    return override;
  }
  const bundled = path.join(__dirname, "..", "assets", name);
  if (!fs.existsSync(bundled)) {
    throw new Error(
      `Bundled asset missing: ${bundled}.\n` +
        `Packaging bug (scripts/sync-assets.js did not run before publish), ` +
        `or a monorepo checkout — run scripts/build-bundle-assets.sh and set ` +
        `${overrideEnv}=<repo>/dist/bundle/${name}.`,
    );
  }
  return bundled;
}

const ensureWebDist = () => ensureAsset("web", "SUITEST_BUNDLE_WEB_DIST");
const ensureWheels = () => ensureAsset("wheels", "SUITEST_BUNDLE_WHEELS_DIR");

module.exports = { ensureWebDist, ensureWheels };
