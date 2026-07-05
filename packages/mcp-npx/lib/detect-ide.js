"use strict";

/**
 * IDE detection for `init` — a data table, one entry per IDE. Adding a new IDE
 * = one object here, zero logic changes.
 *
 * `configPath` resolves to the same file the existing installer writes (see
 * lib/install.js CLIENTS). `init` reuses `install.installClient` as the actual
 * merge-safe writer; this table only supplies *where to look* (markers) and the
 * project-scope config path for detection + display.
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// One entry per IDE. `configPath(cwd)` mirrors install.js CLIENTS project scope.
const IDE_TARGETS = [
  {
    id: "claude-code",
    label: "Claude Code",
    configPath: (cwd) => path.join(cwd, ".mcp.json"),
    markers: (cwd) => [path.join(cwd, ".mcp.json"), path.join(cwd, ".claude")],
  },
  {
    id: "cursor",
    label: "Cursor",
    configPath: () => path.join(os.homedir(), ".cursor", "mcp.json"),
    markers: (cwd) => [
      path.join(cwd, ".cursor", "mcp.json"),
      path.join(cwd, ".cursor"),
    ],
  },
  {
    id: "windsurf",
    label: "Windsurf",
    configPath: () =>
      path.join(os.homedir(), ".codeium", "windsurf", "mcp_config.json"),
    // Windsurf keeps its MCP config in $HOME, not the project, so there is no
    // project-local marker to auto-detect. Select it explicitly with
    // `--ide windsurf`. (Home-dir markers would make detection depend on
    // whatever IDEs the host happens to have installed — non-deterministic.)
    markers: () => [],
  },
];

function detectIdes(cwd) {
  return IDE_TARGETS.filter((t) => t.markers(cwd).some((m) => fs.existsSync(m)));
}

module.exports = { detectIdes, IDE_TARGETS };
