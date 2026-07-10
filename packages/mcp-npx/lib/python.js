"use strict";

/**
 * Locate a Python >= 3.11 interpreter. Shared by the server launcher (bin)
 * and the installer's prereq check.
 *
 * Resolution order:
 *   1. $SUITEST_PYTHON, then `python3` / `python` on PATH.
 *   2. Fallback: a `uv`-managed Python. If the client has no system Python but
 *      has `uv` (a single static binary), we provision one automatically so
 *      "test my app" works without the user installing Python by hand.
 */

const { spawnSync } = require("node:child_process");

const MIN_PY = [3, 11];

function probeVersion(cmd, args = []) {
  const probe = spawnSync(cmd, [
    ...args,
    "-c",
    "import sys; print('%d.%d' % sys.version_info[:2])",
  ]);
  if (probe.status !== 0) return null;
  const [maj, min] = String(probe.stdout).trim().split(".").map(Number);
  if (Number.isNaN(maj) || Number.isNaN(min)) return null;
  if (maj > MIN_PY[0] || (maj === MIN_PY[0] && min >= MIN_PY[1])) {
    return `${maj}.${min}`;
  }
  return null;
}

// Provision/locate a uv-managed interpreter. Returns an absolute python path or
// null when uv is absent or the install fails (offline, etc.).
function findUvPython() {
  const uv = spawnSync("uv", ["--version"]);
  if (uv.status !== 0) return null;

  const target = `${MIN_PY[0]}.${Math.max(MIN_PY[1], 12)}`; // 3.12
  // Install is idempotent and fast when the interpreter is already present.
  spawnSync("uv", ["python", "install", target], { stdio: "ignore" });

  const found = spawnSync("uv", ["python", "find", target], { encoding: "utf8" });
  if (found.status !== 0) return null;
  const path = String(found.stdout).trim().split("\n")[0].trim();
  if (!path) return null;
  const version = probeVersion(path);
  return version ? { cmd: path, version, viaUv: true } : null;
}

function findPython() {
  const candidates = process.env.SUITEST_PYTHON
    ? [process.env.SUITEST_PYTHON]
    : ["python3", "python"];
  for (const cmd of candidates) {
    const version = probeVersion(cmd);
    if (version) return { cmd, version };
  }
  return findUvPython();
}

module.exports = { MIN_PY, findPython, findUvPython, probeVersion };
