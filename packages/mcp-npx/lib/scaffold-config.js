"use strict";

/**
 * Scaffold a minimal `suitest.config.json`. Shape verified against the Python
 * loader (packages/lifecycle .../config.py `load_config`):
 *   - `mode` required — must be "frontend" | "backend" (Mode enum). This is the
 *     app's test mode, NOT the local/server delivery mode.
 *   - `baseUrl` required (`_require`).
 *   - `server.autostart=false` so an empty `startCommand` is not an error.
 * Never clobbers a user-authored config.
 */

const fs = require("node:fs");
const path = require("node:path");

function scaffoldConfig(cwd, { mode, projectName, baseUrl }) {
  const target = path.join(cwd, "suitest.config.json");
  if (fs.existsSync(target)) {
    return { created: false, path: target };
  }
  const config = {
    mode,
    projectName,
    projectPath: ".",
    baseUrl,
    server: { autostart: false, startCommand: "" },
  };
  fs.writeFileSync(target, JSON.stringify(config, null, 2) + "\n");
  return { created: true, path: target };
}

module.exports = { scaffoldConfig };
