"use strict";

const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { spawn, execFileSync } = require("node:child_process");

const {
  projectDirs,
  ensureProjectDirs,
  loadOrCreateCredentials,
  saveCredentials,
  loadConfig,
  saveConfig,
  dbUrl,
} = require("./project.js");
const { ensureApiKey } = require("./api-key.js");

const pkg = require("../package.json");

function isFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.listen(port, "127.0.0.1", () => srv.close(() => resolve(true)));
  });
}

// No silent fallback to preferred+1: the IDE MCP config and the user's muscle
// memory both point at ONE port — booting somewhere else just hides the problem.
async function pickPort(preferred = 4000) {
  if (await isFree(preferred)) return preferred;
  throw new Error(
    `Port ${preferred} is already in use.\n` +
      `Stop the app using it first, then run again.\n` +
      `(Another Suitest project? Run "suitest down" in that project.)\n` +
      `Or pick a different port: suitest up --port ${preferred + 1}`,
  );
}

// One env for API + supervisor: both MUST point at the same sqlite/artifacts
// (the runner honors the unprefixed SUITEST_DATABASE_URL / SUITEST_ARTIFACTS_* aliases).
function buildEnv(cwd, { port, webDist, creds }) {
  const dirs = projectDirs(cwd);
  return {
    ...process.env,
    // stdout is redirected to .suitest/logs/*.log; without this Python
    // block-buffers and log lines are delayed or lost on SIGTERM.
    PYTHONUNBUFFERED: "1",
    SUITEST_MODE: "local",
    SUITEST_DATABASE_URL: dbUrl(cwd),
    SUITEST_ARTIFACTS_BACKEND: "local",
    SUITEST_ARTIFACTS_DIR: dirs.artifacts,
    SUITEST_WEB_DIST: webDist,
    SUITEST_OTEL_DISABLED: "1",
    SUITEST_SUPERADMIN_EMAIL: creds.email,
    SUITEST_SUPERADMIN_PASSWORD: creds.password,
    SUITEST_ENCRYPTION_KEY: creds.encryptionKey,
    SUITEST_API_URL: `http://127.0.0.1:${port}`,
  };
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function spawnLogged(cmd, args, { env, logFile }) {
  const out = fs.openSync(logFile, "a");
  const child = spawn(cmd, args, {
    env,
    // ponytail: detached only off-Windows — detached:true forces a job-object
    // assign that fails with AssignProcessToJobObject (87) when the parent is
    // already in a no-breakaway job (VS Code terminal / CI). unref() alone keeps
    // the child alive after the parent exits.
    detached: process.platform !== "win32",
    stdio: ["ignore", out, out],
    windowsHide: true,
  });
  child.unref();
  fs.closeSync(out);
  return child.pid;
}

function tailFile(file, lines = 15) {
  try {
    const content = fs.readFileSync(file, "utf8").trimEnd().split("\n");
    return content.slice(-lines).join("\n");
  } catch {
    return "(no log file yet)";
  }
}

// 60s: slow disks + antivirus scans on first boot blow past 30s regularly.
async function waitHealthy(base, timeoutMs = 60_000, logFile = null) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(base + "/health");
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  const tail = logFile ? `\n\nLast lines of ${logFile}:\n${tailFile(logFile)}` : "";
  throw new Error(`API not healthy after ${timeoutMs / 1000}s.${tail}`);
}

async function isHealthy(base) {
  try {
    const res = await fetch(base + "/health", { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function up(cwd, { webDist, python, port: preferred }) {
  const dirs = ensureProjectDirs(cwd);
  const config = loadConfig(dirs.config);

  if (fs.existsSync(dirs.pids)) {
    const prev = JSON.parse(fs.readFileSync(dirs.pids, "utf8"));
    // PID alone lies after a reboot (PIDs get reused) — the health probe decides.
    if (isAlive(prev.api) && (await isHealthy(`http://127.0.0.1:${prev.port}`))) {
      if (prev.version && prev.version !== pkg.version) {
        console.log(
          `Already running: http://127.0.0.1:${prev.port}\n` +
            `But it's version ${prev.version} and you invoked ${pkg.version} — ` +
            `run "suitest down" then "suitest up" to switch.`,
        );
      } else {
        console.log(`Already running: http://127.0.0.1:${prev.port}`);
      }
      return prev;
    }
    fs.rmSync(dirs.pids);
  }

  // Priority: explicit --port > port this project used before > 4000.
  const port = await pickPort(preferred || config.port || 4000);
  const creds = loadOrCreateCredentials(dirs.credentials);
  const env = buildEnv(cwd, { port, webDist, creds });
  const base = `http://127.0.0.1:${port}`;

  // Schema first (idempotent) — the API lifespan queries users during superadmin bootstrap.
  execFileSync(python, ["-m", "suitest_db.bootstrap"], { env, stdio: "inherit" });

  // Verified: create_app(settings=None) is a sync zero-arg-callable factory, so --factory works.
  const api = spawnLogged(
    python,
    [
      "-m", "uvicorn", "suitest_api.main:create_app", "--factory",
      "--host", "127.0.0.1", // trust boundary: NEVER 0.0.0.0
      "--port", String(port),
    ],
    { env, logFile: path.join(dirs.logs, "api.log") },
  );

  try {
    await waitHealthy(base, 60_000, path.join(dirs.logs, "api.log"));
    creds.apiKey = await ensureApiKey(base, creds);
    saveCredentials(dirs.credentials, creds);
  } catch (err) {
    if (isAlive(api)) process.kill(api, "SIGTERM");
    throw err;
  }

  const supervisor = spawnLogged(
    python,
    ["-m", "suitest_runner.local_supervisor"],
    { env, logFile: path.join(dirs.logs, "supervisor.log") },
  );

  const state = { api, supervisor, port, version: pkg.version };
  fs.writeFileSync(dirs.pids, JSON.stringify(state, null, 2) + "\n");
  saveConfig(dirs.config, { ...config, port });
  console.log(`Suitest local up: ${base}`);
  return state;
}

// For `suitest status`: never boots anything, just reports.
async function status(cwd) {
  const dirs = projectDirs(cwd);
  if (!fs.existsSync(dirs.credentials)) {
    return { state: "not-onboarded" };
  }
  if (!fs.existsSync(dirs.pids)) {
    return { state: "stopped" };
  }
  const pids = JSON.parse(fs.readFileSync(dirs.pids, "utf8"));
  const url = `http://127.0.0.1:${pids.port}`;
  const healthy = isAlive(pids.api) && (await isHealthy(url));
  return { state: healthy ? "running" : "stale", url, ...pids };
}

function down(cwd) {
  const dirs = projectDirs(cwd);
  if (!fs.existsSync(dirs.pids)) {
    console.log("Not running (no .suitest/pids.json).");
    return false;
  }
  const pids = JSON.parse(fs.readFileSync(dirs.pids, "utf8"));
  for (const pid of [pids.supervisor, pids.api]) {
    if (pid && isAlive(pid)) {
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        // died between check and kill — ignore
      }
    }
  }
  fs.rmSync(dirs.pids);
  console.log("Suitest local stopped.");
  return true;
}

module.exports = { pickPort, buildEnv, up, down, status, isAlive, isHealthy, waitHealthy };
