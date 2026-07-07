"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const pkg = require("../package.json");

const REGISTRY_URL = `https://registry.npmjs.org/${pkg.name}/latest`;
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

function cacheFile() {
  return path.join(os.homedir(), ".suitest", "update-check.json");
}

// "0.1.10" > "0.1.9" — plain string compare fails on this, so numeric per part.
function isNewer(latest, current) {
  const a = String(latest).split(".").map(Number);
  const b = String(current).split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const d = (a[i] || 0) - (b[i] || 0);
    if (d !== 0) return d > 0;
  }
  return false;
}

async function fetchLatest(timeoutMs = 2000) {
  const res = await fetch(REGISTRY_URL, { signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`registry HTTP ${res.status}`);
  const body = await res.json();
  if (!body.version) throw new Error("registry response missing version");
  return body.version;
}

// Passive check: never throws, never slows boot by more than the fetch timeout,
// caches for 24h so repeated commands (and offline machines) stay quiet.
async function checkForUpdate({ force = false } = {}) {
  const file = cacheFile();
  if (!force) {
    try {
      const cached = JSON.parse(fs.readFileSync(file, "utf8"));
      if (Date.now() - cached.checkedAt < CACHE_TTL_MS) {
        return isNewer(cached.latest, pkg.version) ? cached.latest : null;
      }
    } catch {
      // no cache yet / unreadable — fall through to a live check
    }
  }
  try {
    const latest = await fetchLatest();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ checkedAt: Date.now(), latest }) + "\n");
    return isNewer(latest, pkg.version) ? latest : null;
  } catch {
    return null; // offline / registry down — never block the actual command
  }
}

function updateNotice(latest) {
  return `
Update available: ${pkg.version} → ${latest}
Run: npx ${pkg.name}@latest up`;
}

module.exports = { isNewer, checkForUpdate, updateNotice, fetchLatest };
