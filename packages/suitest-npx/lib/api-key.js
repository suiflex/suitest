"use strict";

// Mint the local API key: superadmin cookie login (fastapi-users) -> first
// workspace -> POST api-keys. The plaintext key is returned exactly once;
// the caller persists it in .suitest/credentials.json (mode 600).
//
// Verified against apps/api: login lives at /auth/cookie/login (the auth
// router is mounted at the app root, unlike the /api/v1-prefixed routers)
// and returns 204 + a suitest_session cookie; ApiKeyCreated exposes the
// plaintext as `key`; WorkspacePublic uses `id`.

async function login(base, creds) {
  const res = await fetch(base + "/auth/cookie/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: creds.email, password: creds.password }),
    redirect: "manual",
  });
  if (res.status >= 400) {
    throw new Error(
      `superadmin login failed (HTTP ${res.status}) — check .suitest/credentials.json vs DB`,
    );
  }
  const cookie = res.headers.get("set-cookie");
  if (!cookie || !cookie.includes("suitest_session")) {
    throw new Error("login succeeded but no suitest_session cookie returned");
  }
  return cookie.split(";")[0];
}

async function ensureApiKey(base, creds) {
  if (creds.apiKey) {
    const ok = await fetch(base + "/api/v1/api-keys/whoami", {
      headers: { "X-API-Key": creds.apiKey },
    });
    if (ok.status === 200) return creds.apiKey;
  }
  const cookie = await login(base, creds);

  const wsRes = await fetch(base + "/api/v1/workspaces", { headers: { Cookie: cookie } });
  if (!wsRes.ok) throw new Error(`list workspaces failed (HTTP ${wsRes.status})`);
  const workspaces = await wsRes.json();
  if (!Array.isArray(workspaces) || workspaces.length === 0) {
    throw new Error("no workspace found after superadmin bootstrap");
  }
  const wsId = workspaces[0].id;

  const keyRes = await fetch(base + `/api/v1/workspaces/${wsId}/api-keys`, {
    method: "POST",
    headers: { Cookie: cookie, "Content-Type": "application/json" },
    body: JSON.stringify({ name: "local-launcher" }),
  });
  if (keyRes.status !== 201) {
    throw new Error(`mint api key failed (HTTP ${keyRes.status})`);
  }
  const created = await keyRes.json();
  if (!created.key) throw new Error("api key response missing plaintext key field");
  return created.key;
}

module.exports = { ensureApiKey };
