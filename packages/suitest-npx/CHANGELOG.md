# Changelog

## [0.8.0](https://github.com/suiflex/suitest/compare/launcher-v0.7.0...launcher-v0.8.0) (2026-08-28)


### Features

* **cases:** per-case pixel-diff threshold override (M12-3) ([399182e](https://github.com/suiflex/suitest/commit/399182e9a9885cbf90de22cab91619865ea4285a))


### Bug Fixes

* **api:** stop the UAT export 500ing on unrenderable content ([145ee97](https://github.com/suiflex/suitest/commit/145ee97d6948b7bb0f5a192ef0b250e200653048))

## [0.7.0](https://github.com/suiflex/suitest/compare/launcher-v0.6.10...launcher-v0.7.0) (2026-08-27)


### Features

* **agent:** add the code assist provider ([a0c936f](https://github.com/suiflex/suitest/commit/a0c936fe1a6dd53164fbbfbaabe74019b24d3b91))
* **agent:** call the chatgpt backend through the responses api ([44dc312](https://github.com/suiflex/suitest/commit/44dc3123f64f2732113e9d7ecdec58ddc52d113e))
* **api:** add sign in with google login flow ([4de1c46](https://github.com/suiflex/suitest/commit/4de1c4658259b30a128b409c7ca1c29a2c4fb371))
* **api:** expose sign in with google routes ([61cf876](https://github.com/suiflex/suitest/commit/61cf8763918e8d9b0db41ca0b222be10219d6762))
* **api:** expose the google project list route ([2a0c2a4](https://github.com/suiflex/suitest/commit/2a0c2a42a77fac91e6e1863a36882cc469f6a437))
* **api:** finish a google sign-in into code assist ([d55b8c1](https://github.com/suiflex/suitest/commit/d55b8c178af35783d6d202ba40d65e53381192ed))
* **api:** let a publisher import desktop cases ([ae7af26](https://github.com/suiflex/suitest/commit/ae7af267345df1a83644f0df460a632b4185afc3))
* **core:** add google installed-app oauth flow ([f640d67](https://github.com/suiflex/suitest/commit/f640d67d73b4920eedcead196de59278bc3aef1f))
* **core:** add google-vertex provider reached by google sign-in ([e52847c](https://github.com/suiflex/suitest/commit/e52847c1dcf6e4e08d1b456a238e60bdc2ceb748))
* **core:** add the code assist onboarding protocol ([5548dea](https://github.com/suiflex/suitest/commit/5548dea09afd18a32f81eef7eb8766565bf74c53))
* **core:** list the models a code assist account can use ([6e6d675](https://github.com/suiflex/suitest/commit/6e6d6750ac37f896cbca5ff7be09e55ebcb7f680))
* **core:** list the signed-in user's gcp projects ([2b6f10b](https://github.com/suiflex/suitest/commit/2b6f10bebe65a3c2158913d597902e28968ce145))
* **core:** register the code assist oauth backends ([8d1d8ef](https://github.com/suiflex/suitest/commit/8d1d8efa4a13d6bec7815fdeeb10e3479a6ad290))
* **mcp:** assert any property a slint element exposes ([0bf8bee](https://github.com/suiflex/suitest/commit/0bf8beecdfa28d8376af3bbee99adb80218828e5))
* **mcp:** double-click through slint.click ([230fd1c](https://github.com/suiflex/suitest/commit/230fd1c16bbc88f4f90d42c25f2984048f0c0870))
* **mcp:** drag, element tree and a11y actions for slint ([2190370](https://github.com/suiflex/suitest/commit/21903705df29956f52dfa4f7ceb3398038a4bbc8))
* **mcp:** drag, video and event recording for slint desktop tests ([c50d9ab](https://github.com/suiflex/suitest/commit/c50d9ab5f49e74240b2380bc6750c55eb1fe70cf))
* **mcp:** expose slint's event recording ([ff5aa0a](https://github.com/suiflex/suitest/commit/ff5aa0a234db19d0f0fd9b05e64883a7433810e5))
* **mcp:** film a slint window into a run video ([e204ec4](https://github.com/suiflex/suitest/commit/e204ec4d65e89ba373d664d88822a7b37393c5e2))
* **runs:** show what a step's tool returned ([1096b8c](https://github.com/suiflex/suitest/commit/1096b8ca44c01a45080254a18d7254632cb554cd))
* **web:** add antigravity as a vendor ([ddc2e16](https://github.com/suiflex/suitest/commit/ddc2e160c4f6ba6e7eb40845ed50760b4134e795))
* **web:** add llm vendor table and provider labels ([bd7f57c](https://github.com/suiflex/suitest/commit/bd7f57caff7c1f949ac9acf1ed6a33019c81e28e))
* **web:** add screenshot diff viewer (M12-1) ([9ca5650](https://github.com/suiflex/suitest/commit/9ca5650c8d2e8ccf6a1ce1e14f9fbeb758b3bcc4))
* **web:** add sign in with google to the llm settings panel ([5ac3308](https://github.com/suiflex/suitest/commit/5ac330864abffd1a69e27cbf6ef17dfdaf5b0c34))
* **web:** choose the backend after signing in with google ([29aeda3](https://github.com/suiflex/suitest/commit/29aeda3fea5a44bf4afb4b4bae2d528dd2bbadde))
* **web:** pick a gcp project from a list ([64392cc](https://github.com/suiflex/suitest/commit/64392ccaef99969b8ebff234d60fd7f2bc745d73))
* **web:** warn where a sign-in spends an unlicensed session ([99de9bf](https://github.com/suiflex/suitest/commit/99de9bf67c405d7018ae77f9c579c581cde24b4c))


### Bug Fixes

* **api:** test an oauth config against its stored credential ([9649d98](https://github.com/suiflex/suitest/commit/9649d985574a9000c1a33fcc043e20fd7a12a811))
* **ci:** use the input name the CLA action actually reads ([9c8d05d](https://github.com/suiflex/suitest/commit/9c8d05d8dbdff46d20211b87f850f09a6bc7c982))
* **ci:** use the input name the CLA action actually reads ([46d4817](https://github.com/suiflex/suitest/commit/46d4817c30c95b1b418cb85e0cf59b20791b5da3))
* **core:** stop bundling antigravity's oauth client ([c5e2f29](https://github.com/suiflex/suitest/commit/c5e2f298a1c21433a35de3902cb905702af34b6f))
* **db:** add columns a release grew to a local database ([660a7cc](https://github.com/suiflex/suitest/commit/660a7cca7d79dcd3b2c3022bcce1bb9904588e1c))
* **mcp:** encode the video through a file, not a pipe ([51bf8f8](https://github.com/suiflex/suitest/commit/51bf8f8f415ccf2c1d7f17a405419669dcecb1ba))
* **mcp:** fall back to the filename when a resource has no mime ([a82aa0f](https://github.com/suiflex/suitest/commit/a82aa0f5989306889146bde4233be4695c6296a4))
* **mcp:** poll a text assertion instead of reading once ([4227b86](https://github.com/suiflex/suitest/commit/4227b86b54956368e0a5ac7c874b3f35f7a9fb2d))
* **mcp:** resolve id+label through the id index ([715a062](https://github.com/suiflex/suitest/commit/715a062ee353412cd128711e7a6e9e478d7adcff))
* **mcp:** retry once when an element handle went stale ([e26856d](https://github.com/suiflex/suitest/commit/e26856db9eaf4405d221a8f8dd79d330b71740e8))
* **mcp:** send the video resource uri as a plain string ([b15909e](https://github.com/suiflex/suitest/commit/b15909e63a9520c91b3b1f7652ab76abc927b090))
* **mcp:** steadier slint driving, double-click and property assertions ([6623eab](https://github.com/suiflex/suitest/commit/6623eab56490e2a3e2bb784bca87ef074c7cb5d5))
* **mcp:** stop the video sampler from starving the step it films ([ff9ef87](https://github.com/suiflex/suitest/commit/ff9ef8737c54114597481430828c6d9da48bd4ed))
* **runs:** pass a step's output through the steps endpoint ([70ca700](https://github.com/suiflex/suitest/commit/70ca700787e41e87d609c191a46f2cf1cc57b6d4))
* **web:** name the provider in the badge and agent panel ([f1e2d27](https://github.com/suiflex/suitest/commit/f1e2d2758e9a265f503caff4011ebfc57e049adf))
* **web:** stop the browser autofilling the model field ([8ffd7e0](https://github.com/suiflex/suitest/commit/8ffd7e02c6f9f88c681bfaef90a54aaae9a6857e))

## [0.6.10](https://github.com/suiflex/suitest/compare/launcher-v0.6.9...launcher-v0.6.10) (2026-08-21)


### Bug Fixes

* **launcher:** clear the stale venv before reinstalling it ([69356e9](https://github.com/suiflex/suitest/commit/69356e9a51092ca97fd310d28a9f628a5c17e9be))
* **launcher:** key the venv cache on the wheel set, not the version ([a68568f](https://github.com/suiflex/suitest/commit/a68568fd55d6058ea2ffc4639a536196e77a935c))

## [0.6.9](https://github.com/suiflex/suitest/compare/launcher-v0.6.8...launcher-v0.6.9) (2026-08-20)


### Bug Fixes

* **launcher:** guard cwd and drop brew/scoop launcher distribution ([#110](https://github.com/suiflex/suitest/issues/110)) ([d76cf0f](https://github.com/suiflex/suitest/commit/d76cf0fa3aabdb08219ab484867c76c25cab7fad))
* **launcher:** guard cwd before onboard and up ([085ef66](https://github.com/suiflex/suitest/commit/085ef66c0fa1c549eaec13ea5d4d82de6274829e))

## [0.6.8](https://github.com/suiflex/suitest/compare/launcher-v0.6.7...launcher-v0.6.8) (2026-08-16)


### Features

* ship the rebuilt API wheel, so the UAT export renders the branded four-part document (cover, execution summary, detailed results, sign-off) instead of the single navy table

## [0.6.7](https://github.com/suiflex/suitest/compare/launcher-v0.6.6...launcher-v0.6.7) (2026-08-13)


### Bug Fixes

* onboard with `@suiflex/suitest-mcp@0.7.2`, which runs on Python 3.11 and installs the backend test dependency itself

## [0.6.6](https://github.com/suiflex/suitest/compare/launcher-v0.6.5...launcher-v0.6.6) (2026-08-13)


### Bug Fixes

* sign session JWTs with a 32-byte secret generated per install, instead of the published default in `settings.py`. Existing installs are signed out once.
* onboard with `@suiflex/suitest-mcp@0.7.1`, so publishing survives an uninstall/reinstall without hand-editing `suitest.config.json`

## [0.6.5](https://github.com/suiflex/suitest/compare/launcher-v0.6.4...launcher-v0.6.5) (2026-08-13)


### Bug Fixes

* **onboard:** export isFree from stack.js ([2da4c2f](https://github.com/suiflex/suitest/commit/2da4c2fca20acd261dd198ffe3e8b378cd11ee47))
* **onboard:** export isFree from stack.js ([970c644](https://github.com/suiflex/suitest/commit/970c6449616d3099e25839ec237d7155ed6c824d))
* **onboard:** reject already-in-use ports during setup ([e2ca20d](https://github.com/suiflex/suitest/commit/e2ca20d6ec7508654187fa409b1cc868011e3c72))

## [0.6.4](https://github.com/suiflex/suitest/compare/launcher-v0.6.3...launcher-v0.6.4) (2026-08-13)

### Features

* onboard with `@suiflex/suitest-mcp@0.7.0`, which detects more FE/BE frameworks in `init`

## [0.6.3](https://github.com/suiflex/suitest/compare/launcher-v0.6.2...launcher-v0.6.3) (2026-08-12)

### Bug Fixes

* publish the launcher with the released `@suiflex/suitest-mcp@0.6.1` dependency

## [0.6.2](https://github.com/suiflex/suitest/compare/launcher-v0.6.1...launcher-v0.6.2) (2026-08-12)

### Bug Fixes

* use the released MCP package containing the onboarding theme module
* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))
* ship MCP onboarding theme and workspace updates ([9d48783](https://github.com/suiflex/suitest/commit/9d48783425dd01b93d1b24a92bb0ef6f09080f10))

## [0.6.1](https://github.com/suiflex/suitest/compare/launcher-v0.6.0...launcher-v0.6.1) (2026-08-11)


### Bug Fixes

* **suitest-npx:** correct license field to Apache-2.0 ([59fb3e2](https://github.com/suiflex/suitest/commit/59fb3e273cf0dc186482ffcb14dcddbc76acf011))
* **suitest-npx:** correct license field to Apache-2.0 ([6cb0624](https://github.com/suiflex/suitest/commit/6cb062478617503b492d14c622775b21446ba179))

## [0.6.0](https://github.com/suiflex/suitest/compare/launcher-v0.5.1...launcher-v0.6.0) (2026-08-06)


### Features

* **cli:** brand suitest/suitest-mcp with a connected onboarding wizard ([1f90b29](https://github.com/suiflex/suitest/commit/1f90b299dee5a0baa094381ac8ed9765b4aee4fa))
* **cli:** brand suitest/suitest-mcp with a connected onboarding wizard ([0e67907](https://github.com/suiflex/suitest/commit/0e67907ca62e0dfaaf8acfb1f06e71e6fe415b56))

## [0.5.1](https://github.com/suiflex/suitest/compare/launcher-v0.5.0...launcher-v0.5.1) (2026-08-04)


### Bug Fixes

* **release:** add launcher provenance metadata ([e8369d3](https://github.com/suiflex/suitest/commit/e8369d3aa59c5d16b2e73d7d382ecb516df441b7))
* **release:** declare launcher repository metadata ([b44cf86](https://github.com/suiflex/suitest/commit/b44cf86a221f31e093654fd1b4ecd374fbfa52a7))

## [0.5.0] (unreleased)

Includes the post-0.4.0 launcher updates currently on `main`.

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
