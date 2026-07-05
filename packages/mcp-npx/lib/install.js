"use strict";

/**
 * `suitest-mcp install` — register the Suitest MCP server into a supported
 * IDE agent's config. Node/stdlib port of jira-commands' crates/jira/src/cli/mcp.rs.
 *
 * File-target clients get their JSON/JSONC config merged in place (with a .bak
 * backup); CLIs that own an `mcp add` command are delegated to. Every entry
 * carries the SUITEST_API_URL/KEY env the server needs to boot.
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const creds = require("./creds.js");
const picker = require("./picker.js");
const { findPython } = require("./python.js");

const PKG = "@suiflex/suitest-mcp";
const NPX_ARGS = ["-y", PKG];

function homeConfig(envKey, ...segments) {
  if (envKey && process.env[envKey]) return process.env[envKey];
  return path.join(os.homedir(), ...segments);
}

function claudeDesktopPath() {
  const home = os.homedir();
  if (process.platform === "darwin") {
    return path.join(
      home,
      "Library/Application Support/Claude/claude_desktop_config.json",
    );
  }
  if (process.platform === "win32") {
    const appdata = process.env.APPDATA || path.join(home, "AppData/Roaming");
    return path.join(appdata, "Claude/claude_desktop_config.json");
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "Claude/claude_desktop_config.json");
}

function opencodePath() {
  if (process.env.OPENCODE_CONFIG) return process.env.OPENCODE_CONFIG;
  const home = os.homedir();
  if (process.platform === "win32") {
    const appdata = process.env.APPDATA || path.join(home, "AppData/Roaming");
    return path.join(appdata, "opencode/opencode.jsonc");
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "opencode/opencode.jsonc");
}

// Client registry — same 11 targets as the jira reference.
const CLIENTS = {
  "claude-code": {
    kind: "file",
    label: "claude-code",
    hint: "writes ~/.claude.json mcpServers",
    key: "mcpServers",
    targetPath: (scope) =>
      scope === "project"
        ? path.resolve(process.cwd(), ".mcp.json")
        : homeConfig("CLAUDE_CODE_CONFIG", ".claude.json"),
  },
  "claude-desktop": {
    kind: "file",
    label: "claude-desktop",
    hint: "writes claude_desktop_config.json in Claude support dir",
    key: "mcpServers",
    targetPath: () => process.env.CLAUDE_DESKTOP_CONFIG || claudeDesktopPath(),
  },
  cursor: {
    kind: "file",
    label: "cursor",
    hint: "writes ~/.cursor/mcp.json",
    key: "mcpServers",
    targetPath: () => homeConfig("CURSOR_CONFIG", ".cursor/mcp.json"),
  },
  codex: {
    kind: "delegated",
    label: "codex",
    hint: "delegates to `codex mcp add`",
    program: "codex",
    steps: (name, env, force) => {
      const steps = [];
      if (force) steps.push(["mcp", "remove", name]);
      const envFlags = Object.entries(env).flatMap(([k, v]) => [
        "--env",
        `${k}=${v}`,
      ]);
      steps.push(["mcp", "add", name, ...envFlags, "--", "npx", ...NPX_ARGS]);
      return steps;
    },
  },
  "gemini-cli": {
    kind: "delegated",
    label: "gemini-cli",
    hint: "delegates to `gemini mcp add`",
    program: "gemini",
    steps: (name, env, force) => {
      const steps = [];
      if (force) steps.push(["mcp", "remove", name]);
      const envFlags = Object.entries(env).flatMap(([k, v]) => [
        "-e",
        `${k}=${v}`,
      ]);
      steps.push([
        "mcp",
        "add",
        "-s",
        "user",
        ...envFlags,
        name,
        "npx",
        ...NPX_ARGS,
      ]);
      return steps;
    },
  },
  vscode: {
    kind: "delegated",
    label: "vscode",
    hint: "delegates to `code --add-mcp` (GitHub Copilot in VS Code)",
    program: "code",
    steps: (name, env) => [
      [
        "--add-mcp",
        JSON.stringify({
          name,
          type: "stdio",
          command: "npx",
          args: NPX_ARGS,
          env,
        }),
      ],
    ],
  },
  "copilot-cli": {
    kind: "file",
    label: "copilot-cli",
    hint: "writes ~/.copilot/mcp-config.json (GitHub Copilot CLI)",
    key: "mcpServers",
    targetPath: () =>
      homeConfig("COPILOT_CLI_CONFIG", ".copilot/mcp-config.json"),
  },
  opencode: {
    kind: "file",
    label: "opencode",
    hint: "writes opencode.jsonc",
    key: "mcp",
    targetPath: () => opencodePath(),
  },
  antigravity: {
    kind: "file",
    label: "antigravity",
    hint: "writes ~/.gemini/antigravity/mcp_config.json",
    key: "mcpServers",
    targetPath: () =>
      homeConfig("ANTIGRAVITY_CONFIG", ".gemini/antigravity/mcp_config.json"),
  },
  "antigravity-cli": {
    kind: "file",
    label: "antigravity-cli",
    hint: "writes ~/.gemini/config/mcp_config.json",
    key: "mcpServers",
    targetPath: () =>
      homeConfig("ANTIGRAVITY_CLI_CONFIG", ".gemini/config/mcp_config.json"),
  },
  "generic-json": {
    kind: "snippet",
    label: "generic-json",
    hint: "print snippet only, no file changes",
  },
};

const CLIENT_ORDER = Object.keys(CLIENTS);

// --- JSON entry shape per client (file targets) --------------------------

function serverSpec(client, env) {
  if (client === "opencode") {
    const entry = {
      type: "local",
      command: ["npx", ...NPX_ARGS],
      environment: env,
      enabled: true,
    };
    return { entry, snippet: { mcp: { suitest: entry } } };
  }
  if (client === "copilot-cli") {
    const entry = { type: "stdio", command: "npx", args: NPX_ARGS, env };
    return { entry, snippet: { mcpServers: { suitest: entry } } };
  }
  const entry = { command: "npx", args: NPX_ARGS, env };
  return { entry, snippet: { mcpServers: { suitest: entry } } };
}

// --- JSON/JSONC helpers (port of mcp.rs) ---------------------------------

function stripJsonComments(input) {
  let out = "";
  let inString = false;
  let escaped = false;
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (inString) {
      out += ch;
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      out += ch;
    } else if (ch === "/" && input[i + 1] === "/") {
      i++;
      while (i + 1 < input.length && input[i + 1] !== "\n") i++;
    } else if (ch === "/" && input[i + 1] === "*") {
      i += 2;
      while (i + 1 < input.length && !(input[i] === "*" && input[i + 1] === "/")) {
        if (input[i] === "\n") out += "\n";
        i++;
      }
      i++;
    } else {
      out += ch;
    }
  }
  return out;
}

function loadJsonObject(p) {
  if (!fs.existsSync(p)) return {};
  const raw = fs.readFileSync(p, "utf8");
  if (!raw.trim()) return {};
  const value = JSON.parse(stripJsonComments(raw));
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Config file ${p} must contain a top-level JSON object`);
  }
  return value;
}

function ensureObjectPath(root, dottedKey) {
  let current = root;
  for (const key of dottedKey.split(".")) {
    if (current[key] === undefined) current[key] = {};
    if (
      typeof current[key] !== "object" ||
      current[key] === null ||
      Array.isArray(current[key])
    ) {
      throw new Error(`Field '${key}' must be a JSON object`);
    }
    current = current[key];
  }
  return current;
}

function backupIfExists(p) {
  if (!fs.existsSync(p)) return;
  fs.copyFileSync(p, `${p}.bak`);
}

function writeJsonObject(p, root) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `${JSON.stringify(root, null, 2)}\n`);
}

function shellJoin(args) {
  return args
    .map((a) => (/^[\w\-/.:=@]+$/.test(a) ? a : `'${a.replace(/'/g, "'\\''")}'`))
    .join(" ");
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// --- install one client ---------------------------------------------------

function installClient(clientId, { name, scope, env, print, dryRun, force }) {
  const client = CLIENTS[clientId];
  if (!client) throw new Error(`unknown client: ${clientId}`);
  const { entry, snippet } = serverSpec(clientId, env);

  if (client.kind === "snippet") {
    process.stdout.write(`${JSON.stringify(snippet, null, 2)}\n`);
    return;
  }

  if (client.kind === "delegated") {
    const steps = client.steps(name, env, force);
    const preview = steps
      .map((s) => `${client.program} ${shellJoin(s)}`)
      .join(" && ");
    if (print || dryRun) process.stdout.write(`${preview}\n`);
    if (dryRun) {
      process.stdout.write("Dry run, no client command executed.\n");
      return;
    }
    for (const s of steps) {
      const res = spawnSync(client.program, s, { stdio: "inherit" });
      if (res.error && res.error.code === "ENOENT") {
        throw new Error(
          `${client.program} CLI not found on PATH — install it, then retry.`,
        );
      }
      // `force` remove may fail if the entry is absent; ignore that one.
      if (res.status !== 0 && !(force && s[1] === "remove")) {
        throw new Error(`${client.program} exited with status ${res.status}`);
      }
    }
    process.stdout.write(`Installed MCP entry '${name}' via ${client.label}\n`);
    return;
  }

  // file target
  const target = client.targetPath(scope);
  const root = loadJsonObject(target);
  const bag = ensureObjectPath(root, client.key);

  if (bag[name] !== undefined) {
    if (deepEqual(bag[name], entry)) {
      process.stdout.write(
        `MCP entry '${name}' already configured at ${target}\n`,
      );
      return;
    }
    if (!force) {
      throw new Error(
        `MCP entry '${name}' already exists at ${target}. Re-run with --force to overwrite.`,
      );
    }
  }

  bag[name] = entry;
  if (print || dryRun) {
    process.stdout.write(`${JSON.stringify(snippet, null, 2)}\n`);
  }
  if (dryRun) {
    process.stdout.write(`Dry run, no file written. Target: ${target}\n`);
    return;
  }
  backupIfExists(target);
  writeJsonObject(target, root);
  process.stdout.write(
    `Installed MCP entry '${name}' for ${client.label} at ${target}\n`,
  );
}

// --- doctor ---------------------------------------------------------------

function commandExists(program) {
  const probe = spawnSync(program, ["--version"], { stdio: "ignore" });
  return !(probe.error && probe.error.code === "ENOENT");
}

function doctor(only) {
  process.stdout.write("MCP doctor\n──────────\n");

  const py = findPython();
  process.stdout.write(
    py
      ? `[ok] Python ${py.version} on PATH (${py.cmd})\n`
      : "[warn] Python >= 3.11 not found on PATH (set SUITEST_PYTHON)\n",
  );

  const saved = creds.loadCreds();
  process.stdout.write(
    saved
      ? `[ok] Credentials saved at ${creds.credsPath()}\n`
      : "[warn] No saved credentials — run `suitest-mcp login`\n",
  );

  const ids = only ? [only] : CLIENT_ORDER;
  for (const id of ids) {
    const client = CLIENTS[id];
    if (client.kind === "delegated") {
      process.stdout.write(
        commandExists(client.program)
          ? `[ok] ${client.label} CLI found: ${client.program}\n`
          : `[warn] ${client.label} CLI missing: ${client.program}\n`,
      );
    } else if (client.kind === "file") {
      const p = client.targetPath("global");
      process.stdout.write(
        fs.existsSync(p)
          ? `[ok] ${client.label} config exists: ${p}\n`
          : `[info] ${client.label} config will be created: ${p}\n`,
      );
    } else {
      process.stdout.write(`[ok] ${client.label} available (print-only)\n`);
    }
  }
}

// --- interactive orchestration -------------------------------------------

async function runInteractive(opts) {
  process.stdout.write("suitest-mcp install — interactive setup\n");
  process.stdout.write("─".repeat(38) + "\n\n");

  const py = findPython();
  process.stdout.write(
    py
      ? `[ok]   Python interpreter: ${py.cmd} (${py.version})\n`
      : "[fail] Python >= 3.11 not found on PATH\n",
  );
  const saved = creds.loadCreds();
  process.stdout.write(
    saved
      ? "[ok]   Credentials saved (reused automatically)\n"
      : "[info] No saved credentials — you'll be asked once\n",
  );
  process.stdout.write("\n");

  if (!py) {
    throw new Error(
      "Python >= 3.11 is required to run the server. Install from https://python.org, then retry.",
    );
  }

  const items = CLIENT_ORDER.map((id) => ({
    value: id,
    label: CLIENTS[id].label,
    hint: CLIENTS[id].hint,
  }));
  const clientId = await picker.select("Pick the MCP client to install into:", items);

  const resolved = await creds.resolveCreds(opts);
  const env = {
    SUITEST_API_URL: resolved.apiUrl,
    SUITEST_API_KEY: resolved.apiKey,
  };
  if (resolved.warn) {
    process.stderr.write(
      "[warn] Using placeholder credentials — edit the config or run `suitest-mcp login`.\n",
    );
  }
  installClient(clientId, { ...opts, env });
}

// --- arg parsing + entrypoints -------------------------------------------

function parseArgs(argv) {
  const out = {
    client: null,
    name: "suitest",
    scope: "global",
    print: false,
    dryRun: false,
    force: false,
    apiUrl: undefined,
    apiKey: undefined,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--client":
        out.client = argv[++i];
        break;
      case "--name":
        out.name = argv[++i];
        break;
      case "--scope":
        out.scope = argv[++i];
        break;
      case "--api-url":
        out.apiUrl = argv[++i];
        break;
      case "--api-key":
        out.apiKey = argv[++i];
        break;
      case "--print":
        out.print = true;
        break;
      case "--dry-run":
        out.dryRun = true;
        break;
      case "--force":
        out.force = true;
        break;
      default:
        throw new Error(`unknown flag: ${a}`);
    }
  }
  return out;
}

async function handleInstall(argv) {
  const opts = parseArgs(argv);
  if (!opts.client) {
    return runInteractive(opts);
  }
  if (!CLIENTS[opts.client]) {
    throw new Error(
      `unknown --client '${opts.client}'. Choose from: ${CLIENT_ORDER.join(", ")}`,
    );
  }
  const resolved = await creds.resolveCreds(opts);
  if (resolved.warn) {
    process.stderr.write(
      "[warn] No credentials — writing placeholders. Run `suitest-mcp login` or pass --api-url/--api-key.\n",
    );
  }
  const env = {
    SUITEST_API_URL: resolved.apiUrl,
    SUITEST_API_KEY: resolved.apiKey,
  };
  installClient(opts.client, { ...opts, env });
}

async function handleLogin() {
  if (!process.stdin.isTTY) {
    throw new Error(
      "login needs a TTY. Non-interactive? Pass --api-url/--api-key to install, or set SUITEST_API_URL/KEY.",
    );
  }
  const existing = creds.loadCreds() || {};
  const entered = await creds.promptCreds(existing);
  if (!entered) {
    throw new Error("login cancelled — both URL and key are required.");
  }
  const p = creds.saveCreds(entered);
  process.stdout.write(`Saved credentials to ${p} (chmod 600).\n`);
}

function handleDoctor(argv) {
  const opts = parseArgs(argv);
  doctor(opts.client || null);
}

module.exports = {
  CLIENTS,
  CLIENT_ORDER,
  serverSpec,
  stripJsonComments,
  loadJsonObject,
  ensureObjectPath,
  installClient,
  parseArgs,
  handleInstall,
  handleLogin,
  handleDoctor,
};
