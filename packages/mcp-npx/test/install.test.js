#!/usr/bin/env node
/**
 * Installer unit checks — no framework, just node:assert, mirroring smoke.test.js.
 * Exercises the pure logic (spec shape, JSON merge, idempotency, JSONC, paths)
 * without touching real client configs: every target is redirected via env.
 */

"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { PassThrough } = require("node:stream");

const install = require("../lib/install.js");
const creds = require("../lib/creds.js");
const { multiselect } = require("../lib/picker.js");

const KEY_ESC = "\x1b";
const KEY_ENTER = "\r";
const KEY_DOWN = "\x1b[B";
const KEY_SPACE = " ";

const ENV = { SUITEST_API_URL: "http://localhost:4000", SUITEST_API_KEY: "sk_test" };

function tmp(name) {
  const p = path.join(
    os.tmpdir(),
    `suitest-mcp-test-${process.pid}-${name}`,
  );
  fs.rmSync(p, { recursive: true, force: true });
  return p;
}

function silence(fn) {
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = () => true;
  try {
    return fn();
  } finally {
    process.stdout.write = orig;
  }
}

// 1. serverSpec shape (default mcpServers client)
{
  const { entry, snippet } = install.serverSpec("claude-code", ENV);
  assert.strictEqual(entry.command, "npx");
  assert.deepStrictEqual(entry.args, ["-y", "@suiflex/suitest-mcp"]);
  assert.deepStrictEqual(entry.env, ENV);
  assert.ok(snippet.mcpServers.suitest, "snippet has mcpServers.suitest");
}

// 2. opencode variant uses `mcp` + command array + environment
{
  const { entry, snippet } = install.serverSpec("opencode", ENV);
  assert.strictEqual(entry.type, "local");
  assert.deepStrictEqual(entry.command, ["npx", "-y", "@suiflex/suitest-mcp"]);
  assert.deepStrictEqual(entry.environment, ENV);
  assert.ok(snippet.mcp.suitest, "snippet has mcp.suitest");
}

// 3. Codex delegates the exact stdio command and env expected by its CLI.
{
  const steps = install.CLIENTS.codex.steps("suitest", ENV, false);
  assert.deepStrictEqual(steps, [
    [
      "mcp",
      "add",
      "suitest",
      "--env",
      "SUITEST_API_URL=http://localhost:4000",
      "--env",
      "SUITEST_API_KEY=sk_test",
      "--",
      "npx",
      "-y",
      "@suiflex/suitest-mcp",
    ],
  ]);
}

// 4. Antigravity uses the same portable mcpServers stdio shape as Claude.
{
  const antigravity = install.serverSpec("antigravity", ENV);
  const claude = install.serverSpec("claude-code", ENV);
  assert.deepStrictEqual(antigravity, claude);

  const target = tmp("antigravity.json");
  process.env.ANTIGRAVITY_CONFIG = target;
  silence(() => install.installClient("antigravity", {
    name: "suitest",
    scope: "global",
    env: ENV,
    print: false,
    dryRun: false,
    force: false,
  }));
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(target, "utf8")), antigravity.snippet);
  fs.rmSync(target, { force: true });
  delete process.env.ANTIGRAVITY_CONFIG;
}

// 4b. hermes delegates with --command/--arg flags and one space-separated
//     --env value (repeating the flag overwrites earlier pairs).
{
  const steps = install.CLIENTS.hermes.steps("suitest", ENV, false);
  assert.deepStrictEqual(steps, [
    ["mcp", "add", "suitest", "--command", "npx"],
    ["mcp", "add", "suitest", "--arg", "-y"],
    ["mcp", "add", "suitest", "--arg", "@suiflex/suitest-mcp"],
    [
      "mcp",
      "add",
      "suitest",
      "--env",
      "SUITEST_API_URL=http://localhost:4000 SUITEST_API_KEY=sk_test",
    ],
  ]);

  const forced = install.CLIENTS.hermes.steps("suitest", ENV, true);
  assert.deepStrictEqual(forced[0], ["mcp", "remove", "suitest"]);
}

// 4c. openclaw nests under mcp.servers and names the transport.
{
  const { entry, snippet } = install.serverSpec("openclaw", ENV);
  assert.strictEqual(entry.transport, "stdio");
  assert.strictEqual(entry.command, "npx");
  assert.deepStrictEqual(entry.args, ["-y", "@suiflex/suitest-mcp"]);
  assert.ok(snippet.mcp.servers.suitest, "snippet has mcp.servers.suitest");

  const target = tmp("openclaw.json");
  process.env.OPENCLAW_CONFIG = target;
  // Preserve an unrelated existing entry to prove the merge is an upsert.
  fs.writeFileSync(
    target,
    JSON.stringify({ mcp: { servers: { docs: { url: "https://example.test" } } } }),
  );
  silence(() => install.installClient("openclaw", {
    name: "suitest",
    scope: "global",
    env: ENV,
    print: false,
    dryRun: false,
    force: false,
  }));
  const written = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.strictEqual(written.mcp.servers.docs.url, "https://example.test");
  assert.strictEqual(written.mcp.servers.suitest.transport, "stdio");
  fs.rmSync(target, { force: true });
  delete process.env.OPENCLAW_CONFIG;
}

