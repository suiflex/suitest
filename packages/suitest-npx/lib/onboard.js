"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { ensureProjectDirs } = require("./project.js");
const { ensureWebDist, ensureWheels } = require("./assets.js");
const { requireUv, ensureVenv } = require("./venv.js");
const { up } = require("./stack.js");

// ponytail: published dependency first; relative fallback for monorepo dev
// (node_modules is not guaranteed to exist in packages/suitest-npx while developing).
function loadMcpLib(mod) {
  try {
    return require(`@suiflex/suitest-mcp/lib/${mod}`);
  } catch {
    return require(path.join(__dirname, "..", "..", "mcp-npx", "lib", mod));
  }
}

// Prepare = every up() prerequisite: uv, assets, venv. Used by onboard AND `suitest up`.
async function prepare(cwd) {
  requireUv();
  const dirs = ensureProjectDirs(cwd);
  const webDist = await ensureWebDist();
  const wheels = await ensureWheels();
  const python = ensureVenv(dirs.venv, wheels);
  return { dirs, webDist, python };
}

async function onboard(cwd, opts = {}) {
  const { dirs, webDist, python } = await prepare(cwd);
  const running = await up(cwd, { webDist, python, port: opts.port });
  const creds = JSON.parse(fs.readFileSync(dirs.credentials, "utf8"));
  const apiUrl = `http://127.0.0.1:${running.port}`;

  const { runInit } = loadMcpLib("init.js");
  let mcpConfigPath = null;
  try {
    const result = await runInit({
      cwd,
      ide: opts.ide,
      yes: true,
      mode: "server",
      apiUrl,
      apiKey: creds.apiKey,
      baseUrl: opts.baseUrl,
    });
    mcpConfigPath = result.mcpConfigPath;
  } catch (err) {
    // Stack is already up — don't fail onboarding because IDE detection missed.
    console.error(`MCP wiring skipped: ${err.message}`);
    console.error("Re-run later: suitest init --ide <claude-code|cursor|windsurf>");
  }

  console.log(`
Suitest local ready:
  dashboard : ${apiUrl}
  MCP config: ${mcpConfigPath || "(not wired)"}
  data      : ${dirs.root}
  stop      : suitest down`);
  return { ...running, apiUrl, mcpConfigPath };
}

module.exports = { onboard, prepare, loadMcpLib };
