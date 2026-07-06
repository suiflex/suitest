---
title: Configuration reference
description: Every field of suitest.config.json, including auth, server, dependencies, publish, and the blackbox ui section, with types and defaults.
---

`suitest.config.json` is the front door of the testing lifecycle: one plain JSON file that tells Suitest what to test, how to start it, how to authenticate, and where to publish results. The MCP server, the lifecycle CLI, and `suitest ci` all read the same file.

The fastest way to create one is the setup wizard (`bootstrap_project` MCP tool) or `npx -y @suiflex/suitest-mcp init`. This page documents every field for hand-editing.

## Top-level fields

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mode` | string | **required** | `backend` or `frontend`. Decides analyzers, generators, and the runner. |
| `projectName` | string | directory name of `projectPath` | Display name used in reports and publishing. |
| `projectPath` | string | `"."` | Path to the project checkout, relative to the config file. Must exist when `analysisSource` is `repo`; optional for no-repo sources. |
| `baseUrl` | string | **required** | Target base URL, e.g. `http://localhost:4000`. When a `ui` section provides `targetUrl`, that value is used as the fallback. |
| `apiBasePath` | string | `"/api"` | API prefix appended to `baseUrl` (backend only). |
| `readyPath` | string | `/api/health` (backend) / `/` (frontend) | Readiness probe path polled before tests run. |
| `port` | integer | derived from `baseUrl` | Target port; only set it when the URL does not carry it. |
| `scope` | string | `"codebase"` | `codebase` (test everything) or `diff` (test what changed). |
| `analysisSource` | string | `"repo"` | Where test discovery comes from: `repo` (static source analysis), `openapi` (OpenAPI spec, backend), `postman` (Postman v2 collection, backend), `crawl` (live DOM crawl, frontend). A frontend config with a `ui.mode: "blackbox"` section defaults to `blackbox` unless pinned. |
| `openapiUrl` | string | `""` | URL or path to `openapi.json` (`analysisSource: openapi`). |
| `openapiFile` | string | `""` | Local OpenAPI file, relative to the config. |
| `postmanFile` | string | `""` | Local Postman v2 collection, relative to the config. |
| `testIds` | string[] | `[]` | Run only these case ids; empty means all. |
| `additionalInstruction` | string | `""` | Free-text instruction blended into planning. |
| `enrich` | boolean | `false` | LLM enrichment of the plan (uses the Suitest LLM proxy when reachable). |
| `prdFile` | string | `""` | Markdown product spec; when set and an LLM bridge is reachable, the plan is PRD-driven on top of the deterministic baseline. |
| `codegen` | string | `"auto"` | Frontend codegen strategy: `auto` (deterministic archetypes first, LLM fills the rest), `llm` (LLM writes every frontend test body), `deterministic` (archetypes only; unknown cases fail loud). |
| `output` | string | `"suitest-output"` | Output directory for generated tests, reports, and evidence, relative to the config. |
| `auth` | object | see below | How generated tests authenticate against the target. |
| `server` | object | see below | How Suitest starts and stops the target. |
| `dependencies` | object[] | `[]` | Supporting services to start before the target. |
| `publish` | object | see below | Publishing results into a running Suitest server. |
| `ui` | object | absent | Blackbox DOM engine settings (frontend, no repo). |

:::caution
A no-repo backend (`analysisSource` other than `repo` in `backend` mode) **must** bring an API contract: set one of `openapiUrl`, `openapiFile`, or `postmanFile`, otherwise loading the config fails. Blackbox-from-URL alone is not enough to generate reliable backend tests.
:::

## `auth`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `type` | string | `"none"` | `none`, `bearer`, or `basic`. |
| `loginPath` | string | `"/api/auth/login"` | Login endpoint used to obtain a token (`bearer`). |
| `username` | string | `""` | Test credential username/email. |
| `password` | string | `""` | Test credential password. |
| `tokenField` | string | `"token"` | JSON field holding the bearer token in the login response. |
| `usernameField` | string | `"email"` | Request-body key for the username/email. |
| `passwordField` | string | `"password"` | Request-body key for the password. |

## `server`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `autostart` | boolean | `true` | Whether Suitest spawns the target itself. |
| `startCommand` | string | `""` | Command to start the target, e.g. `npm run dev`. Required when `autostart` is true (empty raises a config error). |
| `cwd` | string | `"."` | Working directory for the start command, relative to `projectPath`. |
| `readyTimeoutSec` | integer | `60` | Max seconds to wait for readiness. |
| `readyLogPattern` | string | `""` | Optional substring/regex in stdout marking the target ready. |
| `env` | object | `{}` | Extra environment variables for the spawned process. |
| `stopGraceSec` | integer | `5` | Grace period before the process is killed on teardown. |

## `dependencies[]`

Supporting services started (and readiness-gated) in order before the main target, then torn down after the run. Example: the backend a frontend run needs for login and API calls.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | directory name of `cwd` | Label used in logs. |
| `startCommand` | string | **required** | Command to start the dependency. |
| `cwd` | string | `"."` | Working directory, relative to the config file. |
| `baseUrl` | string | **required** | Base URL of the dependency. |
| `readyPath` | string | `"/"` | Readiness probe path. |
| `port` | integer | derived from `baseUrl` | Dependency port. |
| `readyTimeoutSec` | integer | `60` | Max seconds to wait for readiness. |
| `readyLogPattern` | string | `""` | Optional readiness marker in stdout. |
| `env` | object | `{}` | Extra environment variables. |
| `stopGraceSec` | integer | `5` | Teardown grace period. |

