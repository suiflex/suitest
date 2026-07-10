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
  const { askSecret } = loadMcpLib("prompt.js");
  console.log("Create the admin account for your local Suitest (you'll log in with this):");

  // Email over a plain interface, closed before we prompt for secrets so the
  // masked-secret interface owns stdin without two readers competing.
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  let email = "";
  try {
    while (!email.includes("@")) {
      email = (await rl.question("  email: ")).trim();
    }
  } finally {
    rl.close();
  }

  // Password typed twice, masked (`askSecret` echoes `*`, never the chars).
  let password = "";
  for (;;) {
    password = await askSecret("  password (min 8 chars): ");
    if (password.length < 8) continue;
    const confirm = await askSecret("  confirm password: ");
    if (confirm === password) break;
    console.log("  Passwords don't match, try again.");
  }
  return loadOrCreateCredentials(credPath, { email, password });
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

// Resolve the dashboard port for onboard: an explicit --port wins; otherwise,
// interactively, offer the previously-used port (or 4000) as the default.
async function resolvePort(dirs, opts) {
  if (opts.port) return opts.port;
  if (!process.stdin.isTTY || !process.stdout.isTTY) return undefined;
  const { loadConfig } = require("./project.js");
  const current = loadConfig(dirs.config).port || 4000;
  const readline = require("node:readline/promises");
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await rl.question(`Dashboard port [${current}]: `)).trim();
    if (!answer) return current;
    if (/^\d+$/.test(answer)) {
      const n = Number(answer);
      if (n >= 1024 && n <= 65535) return n;
    }
    console.log(`  Ignoring invalid port "${answer}" — using ${current}.`);
    return current;
  } finally {
    rl.close();
  }
}

async function onboard(cwd, opts = {}) {
  const { dirs, webDist, python } = await prepare(cwd);
  await promptAccount(dirs.credentials, opts);
  const port = await resolvePort(dirs, opts);
  const running = await up(cwd, { webDist, python, port });
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
  stop      : suitest down
  start again (after reboot): suitest up`);
  return { ...running, apiUrl, mcpConfigPath };
}

module.exports = { onboard, prepare, loadMcpLib };
