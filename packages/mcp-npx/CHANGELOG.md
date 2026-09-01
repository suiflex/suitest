# Changelog

## [0.8.1](https://github.com/suiflex/suitest/compare/mcp-v0.8.0...mcp-v0.8.1) (2026-09-01)


### Bug Fixes

* **release:** unjam release-please and repair the linked-versions setup ([ca78c97](https://github.com/suiflex/suitest/commit/ca78c97d8ed38d0fc0b253d5728b6028977bbeff))

## [0.8.0](https://github.com/suiflex/suitest/compare/mcp-v0.7.3...mcp-v0.8.0) (2026-08-15)


### Features

* implement slint-mcp as a bundled desktop provider ([d5645c9](https://github.com/suiflex/suitest/commit/d5645c9a0e93b289c04fe73169fb568b55e65bd1))


### Bug Fixes

* **mcp-npx:** find Python when the launcher gets a short PATH ([b8aff17](https://github.com/suiflex/suitest/commit/b8aff174f00a7905b1f15165b456c29d6373bb75))

## [0.7.3](https://github.com/suiflex/suitest/compare/mcp-v0.7.2...mcp-v0.7.3) (2026-08-15)


### Bug Fixes

* keep per-step screenshots after a durable publish, so a later sidecar-based publish still carries evidence instead of blanking the web preview and the UAT PDF
* refuse to publish blackbox results whose sidecar screenshots are gone, instead of silently committing an evidence-less run over every case's last run

## [0.7.2](https://github.com/suiflex/suitest/compare/mcp-v0.7.1...mcp-v0.7.2) (2026-08-13)


### Bug Fixes

* run on the Python 3.11 the package advertises — a PEP 695 `type` alias in `http_client.py` made every tool crash with `SyntaxError` on 3.11 hosts
* provision `requests` on demand for backend runs, matching how playwright is already provisioned for frontend runs
* run white-box pytest with the project's own interpreter, so the user's tests can import the user's dependencies

## [0.7.1](https://github.com/suiflex/suitest/compare/mcp-v0.7.0...mcp-v0.7.1) (2026-08-13)


### Bug Fixes

* publish against the workspace the API key belongs to, ignoring a stale `publish.workspaceId`
* rebind a dead `publish.projectId` by slug when nothing ambiguous matches, instead of blocking the run

## [0.7.0](https://github.com/suiflex/suitest/compare/mcp-v0.6.2...mcp-v0.7.0) (2026-08-13)


### Features

* detect more FE/BE frameworks in `init` ([553e62c](https://github.com/suiflex/suitest/commit/553e62c))


### Bug Fixes

* ship the terminal theme module required by `@suiflex/suitest` onboarding

## [0.6.2](https://github.com/suiflex/suitest/compare/mcp-v0.6.1...mcp-v0.6.2) (2026-08-12)


### Bug Fixes

* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))

## [0.6.1](https://github.com/suiflex/suitest/compare/mcp-v0.6.0...mcp-v0.6.1) (2026-08-12)


### Bug Fixes

* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))
* ship MCP onboarding theme and workspace updates ([9d48783](https://github.com/suiflex/suitest/commit/9d48783425dd01b93d1b24a92bb0ef6f09080f10))

## [0.4.0](https://github.com/suiflex/suitest/compare/mcp-v0.3.2...mcp-v0.4.0) (2026-07-19)


### Features

* detect nuxt/sveltekit/vue and trim evidence video blank frames ([#47](https://github.com/suiflex/suitest/issues/47)) ([34cd703](https://github.com/suiflex/suitest/commit/34cd703647f2772c1c052611bb78a08a0aa67c5c))

## [0.3.2](https://github.com/suiflex/suitest/compare/mcp-v0.3.1...mcp-v0.3.2) (2026-07-13)


### Bug Fixes

* **mcp:** ship lifecycle 0.1.5 in bundled package ([#30](https://github.com/suiflex/suitest/issues/30)) ([4495606](https://github.com/suiflex/suitest/commit/4495606c67464ade8566ff169fc9584d8989ef7e))

## [0.3.1](https://github.com/suiflex/suitest/compare/mcp-v0.3.0...mcp-v0.3.1) (2026-07-13)


### Bug Fixes

* **mcp:** guard cross-client protocol compatibility ([#27](https://github.com/suiflex/suitest/issues/27)) ([cbf5190](https://github.com/suiflex/suitest/commit/cbf519068c56b6066031fe2a3847180057204791))

## [0.3.0](https://github.com/suiflex/suitest/compare/mcp-v0.2.1...mcp-v0.3.0) (2026-07-10)


### Features

* CLI onboard hardening — cross-OS transport, secret masking, settings TUI ([6bad9f5](https://github.com/suiflex/suitest/commit/6bad9f52f5e87a6d63bc78a8f0cb9b10cf37b909))
* **mcp-npx:** mask secret input in CLI prompts ([714eb3e](https://github.com/suiflex/suitest/commit/714eb3e38c0a304b787a2eaf00a1cd71a69fca37))

## [0.2.1](https://github.com/suiflex/suitest/compare/mcp-v0.2.0...mcp-v0.2.1) (2026-07-10)


### Bug Fixes

* local-runtime + MCP client compatibility (heatmap, eval, Playwright, Codex/Copilot) ([d6a2e8e](https://github.com/suiflex/suitest/commit/d6a2e8ec7fd581018e4e8c0d185444a3ef7127dd))
* **mcp:** auto-provision Playwright on demand for blackbox tools ([5a32d09](https://github.com/suiflex/suitest/commit/5a32d0919715e2f0344bab846dfe87028024f487))

## [0.2.0](https://github.com/suiflex/suitest/compare/mcp-v0.1.5...mcp-v0.2.0) (2026-07-09)


### Features

* **mcp:** log in before picking a client in install flow ([007bad2](https://github.com/suiflex/suitest/commit/007bad253ef01983f7d169763d98570b7bfc6b7d))


### Bug Fixes

* **mcp:** clearer error when a delegated client CLI fails ([20c05a5](https://github.com/suiflex/suitest/commit/20c05a5ad61b57b3ccb5937213bd21e78b377439))
