"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function projectDirs(cwd) {
  const root = path.join(cwd, ".suitest");
  return {
    root,
    db: path.join(root, "suitest.db"),
    artifacts: path.join(root, "artifacts"),
    logs: path.join(root, "logs"),
    venv: path.join(root, ".venv"),
    credentials: path.join(root, "credentials.json"),
    pids: path.join(root, "pids.json"),
    config: path.join(root, "config.json"),
  };
}

// Per-project settings that must survive restarts (unlike pids.json, which is
// deleted on `down`). Today: the chosen port, so `suitest up` after a reboot
// boots on the SAME port the IDE MCP config was wired to.
function loadConfig(configPath) {
  try {
    return JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch {
    return {};
  }
}

function saveConfig(configPath, config) {
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
}

function ensureProjectDirs(cwd) {
  const dirs = projectDirs(cwd);
  fs.mkdirSync(dirs.artifacts, { recursive: true });
  fs.mkdirSync(dirs.logs, { recursive: true });
  return dirs;
}

function cacheDir(version) {
  return path.join(os.homedir(), ".suitest", "cache", version);
}

// Superadmin bootstrap credentials for local API; apiKey is filled after mint (api-key.js).
// encryptionKey feeds SUITEST_ENCRYPTION_KEY (urlsafe-b64, 32 bytes) — api_keys are
// AES-GCM encrypted at rest, so minting 500s without it. Backfilled on load for
// credential files created before this field existed.
// Password is NEVER auto-generated: the superadmin must set one they can remember,
// so account creation happens in `suitest onboard` (prompt or --email/--password).
function loadOrCreateCredentials(credPath, defaults = {}) {
  if (fs.existsSync(credPath)) {
    const creds = JSON.parse(fs.readFileSync(credPath, "utf8"));
    if (!creds.encryptionKey) {
      creds.encryptionKey = crypto.randomBytes(32).toString("base64");
      saveCredentials(credPath, creds);
    }
    return creds;
  }
  if (!defaults.password) {
    throw new Error('No admin account yet — run "suitest onboard" to create one.');
  }
  const creds = {
    email: defaults.email || "admin@suitest.local",
    password: defaults.password,
    encryptionKey: crypto.randomBytes(32).toString("base64"),
    apiKey: null,
  };
  saveCredentials(credPath, creds);
  return creds;
}

function saveCredentials(credPath, creds) {
  fs.writeFileSync(credPath, JSON.stringify(creds, null, 2) + "\n", { mode: 0o600 });
  fs.chmodSync(credPath, 0o600); // writeFileSync mode only applies at creation
}

// sqlite absolute path = sqlite+aiosqlite:////abs/path (path already starts with /)
function dbUrl(cwd) {
  return "sqlite+aiosqlite:///" + projectDirs(cwd).db;
}

module.exports = {
  projectDirs,
  ensureProjectDirs,
  cacheDir,
  loadOrCreateCredentials,
  saveCredentials,
  loadConfig,
  saveConfig,
  dbUrl,
};
