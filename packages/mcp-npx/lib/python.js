"use strict";

/**
 * Locate a Python >= 3.11 interpreter. Shared by the server launcher (bin)
 * and the installer's prereq check.
 */

const { spawnSync } = require("node:child_process");

const MIN_PY = [3, 11];

function findPython() {
  const candidates = process.env.SUITEST_PYTHON
    ? [process.env.SUITEST_PYTHON]
    : ["python3", "python"];
  for (const cmd of candidates) {
    const probe = spawnSync(cmd, [
      "-c",
      "import sys; print('%d.%d' % sys.version_info[:2])",
    ]);
    if (probe.status !== 0) continue;
    const [maj, min] = String(probe.stdout).trim().split(".").map(Number);
    if (maj > MIN_PY[0] || (maj === MIN_PY[0] && min >= MIN_PY[1])) {
      return { cmd, version: `${maj}.${min}` };
    }
  }
  return null;
}

module.exports = { MIN_PY, findPython };