## `publish`

Publishes lifecycle results into a running Suitest server (REST ingest), so cases, runs, and evidence land in the web TCM.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | boolean | `false` | Turn publishing on. |
| `apiUrl` | string | `"http://localhost:4000"` | Suitest server URL. |
| `token` | string | `""` | API token. |
| `workspaceId` | string | `""` | Target workspace id. |
| `projectId` | string | `""` | Target project id. Once set, publishes are pinned to this project. |
| `suiteName` | string | `""` | Suite to publish into. |
| `recreateProject` | boolean | `false` | EXPLICIT opt-in: when the configured `projectId` no longer exists and repair finds no match, create a fresh project. Also settable via the `resetProjectBinding` key, the `SUITEST_RECREATE_PROJECT=1` environment variable, or the `recreate_project` MCP tool argument. Without it, a stale binding fails the run and nothing is inserted. |

## `ui` (blackbox engine)

Configures no-repo frontend testing from a URL. Present only for `mode: "frontend"`. See the [blackbox testing guide](/docs/guides/blackbox-testing/).

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mode` | string | `"blackbox"` | Engine mode marker. |
| `targetUrl` | string | `""` | App URL to test; falls back to `baseUrl`. |
| `headed` | boolean | `false` | Run the browser headed. |
| `recordVideo` | boolean | `true` | Record video evidence for generated tests. |

### `ui.auth`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `strategy` | string | `"form"` | Login strategy. |
| `loginUrl` | string | `"/login"` | Route of the login page. |
| `username` | string | `""` | Test credential username/email (falls back to top-level `auth`). |
| `password` | string | `""` | Test credential password. |

### `ui.crawl`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `maxDepth` | integer | `3` | BFS crawl depth cap. |
| `maxRoutes` | integer | `30` | Route cap. |
| `maxActionsPerPage` | integer | `20` | Max interactive elements analyzed per page. |
| `include` | string[] | `[]` | Extra routes to visit (useful for JS-only navigation the crawler cannot follow). |
| `exclude` | string[] | `[]` | Routes to skip. |
| `safeMode` | boolean | `true` | Skip destructive links/actions (delete, logout, billing, payment style controls). |
| `ignoreTestIds` | boolean | `false` | Pretend the app has no `data-testid` convention so the heuristic locator tiers get exercised. |

### `ui.selectors`

Optional manual overrides when login detection fails: locator expressions or raw CSS.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `loginUsername` | string | `""` | Username field locator. |
| `loginPassword` | string | `""` | Password field locator. |
| `loginSubmit` | string | `""` | Submit button locator. |

### `ui.testGeneration`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `includeSmoke` | boolean | `true` | Generate smoke tests. |
| `includeAuth` | boolean | `true` | Generate auth tests. |
| `includeNavigation` | boolean | `true` | Generate navigation tests. |
| `includeForms` | boolean | `true` | Generate form tests. |
| `includeTables` | boolean | `true` | Generate list/table tests. |
| `allowMutation` | boolean | `false` | Allow generated tests to submit filled forms (off by default for safety). |

## Full annotated example

```json
{
  "mode": "frontend",
  "projectName": "acme-web",
  "projectPath": ".",
  "baseUrl": "http://localhost:3000",
  "readyPath": "/",
  "scope": "codebase",
  "codegen": "auto",
  "prdFile": "docs/PRD.md",
  "output": "suitest-output",

  "auth": {
    "type": "bearer",
    "loginPath": "/api/auth/login",
    "username": "qa@example.com",
    "password": "password123",
    "tokenField": "token",
    "usernameField": "email",
    "passwordField": "password"
  },

  "server": {
    "autostart": true,
    "startCommand": "npm run dev",
    "cwd": ".",
    "readyTimeoutSec": 60,
    "readyLogPattern": "ready in",
    "env": { "NODE_ENV": "test" },
    "stopGraceSec": 5
  },

  "dependencies": [
    {
      "name": "api",
      "startCommand": "npm run start:api",
      "cwd": "../api",
      "baseUrl": "http://localhost:4001",
      "readyPath": "/api/health",
      "readyTimeoutSec": 60
    }
  ],

  "ui": {
    "mode": "blackbox",
    "targetUrl": "http://localhost:3000",
    "auth": { "strategy": "form", "loginUrl": "/login", "username": "qa@example.com", "password": "password123" },
    "crawl": { "maxDepth": 3, "maxRoutes": 30, "safeMode": true },
    "selectors": { "loginUsername": "", "loginPassword": "", "loginSubmit": "" },
    "testGeneration": { "includeSmoke": true, "includeForms": true, "allowMutation": false },
    "headed": false,
    "recordVideo": true
  },

  "publish": {
    "enabled": true,
    "apiUrl": "http://localhost:4000",
    "workspaceId": "ws_1",
    "projectId": "",
    "suiteName": "acme-web blackbox"
  }
}
```

:::tip
A backend example without a repo checkout only needs `mode: "backend"`, `baseUrl`, `analysisSource: "openapi"`, and `openapiUrl` (or `openapiFile` / `postmanFile`), plus `server.autostart: false` when the target is already running.
:::
