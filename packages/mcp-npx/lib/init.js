"use strict";

/**
 * `suitest-mcp init` — zero-config onboarding. Detects the IDE + app framework,
 * asks local vs server, then writes `suitest.config.json` and the MCP config.
 *
 * The MCP config write is delegated to the EXISTING merge-safe writer
 * (`install.installClient`) — never a second writer. init only points that
 * writer at the resolved config path via the client's path-override env var.
 */

const path = require("node:path");
const readline = require("node:readline/promises");

const { detectIdes, IDE_TARGETS } = require("./detect-ide.js");
const { detectFramework } = require("./detect-framework.js");
const { scaffoldConfig } = require("./scaffold-config.js");
const install = require("./install.js");

async function ask(question, fallback) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  try {
    const answer = (await rl.question(question)).trim();
    return answer || fallback;
  } finally {
    rl.close();
  }
}

// Write the suitest MCP entry into `configPath`, reusing installClient. We set
// the client's path-override env var so the shared writer targets exactly this
// file (honoring the passed cwd) instead of its default home/project location.
function writeMcpEntry(target, cwd, env) {
  const configPath = target.configPath(cwd);
  const prev = process.env[target.overrideEnv];
  process.env[target.overrideEnv] = configPath;
  try {
    install.installClient(target.installId, {
      name: "suitest",
      scope: "global", // global -> honors the overrideEnv path we just set
      env,
      print: false,
      dryRun: false,
      force: true, // init is idempotent: refresh our own entry, keep others
    });
  } finally {
    if (prev === undefined) delete process.env[target.overrideEnv];
    else process.env[target.overrideEnv] = prev;
  }
  return configPath;
}

async function runInit(opts) {
  const cwd = opts.cwd || process.cwd();

  // 1. IDE
  let ide = opts.ide;
  if (!ide) {
    const found = detectIdes(cwd);
    if (found.length === 1) ide = found[0].id;
    else if (found.length > 1 && !opts.yes) {
      const labels = found.map((t, i) => `${i + 1}) ${t.label}`).join("  ");
      const pick = await ask(
        `More than one IDE detected: ${labels}\nPick [1]: `,
        "1",
      );
      ide = (found[Number(pick) - 1] || found[0]).id;
    } else if (found.length > 1) {
      ide = found[0].id;
    }
  }
  const target = IDE_TARGETS.find((t) => t.id === ide);
  if (!target) {
    throw new Error(
      "No IDE detected. Re-run with --ide <claude-code|cursor|windsurf>.",
    );
  }

  // 2. Framework -> suitest.config.json defaults
  let fw = detectFramework(cwd);
  if (!fw) {
    const baseUrl = opts.baseUrl
      ? opts.baseUrl
      : opts.yes
        ? "http://localhost:3000"
        : await ask("App base URL [http://localhost:3000]: ", "http://localhost:3000");
    fw = { framework: "unknown", mode: "frontend", baseUrl };
  }

  // 3. Mode local/server
  let mode = opts.mode;
  if (!mode && !opts.yes) {
    const pick = await ask(
      "Mode: 1) Local (SQLite, no server)  2) Connect a server  [1]: ",
      "1",
    );
    mode = pick === "2" ? "server" : "local";
  }
  mode = mode || "local";

  // 4. env block for the mcpServers entry
  let serverEnv;
  if (mode === "local") {
    serverEnv = { SUITEST_MODE: "local" };
  } else {
    const apiUrl = opts.apiUrl
      ? opts.apiUrl
      : await ask("SUITEST_API_URL [http://localhost:4000]: ", "http://localhost:4000");
    const apiKey = opts.apiKey
      ? opts.apiKey
      : await ask("SUITEST_API_KEY (sk_suitest_…): ", "");
    if (!apiKey) {
      throw new Error(
        "server mode needs SUITEST_API_KEY — pass --api-key or run `login` first.",
      );
    }
    serverEnv = { SUITEST_API_URL: apiUrl, SUITEST_API_KEY: apiKey };
  }

  // 5. Write both files
  const cfg = scaffoldConfig(cwd, {
    mode: fw.mode,
    projectName: path.basename(cwd),
    baseUrl: fw.baseUrl,
  });
  const configPath = writeMcpEntry(target, cwd, serverEnv);

  return {
    ide,
    mode,
    framework: fw.framework,
    baseUrl: fw.baseUrl,
    configCreated: cfg.created,
    suitestConfigPath: cfg.path,
    mcpConfigPath: configPath,
  };
}

module.exports = { runInit };