// 4d. cline/roo write {type: stdio} into the VS Code extension profile when it
//     exists, and skip with a notice when the extension never ran here.
{
  const { entry } = install.serverSpec("cline", ENV);
  assert.strictEqual(entry.type, "stdio");
  assert.strictEqual(entry.command, "npx");

  const home = tmp("vscode-home");
  const base = path.join(
    home,
    process.platform === "win32"
      ? path.join("AppData", "Roaming", "Code", "User")
      : process.platform === "darwin"
        ? path.join("Library", "Application Support", "Code", "User")
        : path.join(".config", "Code", "User"),
  );
  const ext = path.join(base, "globalStorage", "saoudrizwan.claude-dev");
  fs.mkdirSync(ext, { recursive: true });

  // The profile directory is discovered through os.homedir(), so point HOME
  // (and USERPROFILE on Windows) at the fixture for the duration.
  const prevHome = process.env.HOME;
  const prevProfile = process.env.USERPROFILE;
  process.env.HOME = home;
  process.env.USERPROFILE = home;
  try {
    silence(() => install.installClient("cline", {
      name: "suitest",
      scope: "global",
      env: ENV,
      print: false,
      dryRun: false,
      force: false,
    }));
    const settings = JSON.parse(
      fs.readFileSync(path.join(ext, "settings", "cline_mcp_settings.json"), "utf8"),
    );
    assert.strictEqual(settings.mcpServers.suitest.type, "stdio");

    // Without the profile directory the install is skipped, not written.
    fs.rmSync(path.join(base, "globalStorage"), { recursive: true, force: true });
    let out = "";
    const orig = process.stdout.write.bind(process.stdout);
    process.stdout.write = (s) => {
      out += s;
      return true;
    };
    try {
      install.installClient("roo", {
        name: "suitest",
        scope: "global",
        env: ENV,
        print: false,
        dryRun: false,
        force: false,
      });
    } finally {
      process.stdout.write = orig;
    }
    assert.match(out, /\[skip\] roo/);
  } finally {
    if (prevHome === undefined) delete process.env.HOME;
    else process.env.HOME = prevHome;
    if (prevProfile === undefined) delete process.env.USERPROFILE;
    else process.env.USERPROFILE = prevProfile;
    fs.rmSync(home, { recursive: true, force: true });
  }
}

// 9. write into an empty claude-code config, then idempotency + conflict
{
  const target = tmp("claude.json");
  process.env.CLAUDE_CODE_CONFIG = target;
  const opts = {
    name: "suitest",
    scope: "global",
    env: ENV,
    print: false,
    dryRun: false,
    force: false,
  };

  silence(() => install.installClient("claude-code", opts));
  const written = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.strictEqual(written.mcpServers.suitest.command, "npx");

  // second identical run is a no-op (no throw)
  silence(() => install.installClient("claude-code", opts));

  // different env without --force -> throws
  const conflict = { ...opts, env: { ...ENV, SUITEST_API_KEY: "sk_other" } };
  assert.throws(
    () => silence(() => install.installClient("claude-code", conflict)),
    /already exists/,
  );

  // with --force -> overwrites
  silence(() =>
    install.installClient("claude-code", { ...conflict, force: true }),
  );
  const after = JSON.parse(fs.readFileSync(target, "utf8"));
  assert.strictEqual(after.mcpServers.suitest.env.SUITEST_API_KEY, "sk_other");

  fs.rmSync(target, { force: true });
  fs.rmSync(`${target}.bak`, { force: true });
  delete process.env.CLAUDE_CODE_CONFIG;
}

// 6. stripJsonComments handles JSONC (opencode config)
{
  const parsed = install.loadJsonObject; // ensure export present
  assert.strictEqual(typeof parsed, "function");
  const jsonc = '// top\n{\n  /* block */\n  "mcp": { "a": 1 }\n}\n';
  const stripped = install.stripJsonComments(jsonc);
  assert.deepStrictEqual(JSON.parse(stripped), { mcp: { a: 1 } });
}

