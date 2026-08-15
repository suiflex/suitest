---
title: Release notes
description: Every released version of the Suitest local bundle and MCP server, with the changes in each — generated from the package changelogs.
editUrl: false
---

:::tip[Which package do I update?]
A change to the API, the web dashboard, or the UAT export reaches you through the
**local bundle** (`npx @suiflex/suitest@latest onboard`). A change to test
generation, test execution, or the IDE tools reaches you through the **MCP
server** (`npx -y @suiflex/suitest-mcp@latest`). Bumping one does not bump the
other.
:::

## Local bundle — `@suiflex/suitest`

Current: **0.6.8** · [npm](https://www.npmjs.com/package/@suiflex/suitest) · [releases](https://github.com/suiflex/suitest/releases?q=launcher-v)

The one-command local platform (`npx @suiflex/suitest onboard`). Ships the web dashboard and every Python wheel, so an API or renderer change reaches you through this package.

### [0.6.8](https://github.com/suiflex/suitest/compare/launcher-v0.6.7...launcher-v0.6.8) (2026-08-16)


#### Features

* ship the rebuilt API wheel, so the UAT export renders the branded four-part document (cover, execution summary, detailed results, sign-off) instead of the single navy table

### [0.6.7](https://github.com/suiflex/suitest/compare/launcher-v0.6.6...launcher-v0.6.7) (2026-08-13)


#### Bug Fixes

* onboard with `@suiflex/suitest-mcp@0.7.2`, which runs on Python 3.11 and installs the backend test dependency itself

### [0.6.6](https://github.com/suiflex/suitest/compare/launcher-v0.6.5...launcher-v0.6.6) (2026-08-13)


#### Bug Fixes

* sign session JWTs with a 32-byte secret generated per install, instead of the published default in `settings.py`. Existing installs are signed out once.
* onboard with `@suiflex/suitest-mcp@0.7.1`, so publishing survives an uninstall/reinstall without hand-editing `suitest.config.json`

### [0.6.5](https://github.com/suiflex/suitest/compare/launcher-v0.6.4...launcher-v0.6.5) (2026-08-13)


#### Bug Fixes

* **onboard:** export isFree from stack.js ([2da4c2f](https://github.com/suiflex/suitest/commit/2da4c2fca20acd261dd198ffe3e8b378cd11ee47))
* **onboard:** export isFree from stack.js ([970c644](https://github.com/suiflex/suitest/commit/970c6449616d3099e25839ec237d7155ed6c824d))
* **onboard:** reject already-in-use ports during setup ([e2ca20d](https://github.com/suiflex/suitest/commit/e2ca20d6ec7508654187fa409b1cc868011e3c72))

### [0.6.4](https://github.com/suiflex/suitest/compare/launcher-v0.6.3...launcher-v0.6.4) (2026-08-13)

#### Features

* onboard with `@suiflex/suitest-mcp@0.7.0`, which detects more FE/BE frameworks in `init`

### [0.6.3](https://github.com/suiflex/suitest/compare/launcher-v0.6.2...launcher-v0.6.3) (2026-08-12)

#### Bug Fixes

* publish the launcher with the released `@suiflex/suitest-mcp@0.6.1` dependency

### [0.6.2](https://github.com/suiflex/suitest/compare/launcher-v0.6.1...launcher-v0.6.2) (2026-08-12)

#### Bug Fixes

* use the released MCP package containing the onboarding theme module
* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))
* ship MCP onboarding theme and workspace updates ([9d48783](https://github.com/suiflex/suitest/commit/9d48783425dd01b93d1b24a92bb0ef6f09080f10))

### [0.6.1](https://github.com/suiflex/suitest/compare/launcher-v0.6.0...launcher-v0.6.1) (2026-08-11)


#### Bug Fixes

* **suitest-npx:** correct license field to Apache-2.0 ([59fb3e2](https://github.com/suiflex/suitest/commit/59fb3e273cf0dc186482ffcb14dcddbc76acf011))
* **suitest-npx:** correct license field to Apache-2.0 ([6cb0624](https://github.com/suiflex/suitest/commit/6cb062478617503b492d14c622775b21446ba179))

### [0.6.0](https://github.com/suiflex/suitest/compare/launcher-v0.5.1...launcher-v0.6.0) (2026-08-06)


#### Features

* **cli:** brand suitest/suitest-mcp with a connected onboarding wizard ([1f90b29](https://github.com/suiflex/suitest/commit/1f90b299dee5a0baa094381ac8ed9765b4aee4fa))
* **cli:** brand suitest/suitest-mcp with a connected onboarding wizard ([0e67907](https://github.com/suiflex/suitest/commit/0e67907ca62e0dfaaf8acfb1f06e71e6fe415b56))

### [0.5.1](https://github.com/suiflex/suitest/compare/launcher-v0.5.0...launcher-v0.5.1) (2026-08-04)


#### Bug Fixes

* **release:** add launcher provenance metadata ([e8369d3](https://github.com/suiflex/suitest/commit/e8369d3aa59c5d16b2e73d7d382ecb516df441b7))
* **release:** declare launcher repository metadata ([b44cf86](https://github.com/suiflex/suitest/commit/b44cf86a221f31e093654fd1b4ecd374fbfa52a7))

### [0.5.0] (unreleased)

Includes the post-0.4.0 launcher updates currently on `main`.

### [0.4.0](https://github.com/suiflex/suitest/compare/launcher-v0.3.0...launcher-v0.4.0) (2026-07-25)


#### Features

* choosable dashboard port, dark/light toggle, fixed Connect-IDE modal ([6412b88](https://github.com/suiflex/suitest/commit/6412b88e2ef981320e994375bc12d684078501ba))
* CLI onboard hardening — cross-OS transport, secret masking, settings TUI ([6bad9f5](https://github.com/suiflex/suitest/commit/6bad9f52f5e87a6d63bc78a8f0cb9b10cf37b909))
* **cli:** consent-based uv preflight with auto-install for onboard ([#25](https://github.com/suiflex/suitest/issues/25)) ([c5901c3](https://github.com/suiflex/suitest/commit/c5901c395879544222bdcc8f201e0df6e6c72e00))
* **launcher:** .suitest project layout + superadmin credentials store ([5f13861](https://github.com/suiflex/suitest/commit/5f138615babe1e476cc1c96a59b2b91d824102b2))
* **launcher:** 0.1.1 — ship bundle assets inside the npm package ([afe38ee](https://github.com/suiflex/suitest/commit/afe38ee8d32da0437abe7503390542ba6251e6c1))
* **launcher:** layman-proof restart, status, and upgrade flow ([128d6ad](https://github.com/suiflex/suitest/commit/128d6adadaa2822c34382863d2e529e8623365fb))
* **launcher:** mint local API key via superadmin cookie login ([05e4947](https://github.com/suiflex/suitest/commit/05e49471c68568182e189e99ce8e5c3d8275b1c3))
* **launcher:** onboard orchestration + command wiring (reuse suitest-mcp init) ([a0c324f](https://github.com/suiflex/suitest/commit/a0c324f7ac74680227d386d18e59a308d97a897d))
* **launcher:** per-project venv provisioning from release wheels via uv ([c5eb866](https://github.com/suiflex/suitest/commit/c5eb866d6e50568c0a19185a1cd7e9cb3cca43e8))
* **launcher:** require user-set admin account on onboard ([046f0a5](https://github.com/suiflex/suitest/commit/046f0a5800b1a90550818f8ded2b5c9d2207f574))
* **launcher:** scaffold @suiflex/suitest package + CLI skeleton ([b160bff](https://github.com/suiflex/suitest/commit/b160bffdac83af29e81b04c47c4e12272e4af095))
* **launcher:** up/down — uvicorn + local supervisor with shared sqlite env ([e16d5b4](https://github.com/suiflex/suitest/commit/e16d5b4d7e37e5a79922f7a92b606ea70a6f173a))
* **launcher:** versioned asset fetch from GitHub Releases with local overrides ([12b7c32](https://github.com/suiflex/suitest/commit/12b7c32bb5c83eb5b74a4f2f14c1aa8121fd9b70))
* **suitest-npx:** add settings TUI to manage API key without a browser ([64a8b29](https://github.com/suiflex/suitest/commit/64a8b29bd3852f5d8bfad317096d319127cfe6be))
* **suitest-npx:** let settings and onboard choose the dashboard port ([5b5e9e8](https://github.com/suiflex/suitest/commit/5b5e9e8d871cd651336a2614c7518d39e507269a))


#### Bug Fixes

* **api:** serve /files from disk in local mode instead of S3 ([5ca9907](https://github.com/suiflex/suitest/commit/5ca9907af78d7815c43199b5a0e73852fb1f8a4e))
* **api:** serve local artifacts to browser img/video via workspaceId query param ([b1aba1b](https://github.com/suiflex/suitest/commit/b1aba1b30a1805aaa70a6ca130e1a1bc4b175f08))
* **db:** generate public IDs on SQLite in local mode ([f59a4af](https://github.com/suiflex/suitest/commit/f59a4af5d1c919b346013a7fdebf94bf844701d8))
* **launcher:** --help/--version pre-parse + test tightening ([cdea838](https://github.com/suiflex/suitest/commit/cdea838f5795b8b507397512a46ae2617666330d))
* **launcher:** avoid AssignProcessToJobObject error on Windows ([79659d5](https://github.com/suiflex/suitest/commit/79659d54d3655ef8dc852f17f283f1966263d107))
* **launcher:** mint and pass SUITEST_ENCRYPTION_KEY to the local stack ([ac006c1](https://github.com/suiflex/suitest/commit/ac006c1775eea1e3d443078da6fd153a9450cd53))
* **launcher:** re-assert 600 on credentials overwrite ([18aff6a](https://github.com/suiflex/suitest/commit/18aff6a7b41bf1175ef00be3e47c90168a04e731))
* **launcher:** unbuffered python logs + supervisor startup line ([7a932e1](https://github.com/suiflex/suitest/commit/7a932e15b53ebc7abcd9d91f5f32182d2174ecd3))
* **suitest-npx:** mask admin password prompts during onboard ([9953446](https://github.com/suiflex/suitest/commit/9953446df104325a7e616365adda8890e2038686))

### [0.2.0](https://github.com/suiflex/suitest/compare/launcher-v0.1.8...launcher-v0.2.0) (2026-07-13)


#### Features

* choosable dashboard port, dark/light toggle, fixed Connect-IDE modal ([6412b88](https://github.com/suiflex/suitest/commit/6412b88e2ef981320e994375bc12d684078501ba))
* CLI onboard hardening — cross-OS transport, secret masking, settings TUI ([6bad9f5](https://github.com/suiflex/suitest/commit/6bad9f52f5e87a6d63bc78a8f0cb9b10cf37b909))
* **cli:** consent-based uv preflight with auto-install for onboard ([#25](https://github.com/suiflex/suitest/issues/25)) ([c5901c3](https://github.com/suiflex/suitest/commit/c5901c395879544222bdcc8f201e0df6e6c72e00))
* **suitest-npx:** add settings TUI to manage API key without a browser ([64a8b29](https://github.com/suiflex/suitest/commit/64a8b29bd3852f5d8bfad317096d319127cfe6be))
* **suitest-npx:** let settings and onboard choose the dashboard port ([5b5e9e8](https://github.com/suiflex/suitest/commit/5b5e9e8d871cd651336a2614c7518d39e507269a))


#### Bug Fixes

* **suitest-npx:** mask admin password prompts during onboard ([9953446](https://github.com/suiflex/suitest/commit/9953446df104325a7e616365adda8890e2038686))

### [0.1.8](https://github.com/suiflex/suitest/compare/launcher-v0.1.7...launcher-v0.1.8) (2026-07-09)


#### Bug Fixes

* **launcher:** avoid AssignProcessToJobObject error on Windows ([79659d5](https://github.com/suiflex/suitest/commit/79659d54d3655ef8dc852f17f283f1966263d107))

## MCP server — `@suiflex/suitest-mcp`

Current: **0.8.0** · [npm](https://www.npmjs.com/package/@suiflex/suitest-mcp) · [releases](https://github.com/suiflex/suitest/releases?q=mcp-v)

The MCP server your IDE agent talks to, and the lifecycle engine that generates and runs tests. Published to npm and to PyPI as `suiflex-suitest-lifecycle`.

### [0.8.0](https://github.com/suiflex/suitest/compare/mcp-v0.7.3...mcp-v0.8.0) (2026-08-15)


#### Features

* implement slint-mcp as a bundled desktop provider ([d5645c9](https://github.com/suiflex/suitest/commit/d5645c9a0e93b289c04fe73169fb568b55e65bd1))


#### Bug Fixes

* **mcp-npx:** find Python when the launcher gets a short PATH ([b8aff17](https://github.com/suiflex/suitest/commit/b8aff174f00a7905b1f15165b456c29d6373bb75))

### [0.7.3](https://github.com/suiflex/suitest/compare/mcp-v0.7.2...mcp-v0.7.3) (2026-08-15)


#### Bug Fixes

* keep per-step screenshots after a durable publish, so a later sidecar-based publish still carries evidence instead of blanking the web preview and the UAT PDF
* refuse to publish blackbox results whose sidecar screenshots are gone, instead of silently committing an evidence-less run over every case's last run

### [0.7.2](https://github.com/suiflex/suitest/compare/mcp-v0.7.1...mcp-v0.7.2) (2026-08-13)


#### Bug Fixes

* run on the Python 3.11 the package advertises — a PEP 695 `type` alias in `http_client.py` made every tool crash with `SyntaxError` on 3.11 hosts
* provision `requests` on demand for backend runs, matching how playwright is already provisioned for frontend runs
* run white-box pytest with the project's own interpreter, so the user's tests can import the user's dependencies

### [0.7.1](https://github.com/suiflex/suitest/compare/mcp-v0.7.0...mcp-v0.7.1) (2026-08-13)


#### Bug Fixes

* publish against the workspace the API key belongs to, ignoring a stale `publish.workspaceId`
* rebind a dead `publish.projectId` by slug when nothing ambiguous matches, instead of blocking the run

### [0.7.0](https://github.com/suiflex/suitest/compare/mcp-v0.6.2...mcp-v0.7.0) (2026-08-13)


#### Features

* detect more FE/BE frameworks in `init` ([553e62c](https://github.com/suiflex/suitest/commit/553e62c))


#### Bug Fixes

* ship the terminal theme module required by `@suiflex/suitest` onboarding

### [0.6.2](https://github.com/suiflex/suitest/compare/mcp-v0.6.1...mcp-v0.6.2) (2026-08-12)


#### Bug Fixes

* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))

### [0.6.1](https://github.com/suiflex/suitest/compare/mcp-v0.6.0...mcp-v0.6.1) (2026-08-12)


#### Bug Fixes

* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))
* ship MCP onboarding theme and workspace updates ([9d48783](https://github.com/suiflex/suitest/commit/9d48783425dd01b93d1b24a92bb0ef6f09080f10))

### [0.4.0](https://github.com/suiflex/suitest/compare/mcp-v0.3.2...mcp-v0.4.0) (2026-07-19)


#### Features

* detect nuxt/sveltekit/vue and trim evidence video blank frames ([#47](https://github.com/suiflex/suitest/issues/47)) ([34cd703](https://github.com/suiflex/suitest/commit/34cd703647f2772c1c052611bb78a08a0aa67c5c))

### [0.3.2](https://github.com/suiflex/suitest/compare/mcp-v0.3.1...mcp-v0.3.2) (2026-07-13)


#### Bug Fixes

* **mcp:** ship lifecycle 0.1.5 in bundled package ([#30](https://github.com/suiflex/suitest/issues/30)) ([4495606](https://github.com/suiflex/suitest/commit/4495606c67464ade8566ff169fc9584d8989ef7e))

### [0.3.1](https://github.com/suiflex/suitest/compare/mcp-v0.3.0...mcp-v0.3.1) (2026-07-13)


#### Bug Fixes

* **mcp:** guard cross-client protocol compatibility ([#27](https://github.com/suiflex/suitest/issues/27)) ([cbf5190](https://github.com/suiflex/suitest/commit/cbf519068c56b6066031fe2a3847180057204791))

### [0.3.0](https://github.com/suiflex/suitest/compare/mcp-v0.2.1...mcp-v0.3.0) (2026-07-10)


#### Features

* CLI onboard hardening — cross-OS transport, secret masking, settings TUI ([6bad9f5](https://github.com/suiflex/suitest/commit/6bad9f52f5e87a6d63bc78a8f0cb9b10cf37b909))
* **mcp-npx:** mask secret input in CLI prompts ([714eb3e](https://github.com/suiflex/suitest/commit/714eb3e38c0a304b787a2eaf00a1cd71a69fca37))

### [0.2.1](https://github.com/suiflex/suitest/compare/mcp-v0.2.0...mcp-v0.2.1) (2026-07-10)


#### Bug Fixes

* local-runtime + MCP client compatibility (heatmap, eval, Playwright, Codex/Copilot) ([d6a2e8e](https://github.com/suiflex/suitest/commit/d6a2e8ec7fd581018e4e8c0d185444a3ef7127dd))
* **mcp:** auto-provision Playwright on demand for blackbox tools ([5a32d09](https://github.com/suiflex/suitest/commit/5a32d0919715e2f0344bab846dfe87028024f487))

### [0.2.0](https://github.com/suiflex/suitest/compare/mcp-v0.1.5...mcp-v0.2.0) (2026-07-09)


#### Features

* **mcp:** log in before picking a client in install flow ([007bad2](https://github.com/suiflex/suitest/commit/007bad253ef01983f7d169763d98570b7bfc6b7d))


#### Bug Fixes

* **mcp:** clearer error when a delegated client CLI fails ([20c05a5](https://github.com/suiflex/suitest/commit/20c05a5ad61b57b3ccb5937213bd21e78b377439))

---

*This page is generated from `packages/*/CHANGELOG.md` by
`docs-site/scripts/sync-changelog.mjs` on every build. Edit the changelogs (or
let release-please write them), not this page.*
