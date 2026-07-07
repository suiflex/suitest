"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { ensureProjectDirs, loadOrCreateCredentials } = require("./project.js");
const { ensureWebDist, ensureWheels } = require("./assets.js");
const { requireUv, ensureVenv } = require("./venv.js");
const { up } = require("./stack.js");

// First run → the user MUST set the superadmin account; nothing is auto-generated
// (a generated password gets lost, and it's the only superadmin). Interactive prompt
// requires a password typed twice; non-TTY (CI) must pass --email/--password.
async function promptAccount(credPath, opts = {}) {
  if (fs.existsSync(credPath)) return loadOrCreateCredentials(credPath);
  if (opts.email || opts.password) {
    if (!opts.email || !opts.password) {
      throw new Error("Both --email and --password are required to create the admin account.");
    }
    return loadOrCreateCredentials(credPath, { email: opts.email, password: opts.password });
  }
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error(
      "No admin account yet and no terminal to ask — re-run interactively, or pass --email and --password.",
    );
  }
  const readline = require("node:readline/promises");
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    console.log("Create the admin account for your local Suitest (you'll log in with this):");
    let email = "";
    while (!email.includes("@")) {
      email = (await rl.question("  email: ")).trim();
    }
    let password = "";
    for (;;) {
      password = (await rl.question("  password (min 8 chars): ")).trim();
      if (password.length < 8) continue;
      const confirm = (await rl.question("  confirm password: ")).trim();
      if (confirm === password) break;
      console.log("  Passwords don't match, try again.");
    }
    return loadOrCreateCredentials(credPath, { email, password });
  } finally {
    rl.close();
  }
}

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
  await promptAccount(dirs.credentials, opts);
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
  login     : ${creds.email} (password you set; stored in ${dirs.credentials})
  MCP config: ${mcpConfigPath || "(not wired)"}
  data      : ${dirs.root}
  stop      : suitest down`);
  return { ...running, apiUrl, mcpConfigPath };
}

module.exports = { onboard, prepare, loadMcpLib };
