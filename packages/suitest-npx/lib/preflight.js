"use strict";

// Consent-based prerequisite check for onboard/up. The only real system
// prerequisite is `uv` (it downloads Python 3.12 and installs the wheels itself).
// When `uv` is missing we print a short report and — on a TTY, with consent —
// run the correct per-OS installer, then refresh PATH in-process so onboarding
// continues in the same terminal instead of dying with an error.

const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const readline = require("node:readline/promises");
const { spawnSync } = require("node:child_process");

const { uvInstallCommand, uvInstallHint } = require("./venv.js");

// ponytail: stdlib spawn probe, no lookpath dep — matches requireUv in venv.js.
function checkTool(cmd, args = ["--version"]) {
  const probe = spawnSync(cmd, args, { stdio: "ignore" });
  return !probe.error && probe.status === 0;
}

// uv's default install targets. A just-installed uv is written here but is NOT
// on the current process PATH — we add these so `execFileSync("uv", …)` resolves
// without asking the user to open a fresh terminal.
function uvBinCandidates(platform = process.platform, env = process.env) {
  const home = os.homedir();
  const dirs =
    platform === "win32"
      ? [env.UV_INSTALL_DIR, path.join(home, ".local", "bin")]
      : [
          env.UV_INSTALL_DIR,
          env.XDG_BIN_HOME,
          path.join(home, ".local", "bin"),
          path.join(home, ".cargo", "bin"),
        ];
  return dirs.filter((d) => d && fs.existsSync(d));
}

function refreshUvPath(platform = process.platform, env = process.env) {
  const sep = platform === "win32" ? ";" : ":";
  const add = uvBinCandidates(platform, env);
  if (add.length === 0) return;
  env.PATH = [...add, env.PATH || ""].join(sep);
}

// { file, args } for spawnSync + the tool the installer pipe needs.
function installerFor(platform = process.platform) {
  const command = uvInstallCommand(platform);
  return platform === "win32"
    ? { file: "cmd", args: ["/c", command], prereq: "powershell" }
    : { file: "sh", args: ["-c", command], prereq: "curl" };
}

async function askYesNo(question, { defaultYes = true } = {}) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await rl.question(question + " ")).trim().toLowerCase();
    if (!answer) return defaultYes;
    return answer === "y" || answer === "yes";
  } finally {
    rl.close();
  }
}

function installUv(platform = process.platform) {
  const { file, args, prereq } = installerFor(platform);
  if (!checkTool(prereq, platform === "win32" ? ["-Command", "$PSVersionTable"] : ["--version"])) {
    throw new Error(
      `Can't auto-install uv: \`${prereq}\` is missing too. Install uv manually:\n` +
        uvInstallHint(platform),
    );
  }
  console.log("Installing uv...");
  const run = spawnSync(file, args, { stdio: "inherit" });
  if (run.error || run.status !== 0) {
    throw new Error("uv install failed. Install it manually:\n" + uvInstallHint(platform));
  }
  refreshUvPath(platform);
}

const isTTY = () => Boolean(process.stdin.isTTY && process.stdout.isTTY);

// Report present/missing prerequisites, then (with consent) install uv.
async function preflight(opts = {}, platform = process.platform) {
  if (checkTool("uv")) return; // happy path: quiet, no noise.

  const installer = installerFor(platform);
  const prereqOk = checkTool(
    installer.prereq,
    platform === "win32" ? ["-Command", "$PSVersionTable"] : ["--version"],
  );
  console.log("Checking prerequisites:");
  console.log("  uv (python runtime manager) ... not found");
  console.log(`  ${installer.prereq} (installer)        ... ${prereqOk ? "ok" : "not found"}`);

  // Explicit non-interactive consent (--yes) may proceed; otherwise no TTY = no
  // way to ask for consent, so fall back to the manual hint (CI stays deterministic).
  if (!isTTY() && !opts.yes) {
    throw new Error(uvInstallHint(platform));
  }
  if (!opts.yes) {
    const consent = await askYesNo("Install uv now? [Y/n]", { defaultYes: true });
    if (!consent) throw new Error(uvInstallHint(platform));
  }

  installUv(platform);
  if (!checkTool("uv")) {
    // Installed but still not resolvable — PATH couldn't be picked up in-process.
    throw new Error(uvInstallHint(platform));
  }
}

module.exports = {
  checkTool,
  uvBinCandidates,
  refreshUvPath,
  installerFor,
  askYesNo,
  installUv,
  preflight,
};
