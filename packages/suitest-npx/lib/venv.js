"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync, spawnSync } = require("node:child_process");

const pkg = require("../package.json");

// The raw per-OS install command — single source of truth shared by the manual
// hint below and the interactive auto-installer in preflight.js.
function uvInstallCommand(platform = process.platform) {
  return platform === "win32"
    ? 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    : "curl -LsSf https://astral.sh/uv/install.sh | sh";
}

function uvInstallHint(platform = process.platform) {
  return (
    "`uv` not found. Install it first:\n" +
    "  " +
    uvInstallCommand(platform) +
    "\nThen close this terminal, open a new one, and run the command again\n" +
    "(a fresh terminal picks up the updated PATH)."
  );
}

function requireUv() {
  const probe = spawnSync("uv", ["--version"], { stdio: "ignore" });
  if (probe.error || probe.status !== 0) {
    throw new Error(uvInstallHint());
  }
}

function venvPython(venvDir) {
  return process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
}

// Per-project venv from the release wheels; marker records the installed bundle version.
function ensureVenv(venvDir, wheelsDir) {
  const marker = path.join(venvDir, ".bundle-version");
  const python = venvPython(venvDir);
  if (
    fs.existsSync(python) &&
    fs.existsSync(marker) &&
    fs.readFileSync(marker, "utf8") === pkg.version
  ) {
    return python;
  }
  requireUv();
  const wheels = fs.existsSync(wheelsDir)
    ? fs
        .readdirSync(wheelsDir)
        .filter((f) => f.endsWith(".whl"))
        .map((f) => path.join(wheelsDir, f))
    : [];
  if (wheels.length === 0) {
    throw new Error(`No wheels (*.whl) found in ${wheelsDir}`);
  }
  console.log(
    "Setting up the Python runtime (first run or new version — may download Python 3.12, ~1 min)...",
  );
  execFileSync("uv", ["venv", venvDir, "--python", "3.12"], { stdio: "inherit" });
  execFileSync("uv", ["pip", "install", "--python", python, ...wheels], {
    stdio: "inherit",
  });
  fs.writeFileSync(marker, pkg.version);
  return python;
}

module.exports = { requireUv, uvInstallCommand, uvInstallHint, ensureVenv, venvPython };