// 7. credsPath honours XDG_CONFIG_HOME
{
  const prev = process.env.XDG_CONFIG_HOME;
  const prevDir = process.env.SUITEST_CONFIG_DIR;
  delete process.env.SUITEST_CONFIG_DIR;
  process.env.XDG_CONFIG_HOME = "/tmp/xdg-test";
  assert.strictEqual(
    creds.credsPath(),
    path.join("/tmp/xdg-test", "suitest", "credentials.json"),
  );
  if (prev === undefined) delete process.env.XDG_CONFIG_HOME;
  else process.env.XDG_CONFIG_HOME = prev;
  if (prevDir !== undefined) process.env.SUITEST_CONFIG_DIR = prevDir;
}

// 8. interactiveLogin: Esc on "use saved creds?" goes back to "log in now?"
// instead of aborting — feed Esc then re-answer Yes/Yes to land on the saved creds.
(async () => {
  const prevDir = process.env.SUITEST_CONFIG_DIR;
  const dir = tmp("interactive-login-back");
  process.env.SUITEST_CONFIG_DIR = dir;
  creds.saveCreds({ apiUrl: "http://127.0.0.1:4000", apiKey: "sk_saved" });

  const input = new PassThrough();
  const output = new PassThrough();
  output.on("data", () => {});

  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  const p = install.interactiveLogin({}, { input, output });
  await delay(20);
  input.write(KEY_ENTER); // "log in now?" -> Yes (default)
  await delay(20);
  input.write(KEY_ESC); // "use saved creds?" -> back
  // readline debounces a lone ESC to distinguish it from the start of an
  // escape sequence (e.g. arrow keys) — give its internal timeout room to
  // fire before sending the next key, or they get parsed as one sequence.
  await delay(600);
  input.write(KEY_ENTER); // "log in now?" again -> Yes
  await delay(20);
  input.write(KEY_ENTER); // "use saved creds?" -> Yes (default)

  const resolved = await p;
  assert.strictEqual(resolved.apiUrl, "http://127.0.0.1:4000");
  assert.strictEqual(resolved.apiKey, "sk_saved");
  assert.strictEqual(resolved.warn, false);

  fs.rmSync(dir, { recursive: true, force: true });
  if (prevDir === undefined) delete process.env.SUITEST_CONFIG_DIR;
  else process.env.SUITEST_CONFIG_DIR = prevDir;

  // 9. multiselect() -> install into every picked client (this is the exact
  // pattern install.js's runInteractive() follows: multiselect then loop).
  {
    const claudeTarget = tmp("multi-client-claude.json");
    const cursorTarget = tmp("multi-client-cursor.json");
    const prevClaude = process.env.CLAUDE_CODE_CONFIG;
    const prevCursor = process.env.CURSOR_CONFIG;
    process.env.CLAUDE_CODE_CONFIG = claudeTarget;
    process.env.CURSOR_CONFIG = cursorTarget;

    const items = install.CLIENT_ORDER.map((id) => ({
      value: id,
      label: install.CLIENTS[id].label,
      hint: install.CLIENTS[id].hint,
    }));

    const mInput = new PassThrough();
    const mOutput = new PassThrough();
    mOutput.on("data", () => {});
    const picked = multiselect("Pick the MCP client(s) to install into:", items, {
      input: mInput,
      output: mOutput,
    });
    // CLIENT_ORDER is [claude-code, claude-desktop, cursor, ...] — check
    // claude-code, skip claude-desktop (no safe env-redirected target, would
    // touch the real Claude Desktop config dir), land on cursor and check it.
    await delay(20);
    mInput.write(KEY_SPACE); // check claude-code
    await delay(20);
    mInput.write(KEY_DOWN);
    await delay(20);
    mInput.write(KEY_DOWN); // now on cursor
    await delay(20);
    mInput.write(KEY_SPACE); // check cursor
    await delay(20);
    mInput.write(KEY_ENTER);

    const clientIds = await picked;
    assert.deepStrictEqual(clientIds.sort(), ["claude-code", "cursor"]);

    for (const clientId of clientIds) {
      silence(() => install.installClient(clientId, { name: "suitest", scope: "global", env: ENV }));
    }
    assert.ok(fs.existsSync(claudeTarget), "expected claude-code config to be written");
    assert.ok(fs.existsSync(cursorTarget), "expected cursor config to be written");

    fs.rmSync(claudeTarget, { force: true });
    fs.rmSync(cursorTarget, { force: true });
    if (prevClaude === undefined) delete process.env.CLAUDE_CODE_CONFIG;
    else process.env.CLAUDE_CODE_CONFIG = prevClaude;
    if (prevCursor === undefined) delete process.env.CURSOR_CONFIG;
    else process.env.CURSOR_CONFIG = prevCursor;
  }

  process.stdout.write("install.test.js OK\n");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
