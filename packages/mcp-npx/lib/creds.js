"use strict";

/**
 * Credential resolution + persistence for `suitest-mcp`.
 *
 * The Suitest MCP server refuses to boot without SUITEST_API_URL +
 * SUITEST_API_KEY (it verifies against /api/v1/api-keys/whoami). So the
 * installer must put a working pair into each client's `env` block.
 *
 * Resolution order: explicit flags -> process env -> saved file -> interactive
 * TTY prompt (which offers to save). Non-TTY with nothing set returns
 * placeholders and warn=true so the caller can nag instead of silently
 * writing a dead config.
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const PLACEHOLDER = {
  apiUrl: "http://localhost:4000",
  apiKey: "sk_suitest_…",
};

// XDG-aware config dir, mirroring opencode_settings_path() in the jira ref.
function configDir() {
  if (process.env.SUITEST_CONFIG_DIR) return process.env.SUITEST_CONFIG_DIR;
  if (process.env.XDG_CONFIG_HOME) {
    return path.join(process.env.XDG_CONFIG_HOME, "suitest");
  }
  if (process.platform === "win32") {
    const appdata =
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
    return path.join(appdata, "suitest");
  }
  return path.join(os.homedir(), ".config", "suitest");
}

function credsPath() {
  return path.join(configDir(), "credentials.json");
}

function loadCreds() {
  const p = credsPath();
  if (!fs.existsSync(p)) return null;
  try {
    const raw = fs.readFileSync(p, "utf8").trim();
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (obj && obj.apiUrl && obj.apiKey) {
      return { apiUrl: String(obj.apiUrl), apiKey: String(obj.apiKey) };
    }
  } catch {
    // corrupt file -> treat as absent, resolve() will re-prompt/warn.
  }
  return null;
}

function saveCreds({ apiUrl, apiKey }) {
  const dir = configDir();
  fs.mkdirSync(dir, { recursive: true });
  const p = credsPath();
  fs.writeFileSync(p, `${JSON.stringify({ apiUrl, apiKey }, null, 2)}\n`);
  try {
    fs.chmodSync(p, 0o600);
  } catch {
    // best effort (e.g. Windows) — the value is user-scoped anyway.
  }
  return p;
}

function ask(rl, question) {
  return new Promise((resolve) => rl.question(question, (a) => resolve(a.trim())));
}

/**
 * Interactive prompt for URL + key. Prefills from `defaults` so the user can
 * just hit enter to keep an existing value. Returns null if aborted (empty
 * required field).
 */
async function promptCreds(defaults = {}) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  try {
    const urlHint = defaults.apiUrl ? ` [${defaults.apiUrl}]` : "";
    const keyHint = defaults.apiKey ? " [keep existing]" : "";
    const apiUrl =
      (await ask(rl, `SUITEST_API_URL${urlHint}: `)) || defaults.apiUrl || "";
    const apiKey =
      (await ask(rl, `SUITEST_API_KEY${keyHint}: `)) || defaults.apiKey || "";
    if (!apiUrl || !apiKey) return null;
    return { apiUrl, apiKey };
  } finally {
    rl.close();
  }
}

/**
 * Resolve credentials to embed in a client's `env` block.
 * @returns {{apiUrl:string, apiKey:string, warn:boolean, source:string}}
 */
async function resolveCreds({
  apiUrl,
  apiKey,
  interactive = true,
  allowPrompt = true,
} = {}) {
  // 1. explicit flags
  if (apiUrl && apiKey) {
    return { apiUrl, apiKey, warn: false, source: "flags" };
  }
  // 2. process env
  if (process.env.SUITEST_API_URL && process.env.SUITEST_API_KEY) {
    return {
      apiUrl: process.env.SUITEST_API_URL,
      apiKey: process.env.SUITEST_API_KEY,
      warn: false,
      source: "env",
    };
  }
  // 3. saved file
  const saved = loadCreds();
  if (saved) return { ...saved, warn: false, source: "saved" };

  // 4. interactive prompt (TTY only)
  if (interactive && allowPrompt && process.stdin.isTTY) {
    process.stdout.write(
      "No saved credentials. Enter them now (stored at " +
        `${credsPath()}, chmod 600):\n`,
    );
    const entered = await promptCreds();
    if (entered) {
      saveCreds(entered);
      process.stdout.write("Saved. Reused automatically next time.\n\n");
      return { ...entered, warn: false, source: "prompted" };
    }
  }

  // 5. give up -> placeholders + warn
  return { ...PLACEHOLDER, warn: true, source: "placeholder" };
}

module.exports = {
  PLACEHOLDER,
  configDir,
  credsPath,
  loadCreds,
  saveCreds,
  promptCreds,
  resolveCreds,
};
