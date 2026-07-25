# Changelog

## [0.4.0](https://github.com/suiflex/suitest/compare/launcher-v0.3.0...launcher-v0.4.0) (2026-07-25)


### Features

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


### Bug Fixes

* **api:** serve /files from disk in local mode instead of S3 ([5ca9907](https://github.com/suiflex/suitest/commit/5ca9907af78d7815c43199b5a0e73852fb1f8a4e))
* **api:** serve local artifacts to browser img/video via workspaceId query param ([b1aba1b](https://github.com/suiflex/suitest/commit/b1aba1b30a1805aaa70a6ca130e1a1bc4b175f08))
* **db:** generate public IDs on SQLite in local mode ([f59a4af](https://github.com/suiflex/suitest/commit/f59a4af5d1c919b346013a7fdebf94bf844701d8))
* **launcher:** --help/--version pre-parse + test tightening ([cdea838](https://github.com/suiflex/suitest/commit/cdea838f5795b8b507397512a46ae2617666330d))
* **launcher:** avoid AssignProcessToJobObject error on Windows ([79659d5](https://github.com/suiflex/suitest/commit/79659d54d3655ef8dc852f17f283f1966263d107))
* **launcher:** mint and pass SUITEST_ENCRYPTION_KEY to the local stack ([ac006c1](https://github.com/suiflex/suitest/commit/ac006c1775eea1e3d443078da6fd153a9450cd53))
* **launcher:** re-assert 600 on credentials overwrite ([18aff6a](https://github.com/suiflex/suitest/commit/18aff6a7b41bf1175ef00be3e47c90168a04e731))
* **launcher:** unbuffered python logs + supervisor startup line ([7a932e1](https://github.com/suiflex/suitest/commit/7a932e15b53ebc7abcd9d91f5f32182d2174ecd3))
* **suitest-npx:** mask admin password prompts during onboard ([9953446](https://github.com/suiflex/suitest/commit/9953446df104325a7e616365adda8890e2038686))

## [0.2.0](https://github.com/suiflex/suitest/compare/launcher-v0.1.8...launcher-v0.2.0) (2026-07-13)


### Features

* choosable dashboard port, dark/light toggle, fixed Connect-IDE modal ([6412b88](https://github.com/suiflex/suitest/commit/6412b88e2ef981320e994375bc12d684078501ba))
* CLI onboard hardening — cross-OS transport, secret masking, settings TUI ([6bad9f5](https://github.com/suiflex/suitest/commit/6bad9f52f5e87a6d63bc78a8f0cb9b10cf37b909))
* **cli:** consent-based uv preflight with auto-install for onboard ([#25](https://github.com/suiflex/suitest/issues/25)) ([c5901c3](https://github.com/suiflex/suitest/commit/c5901c395879544222bdcc8f201e0df6e6c72e00))
* **suitest-npx:** add settings TUI to manage API key without a browser ([64a8b29](https://github.com/suiflex/suitest/commit/64a8b29bd3852f5d8bfad317096d319127cfe6be))
* **suitest-npx:** let settings and onboard choose the dashboard port ([5b5e9e8](https://github.com/suiflex/suitest/commit/5b5e9e8d871cd651336a2614c7518d39e507269a))


### Bug Fixes

* **suitest-npx:** mask admin password prompts during onboard ([9953446](https://github.com/suiflex/suitest/commit/9953446df104325a7e616365adda8890e2038686))

## [0.1.8](https://github.com/suiflex/suitest/compare/launcher-v0.1.7...launcher-v0.1.8) (2026-07-09)


### Bug Fixes

* **launcher:** avoid AssignProcessToJobObject error on Windows ([79659d5](https://github.com/suiflex/suitest/commit/79659d54d3655ef8dc852f17f283f1966263d107))
