"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const { cacheDir } = require("./project.js");
const pkg = require("../package.json");

// Assets are pinned to the package version: release tag bundle-v<version> on suiflex/suitest.
function releaseBase() {
  return (
    process.env.SUITEST_BUNDLE_BASE_URL ||
    `https://github.com/suiflex/suitest/releases/download/bundle-v${pkg.version}`
  );
}

async function ensureAsset(name, overrideEnv) {
  const override = process.env[overrideEnv];
  if (override) {
    if (!fs.existsSync(override)) {
      throw new Error(`${overrideEnv}=${override} does not exist`);
    }
    return override;
  }
  const dest = path.join(cacheDir(pkg.version), name);
  if (fs.existsSync(path.join(dest, ".complete"))) return dest;

  const url = `${releaseBase()}/${name}.tar.gz`;
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) {
    throw new Error(
      `Download failed: ${url} (HTTP ${res.status}).\n` +
        `Bundle assets for v${pkg.version} may not be published yet.\n` +
        `Workaround: set ${overrideEnv}=<local dir> to skip the download.`,
    );
  }
  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(dest, { recursive: true });
  const tarball = path.join(dest, `${name}.tar.gz`);
  fs.writeFileSync(tarball, Buffer.from(await res.arrayBuffer()));
  execFileSync("tar", ["-xzf", tarball, "-C", dest]);
  fs.rmSync(tarball);
  fs.writeFileSync(path.join(dest, ".complete"), "");
  return dest;
}

const ensureWebDist = () => ensureAsset("web", "SUITEST_BUNDLE_WEB_DIST");
const ensureWheels = () => ensureAsset("wheels", "SUITEST_BUNDLE_WHEELS_DIR");

module.exports = { ensureWebDist, ensureWheels, releaseBase };
