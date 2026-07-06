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
  };
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
function loadOrCreateCredentials(credPath) {
  if (fs.existsSync(credPath)) {
    return JSON.parse(fs.readFileSync(credPath, "utf8"));
  }
  const creds = {
    email: "admin@suitest.local",
    password: crypto.randomBytes(24).toString("base64url"),
    apiKey: null,
  };
  saveCredentials(credPath, creds);
  return creds;
}

function saveCredentials(credPath, creds) {
  fs.writeFileSync(credPath, JSON.stringify(creds, null, 2) + "\n", { mode: 0o600 });
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
  dbUrl,
};
