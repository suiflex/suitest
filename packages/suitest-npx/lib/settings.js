"use strict";

// `suitest settings` — a tiny terminal panel for the things you'd otherwise open
// the browser dashboard for. MVP: generate/refresh the API key and show the
// current config. Built on the existing arrow-key picker + the existing
// `ensureApiKey` mint flow — no browser, no new dependency.

const fs = require("node:fs");

const { projectDirs, saveCredentials } = require("./project.js");
const { status } = require("./stack.js");
const { ensureApiKey } = require("./api-key.js");
const { loadMcpLib } = require("./onboard.js");

function redactKey(key) {
  if (!key) return "(none)";
  return key.length <= 8 ? "****" : `${key.slice(0, 6)}…${key.slice(-2)}`;
}

// Mint (or reuse a still-valid) API key against the running local stack and
// persist it into .suitest/credentials.json — same file `onboard` writes.
async function generateKey(cwd) {
  const s = await status(cwd);
  if (s.state !== "running") {
    console.log('Local stack not running — run "suitest up" first.');
    return;
  }
  const dirs = projectDirs(cwd);
  const creds = JSON.parse(fs.readFileSync(dirs.credentials, "utf8"));
  const key = await ensureApiKey(s.url, creds);
  creds.apiKey = key;
  saveCredentials(dirs.credentials, creds);
  console.log(`\nAPI key (saved to ${dirs.credentials}):\n  ${key}\n`);
}

function showConfig(cwd) {
  const dirs = projectDirs(cwd);
  if (!fs.existsSync(dirs.credentials)) {
    console.log('Not set up here — run "suitest onboard" first.');
    return;
  }
  const creds = JSON.parse(fs.readFileSync(dirs.credentials, "utf8"));
  console.log(
    `email  : ${creds.email}\napi key: ${redactKey(creds.apiKey)}\nfile   : ${dirs.credentials}`,
  );
}

async function runSettings(cwd) {
  if (!process.stdin.isTTY) {
    throw new Error("settings is interactive and needs a TTY.");
  }
  const { select } = loadMcpLib("picker.js");
  for (;;) {
    let choice;
    try {
      choice = await select("Suitest settings", [
        { value: "key", label: "Generate / refresh API key", hint: "no browser" },
        { value: "show", label: "Show current config" },
        { value: "quit", label: "Quit" },
      ]);
    } catch {
      return; // Esc / Ctrl-C
    }
    if (choice === "quit") return;
    if (choice === "key") await generateKey(cwd);
    else if (choice === "show") showConfig(cwd);
    console.log("");
  }
}

module.exports = { runSettings, generateKey, redactKey };
