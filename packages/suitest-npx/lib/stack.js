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
  dbUrl,
} = require("./project.js");
const { ensureApiKey } = require("./api-key.js");

function isFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once("error", () => resolve(false));
    srv.listen(port, "127.0.0.1", () => srv.close(() => resolve(true)));
  });
}

async function pickPort(preferred = 4000) {
  for (let p = preferred; p < preferred + 10; p += 1) {
    if (await isFree(p)) return p;
  }
  throw new Error(`No free port in ${preferred}-${preferred + 9}`);
}

// One env for API + supervisor: both MUST point at the same sqlite/artifacts
// (the runner honors the unprefixed SUITEST_DATABASE_URL / SUITEST_ARTIFACTS_* aliases).
function buildEnv(cwd, { port, webDist, creds }) {
  const dirs = projectDirs(cwd);
  return {
    ...process.env,
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
    detached: true,
    stdio: ["ignore", out, out],
  });
  child.unref();
  fs.closeSync(out);
  return child.pid;
}

async function waitHealthy(base, timeoutMs = 30_000) {
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
  throw new Error(
    `API not healthy after ${timeoutMs / 1000}s — see .suitest/logs/api.log`,
  );
}

async function up(cwd, { webDist, python, port: preferred }) {
  const dirs = ensureProjectDirs(cwd);

  if (fs.existsSync(dirs.pids)) {
    const prev = JSON.parse(fs.readFileSync(dirs.pids, "utf8"));
    if (isAlive(prev.api)) {
      console.log(`Already running: http://127.0.0.1:${prev.port}`);
      return prev;
    }
    fs.rmSync(dirs.pids);
  }

  const port = await pickPort(preferred || 4000);
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
    await waitHealthy(base);
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

  const state = { api, supervisor, port };
  fs.writeFileSync(dirs.pids, JSON.stringify(state, null, 2) + "\n");
  console.log(`Suitest local up: ${base}`);
  return state;
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

module.exports = { pickPort, buildEnv, up, down, isAlive, waitHealthy };
