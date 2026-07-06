"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const http = require("node:http");

const { ensureApiKey } = require("../lib/api-key.js");

// Stub mirrors the real API contract (verified against apps/api source):
// - POST /auth/cookie/login (app root, NOT /api/v1) -> 204 + suitest_session cookie
// - GET /api/v1/workspaces -> plain list[WorkspacePublic], id field is `id`
// - POST /api/v1/workspaces/{id}/api-keys -> 201, ApiKeyCreated has `key`
// - GET /api/v1/api-keys/whoami -> 200 when X-API-Key is valid
function stubApi({ mintedKey = "sk_suitest_new" } = {}) {
  const calls = [];
  const srv = http.createServer((req, res) => {
    calls.push(`${req.method} ${req.url}`);
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      if (req.url === "/api/v1/api-keys/whoami") {
        const ok = req.headers["x-api-key"] === "sk_suitest_valid";
        res.statusCode = ok ? 200 : 401;
        return res.end(ok ? "{}" : "");
      }
      if (req.url === "/auth/cookie/login" && req.method === "POST") {
        assert.match(body, /username=admin%40suitest\.local/);
        res.statusCode = 204;
        res.setHeader("set-cookie", "suitest_session=abc; HttpOnly; Path=/");
        return res.end();
      }
      if (req.url === "/api/v1/workspaces") {
        assert.strictEqual(req.headers.cookie, "suitest_session=abc");
        res.setHeader("content-type", "application/json");
        return res.end(JSON.stringify([{ id: "ws_1", name: "Default Workspace" }]));
      }
      if (req.url === "/api/v1/workspaces/ws_1/api-keys" && req.method === "POST") {
        res.statusCode = 201;
        res.setHeader("content-type", "application/json");
        return res.end(JSON.stringify({ key: mintedKey, name: "local-launcher" }));
      }
      res.statusCode = 500;
      res.end();
    });
  });
  return new Promise((resolve) =>
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, base: `http://127.0.0.1:${srv.address().port}` }),
    ),
  );
}

const CREDS = { email: "admin@suitest.local", password: "pw", apiKey: null };

test("mints key via login -> workspaces -> api-keys", async () => {
  const { srv, base } = await stubApi();
  try {
    const key = await ensureApiKey(base, { ...CREDS });
    assert.strictEqual(key, "sk_suitest_new");
  } finally {
    srv.close();
  }
});

test("existing valid key short-circuits (whoami 200)", async () => {
  const { srv, calls, base } = await stubApi();
  try {
    const key = await ensureApiKey(base, { ...CREDS, apiKey: "sk_suitest_valid" });
    assert.strictEqual(key, "sk_suitest_valid");
    assert.deepStrictEqual(calls, ["GET /api/v1/api-keys/whoami"]);
  } finally {
    srv.close();
  }
});

test("stale key falls through to re-mint", async () => {
  const { srv, base } = await stubApi();
  try {
    const key = await ensureApiKey(base, { ...CREDS, apiKey: "sk_suitest_stale" });
    assert.strictEqual(key, "sk_suitest_new");
  } finally {
    srv.close();
  }
});
