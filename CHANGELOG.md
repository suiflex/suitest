# Changelog

Single changelog for the whole Suitest workspace. From `0.11.0` on, every
published package — `@suiflex/suitest` (launcher), `@suiflex/suitest-mcp`,
`suiflex-suitest-lifecycle`, `suiflex-suitest-sdk`, `@suiflex/suitest-sdk`,
`suiflex-suitest-cli` — shares one version and ships on one `vX.Y.Z` tag.
Entries keep their `**scope:**` prefix (`mcp`, `launcher`, `api`, `cli`, …)
so each release still shows which parts moved.

Maintained by release-please; do not hand-edit the generated release
sections below.

<!-- release-please writes new releases directly under this line -->

## Historical milestones (pre-0.11)

Before `0.11.0` each package versioned independently. Per-package detail lives
in the git tags (`launcher-v*`, `mcp-v*`, `lifecycle-v*`, `tssdk-v*`,
`pysdk-v*`, `cli-v*`) and in the per-package `CHANGELOG.md` files as they
stood in those tags' trees. The milestone tags that predate package-level
versioning:

## [0.16.0](https://github.com/suiflex/suitest/compare/v0.15.0...v0.16.0) (2026-09-30)


### Features

* **fixtures:** consolidate PR [#247](https://github.com/suiflex/suitest/issues/247) fixture upload router, step editor UI, and contracts ([3b60199](https://github.com/suiflex/suitest/commit/3b601996ad2dabdca6d104abab0874cb48915621))
* **recorder,runner:** recorder improvements and test fixtures upload (closes [#244](https://github.com/suiflex/suitest/issues/244), closes [#245](https://github.com/suiflex/suitest/issues/245)) ([85498be](https://github.com/suiflex/suitest/commit/85498be9162f406e84dc6f4837f8ebb332606f61))
* **recorder:** auto-abort cleanup, navigate deduplication, and cross-frame iframe assertions (closes [#245](https://github.com/suiflex/suitest/issues/245)) ([c424b50](https://github.com/suiflex/suitest/commit/c424b50cdbd5a71fa63308c89943a1ebf268b65e))
* **recorder:** native headed browser recording, step editing, password resolution, and coalescing (closes [#234](https://github.com/suiflex/suitest/issues/234)) ([61a8dc4](https://github.com/suiflex/suitest/commit/61a8dc44b015b51d98b4e92a301935db0ebed021))
* **recorder:** native headed browser recording, step editing, password resolution, and coalescing (closes [#234](https://github.com/suiflex/suitest/issues/234)) ([9ab520c](https://github.com/suiflex/suitest/commit/9ab520cdd5389422de8fdf190485e185f89c1a68))
* **runs:** dual-phase visual evidence with element highlight and lightbox navigator (closes [#243](https://github.com/suiflex/suitest/issues/243)) ([ea162e2](https://github.com/suiflex/suitest/commit/ea162e28b83a51356392bab675e1973c9ba9c4e4))
* **runs:** dual-phase visual evidence with element highlight and lightbox navigator (closes [#243](https://github.com/suiflex/suitest/issues/243)) ([386b681](https://github.com/suiflex/suitest/commit/386b681c2753d1aff8c05eb2db0b9a4863a12855))


### Bug Fixes

* **agent:** fail closed when the workspace LLM is not ready ([572248f](https://github.com/suiflex/suitest/commit/572248f839824b4b52469f8103f6e8d3d32b4690))
* **agent:** report truncated generation output instead of zero drafts ([d12c4e6](https://github.com/suiflex/suitest/commit/d12c4e6698c7561b920254ca036866d16d70baae))
* **ci:** fix web Dockerfile pnpm frozen lockfile and switch minio to cgr.dev ([163f797](https://github.com/suiflex/suitest/commit/163f7970106b2859f07ba83867889739ec797803))
* **ci:** fix web Dockerfile pnpm frozen lockfile and switch minio to cgr.dev ([7badc7a](https://github.com/suiflex/suitest/commit/7badc7ad40a34ccac265fe80a83861d624f90f1d))
* **ci:** restore dogfood boot and platform image builds ([d2668bf](https://github.com/suiflex/suitest/commit/d2668bf75f64c815a5ce9c9872f3551a7ffde0e9))
* **ci:** restore public ECR registry for MinIO to resolve pull unauthorized failure ([e023694](https://github.com/suiflex/suitest/commit/e023694fdcbb2182bfec0b400837ce25d182fd96))
* **ci:** restore public ECR registry for MinIO to resolve pull unauthorized failure ([65dfa0e](https://github.com/suiflex/suitest/commit/65dfa0e27f2c20ca0d388bc4a048f3c5efb094a3))
* **ci:** switch minio images to public ECR chainguard registry ([532c3de](https://github.com/suiflex/suitest/commit/532c3dec911838e202c71a71de02f002177c5546))
* **docker:** allow docs-site package.json through dockerignore ([2ce7056](https://github.com/suiflex/suitest/commit/2ce705689df1356326ac4471171c762ce2219e98))
* **docker:** copy docs-site package.json and un-ignore for pnpm frozen lockfile ([21a8d5e](https://github.com/suiflex/suitest/commit/21a8d5e54cdae8b7943cb17468d87c370c56ce48))
* **docker:** switch MinIO image registry from public.ecr.aws to cgr.dev ([2d452d2](https://github.com/suiflex/suitest/commit/2d452d2d25efb96290e76d7fdd6d0a5f6d4a856a))
* **docker:** un-ignore docs-site/package.json for pnpm lockfile parity ([6ffd1df](https://github.com/suiflex/suitest/commit/6ffd1dfb249021920850a307c8f6b21dbf08d265))
* **docker:** un-ignore docs-site/package.json for pnpm lockfile parity ([f8fce6b](https://github.com/suiflex/suitest/commit/f8fce6b684c4a29845de4a0a3fdd776dfd05ad30))
* **infra:** remove broken curl healthcheck on distroless minio and wait in minio-init ([69118f0](https://github.com/suiflex/suitest/commit/69118f0771382dfd1e396339140f2d4ab0665c52))
* **infra:** remove broken curl healthcheck on distroless minio and wait in minio-init ([d063b48](https://github.com/suiflex/suitest/commit/d063b48d2625376212a0ce905c9550d0bdb14924))
* **infra:** use public ECR MinIO images with wget healthcheck for CI smoke ([c33a33e](https://github.com/suiflex/suitest/commit/c33a33e39f1cf01b9981021715c57330045de109))
* **runs:** address PR review comments across infra, db, schemas, and web ([fcf8e5f](https://github.com/suiflex/suitest/commit/fcf8e5ffb14415bac9819f237df9117778fac474))
* **web:** keep selected-case actions usable on narrow screens ([a489543](https://github.com/suiflex/suitest/commit/a489543f9c2f2b9328148767fd6e86cbfedf6eea))
* **web:** keep selected-case actions usable on narrow screens ([8ed372e](https://github.com/suiflex/suitest/commit/8ed372e685c81dc282f7820845165ab3b959b447))


### Reverts

* **ci:** keep PR scoped to frontend without docker triggers ([06d2aa0](https://github.com/suiflex/suitest/commit/06d2aa064e8c478d96f1ee434c21ab20dcb2bba3))

## [0.15.0](https://github.com/suiflex/suitest/compare/v0.14.0...v0.15.0) (2026-09-22)


### Features

* **api-keys:** allow QA to mint and manage its own keys ([a3c2ee3](https://github.com/suiflex/suitest/commit/a3c2ee339363a3148e57ea550ef0893ee33d7b0c)), closes [#228](https://github.com/suiflex/suitest/issues/228)
* **api:** adaptive secure S3 streaming gateway for self-hosted and VPS deployments (closes [#221](https://github.com/suiflex/suitest/issues/221)) ([ed57183](https://github.com/suiflex/suitest/commit/ed57183d60b11bb686c095ee02f4079b6bb40ecf))
* **inbox:** audit + WS notify + expiry UX + real aggregators (M1e-10) ([6e43644](https://github.com/suiflex/suitest/commit/6e436442868ed6bb5139cf648f5a3d4070207637))
* **invites:** in-app invite approval for existing users (M1e-9) ([a2ceb0b](https://github.com/suiflex/suitest/commit/a2ceb0b7066e511b4e2366dc8800f1cbe45a000f))
* **profile:** let a user rename themselves ([7b1b55e](https://github.com/suiflex/suitest/commit/7b1b55ee34b306fe4dbb586cebd1877d6fe6e1f9))
* **profile:** let a user rename themselves ([6527756](https://github.com/suiflex/suitest/commit/652775654c64b59a3ba87e8d9d8274bc0454169c)), closes [#227](https://github.com/suiflex/suitest/issues/227)
* **web:** add suite-level selection, collapsible suites, and unset gating toggle ([414d950](https://github.com/suiflex/suitest/commit/414d9504d706c606395081fbad323d5b8f53b460))
* **web:** full CRUD for workspace member management, real-time sync, and multi-workspace fallback (closes [#224](https://github.com/suiflex/suitest/issues/224)) ([42610a6](https://github.com/suiflex/suitest/commit/42610a6158fe252baa1aedff6f73186def58c969))
* **web:** full CRUD for workspace member management, real-time sync, and multi-workspace fallback (closes [#224](https://github.com/suiflex/suitest/issues/224)) ([ca08c59](https://github.com/suiflex/suitest/commit/ca08c59702fd67280af9eace34c6c08adc5db103))


### Bug Fixes

* address review feedback on i18n, invite state guard, audit log, and card footer ([7b26ef7](https://github.com/suiflex/suitest/commit/7b26ef7433221c1079dd2cac11570937a738955c))
* **agent:** handle non-JSON error bodies without an empty except (forgeguard) ([544627c](https://github.com/suiflex/suitest/commit/544627c283138d042046b23a9eb4b014d0e25789))
* **api:** address PR feedback on artifact streaming gateway and storage boundary hardening ([e31af04](https://github.com/suiflex/suitest/commit/e31af04ed80ec38c38b105bc6afc4d31b8b80a3c))
* **api:** allow creating runs for zero-step cases and let runner record them as SKIP ([9369d68](https://github.com/suiflex/suitest/commit/9369d68c91de296997c7aeec35fc5ac4dfc0166b))
* **app:** don't bounce zero-membership users to /login on stale workspaceId ([371c70d](https://github.com/suiflex/suitest/commit/371c70d2bf72165b3ae699f74e910a40cef00e5d))
* **ci:** drop unused import, refresh openapi snapshot with invoke route docstring ([84e46d1](https://github.com/suiflex/suitest/commit/84e46d17e44e2683d3836bd042bc226c589f8e8d))
* **db:** auto-migrate legacy sqlite columns on upgrade and retry runner lock ([205fae9](https://github.com/suiflex/suitest/commit/205fae926e4044f47c3c8647fd71ac1554bc9dda))
* **db:** auto-migrate legacy sqlite columns on upgrade and retry runner lock ([2f1bfe4](https://github.com/suiflex/suitest/commit/2f1bfe41c132776ffb62e6f12fd012d64331bd9c))
* **e2e:** accept adaptive gateway artifact url and verify download in smoke test ([29e2874](https://github.com/suiflex/suitest/commit/29e287433aab74a9155a3ea0a934c297cc3741fd))
* **infra:** proxy /capabilities through the web nginx to the API ([ddad4a7](https://github.com/suiflex/suitest/commit/ddad4a72fb2a10bf1e2a8ad8a7932180d28359d6))
* **invites:** address review feedback on [#219](https://github.com/suiflex/suitest/issues/219) ([fa37c9d](https://github.com/suiflex/suitest/commit/fa37c9d1b37d60660e506940a5bf240fba3a1992))
* **invites:** repair Docker build breaks missed by local env ([02d4c47](https://github.com/suiflex/suitest/commit/02d4c47f5b197ef49f8e7c051b9a7177d6e9d9ee))
* **llm,mcp:** enforce connection invariant, normalize custom endpoints, fix capability push ([4556955](https://github.com/suiflex/suitest/commit/45569556fe93c41bba3df2ac883153254d48eb3f))
* **profile:** address connaners review — 8 items ([9c37b04](https://github.com/suiflex/suitest/commit/9c37b04e8692e15dad97c625c876d32d7cac5731))
* **profile:** rebase onto main, resolve locale conflicts, and fix lint/type/mypy issues ([63d2d09](https://github.com/suiflex/suitest/commit/63d2d0936aa19927f3d8d9d2d20ecc38c0c37326))
* **runner,web:** handle empty test steps and zero-step cases gracefully ([2cf4a2d](https://github.com/suiflex/suitest/commit/2cf4a2da3a84919124b00ffa8364284da0172994))
* **runner,web:** handle empty test steps and zero-step cases gracefully ([3c6b015](https://github.com/suiflex/suitest/commit/3c6b015d947b09ae175a24a95ad8e6e0debb349d))
* **test:** override current_active_user_optional for authenticated clients and fix audit log metadata field ([af09838](https://github.com/suiflex/suitest/commit/af0983864b63e782eb680296834a1756b76ecf95))
* **web:** prevent draft steps leakage, ghost AI diagnosis, and selection desync in test cases and runs ([cbf106d](https://github.com/suiflex/suitest/commit/cbf106d7a651edbfd6fbe0de174c14afb05ff880))
* **web:** resolve seamless fallback logout bug, harden 403 handling, and centralize workspace event sync ([4306b84](https://github.com/suiflex/suitest/commit/4306b84cf196abc483475c9bb8348e7930600d00))

## [0.14.0](https://github.com/suiflex/suitest/compare/v0.13.0...v0.14.0) (2026-09-18)


### Features

* **api:** give the chat agent project, suite and run tools ([8d4427e](https://github.com/suiflex/suitest/commit/8d4427ee647d5975a3faf3029296e87c18b99c2a)), closes [#197](https://github.com/suiflex/suitest/issues/197)
* **db:** add batched project lookup and count helpers ([18dca24](https://github.com/suiflex/suitest/commit/18dca240a93321de5201f4e4c016f085dad54996))
* expand chat agent tools and add panel collapse toggle ([9039a92](https://github.com/suiflex/suitest/commit/9039a92cb9e7ac89665a1d4c98cc057621dc6895))
* **ui:** add resizable pane, centered collapse handle, and hover trigger animation ([6b21b5d](https://github.com/suiflex/suitest/commit/6b21b5dda030146cb7c759b1eb77c92b4bbe1b20))
* **ui:** add toggle and minimize controls for Assistant Chat sidebar ([fb54a43](https://github.com/suiflex/suitest/commit/fb54a436879227831a7eea6a05d69fb6ad41c545)), closes [#198](https://github.com/suiflex/suitest/issues/198)
* **ui:** add toggle, minimize, and resizable controls for Assistant Chat sidebar ([bfb1e6b](https://github.com/suiflex/suitest/commit/bfb1e6ba96639b32b2ad647ce76b5cf83597586f))
* **web:** let users collapse the assistant chat panel ([43cad00](https://github.com/suiflex/suitest/commit/43cad009186038d6352fc4bcc761efdb441fbfb9)), closes [#198](https://github.com/suiflex/suitest/issues/198)


### Bug Fixes

* **api:** address review on chat agent run and project tools ([0444a04](https://github.com/suiflex/suitest/commit/0444a049f3217736e3e7c628ac15e3d49ab54122))
* **api:** default preventSleep to false in run config ([5ec8840](https://github.com/suiflex/suitest/commit/5ec884082ae5cf19da68cb834c87a02f4dfdae6e)), closes [#208](https://github.com/suiflex/suitest/issues/208)
* **llm:** enhance connection resilience, assertive validation UX, and real-time status sync ([1f45c35](https://github.com/suiflex/suitest/commit/1f45c356d1458eca384d83326eff7cd1bc740d4d))
* **llm:** enhance connection resilience, assertive validation UX, and real-time status sync ([1f1ab18](https://github.com/suiflex/suitest/commit/1f1ab18f076485aab29ed00c637af4a04df0f6c4))
* **runs:** make preventSleep opt-in across API, runner and UI ([6a62d7a](https://github.com/suiflex/suitest/commit/6a62d7a640daf83d3a2d3821d1b5a9ee43685b86))
* **runs:** reconcile interrupted runs, add sleep prevention wake-lock, and polish run metrics ([4165f44](https://github.com/suiflex/suitest/commit/4165f44aee6f12b86113f0275c5c43ecb18ecadb))
* **runs:** reconcile interrupted runs, add sleep prevention wake-lock, and polish run metrics (Issue [#191](https://github.com/suiflex/suitest/issues/191)) ([c859410](https://github.com/suiflex/suitest/commit/c85941006bea0aa5017beba1d4b0fe48382a3ff3))
* **ui:** harmonize PR 211 testids, restore w-[380px] class, and add header collapse button ([8c726b2](https://github.com/suiflex/suitest/commit/8c726b2253a7a45461eb777f02e04c91a13c5aad))
* **web:** refine assistant panel shortcut and scroll on expand ([bb032d5](https://github.com/suiflex/suitest/commit/bb032d56783e07c2a24e88e41ca7f5519dc1cf0a))
* **web:** treat missing preventSleep as off and clarify its scope ([33f2aad](https://github.com/suiflex/suitest/commit/33f2aadc26bff34253b0ed7091749b7dd1b9a5da)), closes [#208](https://github.com/suiflex/suitest/issues/208)

## [0.13.0](https://github.com/suiflex/suitest/compare/v0.12.0...v0.13.0) (2026-09-17)


### Features

* **cases,web:** test case historical runs endpoint and artifacts audit consistency ([0357d30](https://github.com/suiflex/suitest/commit/0357d30da864f477ed881692a8f30da11395a8e5))
* **db:** add reconciliation methods for interrupted and stale runs ([f161241](https://github.com/suiflex/suitest/commit/f161241b252f1af52c99b526b1eb599a261577d1))
* **platform:** replace capability tiers with LLM readiness ([f72e1cc](https://github.com/suiflex/suitest/commit/f72e1cc48d63ac1670a5d2d17f752ba0faf14728))
* **runner,mcp:** highlight cleanup, supervisor lock, and session recycling ([fd2098a](https://github.com/suiflex/suitest/commit/fd2098a488813a4abcd6d86feed81f3e876e63ff))
* **runner,repo:** isolate local dev data directory and install local git guard hooks ([9a1e971](https://github.com/suiflex/suitest/commit/9a1e971f4882e81f3bce1ed21910980651a377c8))
* **runs:** configurable execution settings, video recording, and browser preview ([6a3a57d](https://github.com/suiflex/suitest/commit/6a3a57d79f98e4ab8e135df225981382a6c73218))
* **web:** add new project and rename actions to project picker with role hardening ([2c4fc09](https://github.com/suiflex/suitest/commit/2c4fc095f8154cf4f34096c76adeff67564155e0))
* **web:** collapsible rail polish, logout fix, run-view minimize ([4ed73c6](https://github.com/suiflex/suitest/commit/4ed73c6d65aec5b338ab5e7f24b5f9e2a160e09e))
* **web:** collapsible rail polish, logout fix, run-view minimize ([19d87fa](https://github.com/suiflex/suitest/commit/19d87fa8c7e36efac40a242e436b56e907f09557))
* **web:** multi-screenshot lightbox gallery and inline video player modal ([25c193a](https://github.com/suiflex/suitest/commit/25c193aa6d9504777e168ee706ef01975ec3c0f0))


### Bug Fixes

* **api:** remove run reconciliation on API startup to preserve in-flight status ([0985a86](https://github.com/suiflex/suitest/commit/0985a86f1756282c4605c57717800472422c4da5))
* **ci:** address CI failures and bot complexity warnings ([47d92d4](https://github.com/suiflex/suitest/commit/47d92d477a2549a481239b0a23fabd792b431b82))
* **ci:** pass llm_ready=False to strategy test and soft-fail lighthouse ([02b2aa0](https://github.com/suiflex/suitest/commit/02b2aa07f5cf93b52bd3d97a319826119e6b8206))
* improve exception handling and extract reusable banner ([cbfecad](https://github.com/suiflex/suitest/commit/cbfecad77523df57b663937d5a7e298e9e8a5863))
* **platform:** address PR review comments on deterministic execution and DI ([c490825](https://github.com/suiflex/suitest/commit/c490825973f4ec85d5ef373ca4b1865755e04fad))
* **platform:** reconcile interrupted runs and capture errors on execution failure ([7d82e19](https://github.com/suiflex/suitest/commit/7d82e19225d967b5fdf24cbb651855219125c951))
* **pre-commit:** add pypdf to mypy hook deps for api_http bundled server ([50b0f66](https://github.com/suiflex/suitest/commit/50b0f66d8b2fbda51d5e1a9118afc6dd4ffaf611))
* **runner,api,web:** address maintainer review feedback on PR [#200](https://github.com/suiflex/suitest/issues/200) ([902e432](https://github.com/suiflex/suitest/commit/902e43245a2efa634e82ca24046b45ed2e749289))
* **runner,web:** resolve FG-DB-001 bulk query and FG-ALG-002 search lookups ([d932542](https://github.com/suiflex/suitest/commit/d93254275d6e32cfa5e699fa9e6a658d3b46742d))
* **runner:** move defect hook after commit, fix mypy annotation, and update adhoc run test ([a8a19cd](https://github.com/suiflex/suitest/commit/a8a19cd803a3ccb1ff3f94e24b3133835c4107e8))
* **runs:** handle interrupted runs gracefully and allow rerun ([58ab68f](https://github.com/suiflex/suitest/commit/58ab68ff06ff29baad2b5e4222e193a903cc5ab0))
* **web,runner:** clear runs right pane on project switch and address review feedback ([f482f52](https://github.com/suiflex/suitest/commit/f482f52a135c284596c50a1b0016ed7775b035a0))
* **web:** address rail-polish review — project picker state, a11y names, minimize public id ([e7fe045](https://github.com/suiflex/suitest/commit/e7fe04551b619c2b9467532c055ea782e15e18af))
* **web:** display graceful error state and enable rerun for interrupted runs ([4949a7a](https://github.com/suiflex/suitest/commit/4949a7aef30791e381716ece5617a2e1fd5e7c02))

## [0.12.0](https://github.com/suiflex/suitest/compare/v0.11.1...v0.12.0) (2026-09-14)


### Features

* **api:** accept a per-request model override in agent chat ([467fd2f](https://github.com/suiflex/suitest/commit/467fd2faf69af2bd434575a78da1d9718dfb4ab5))
* **api:** list the models a chatgpt or code assist account can use ([502f7bf](https://github.com/suiflex/suitest/commit/502f7bf360ece41de776fb620f435e498bbfb757))
* **cases,runner:** fail-fast test case execution, assertive step validation, and resilient step removal ([02fa9c6](https://github.com/suiflex/suitest/commit/02fa9c67ea41cb022fbe1147cc5be32bc534bdc7))
* **core:** bundle antigravity's oauth client ([6d828f7](https://github.com/suiflex/suitest/commit/6d828f79e867bb18c93d5b3d13d326e6bac06b0e))
* **mcp:** add kurir integration bridge and dependency ([cd0fcac](https://github.com/suiflex/suitest/commit/cd0fcacd3381c205740e32fe17fcd140114206a1))
* **runs:** add full-resolution image lightbox for screenshots ([a453847](https://github.com/suiflex/suitest/commit/a453847218618e49dd936d92f01a6fee71adf55a)), closes [#181](https://github.com/suiflex/suitest/issues/181)
* **runs:** bulk run execution, selective re-run dialog, live progress tracking, and run explorer UX (Phase 1 & Phase 2) ([dda9c8d](https://github.com/suiflex/suitest/commit/dda9c8d778e0f5555f1fb8cf47b85d0203d2fe69))
* **runs:** bulk run execution, UX live progress, and dynamic in-progress case rollup ([c696935](https://github.com/suiflex/suitest/commit/c6969355c97a85d069e32b589d62aac84363b53c))
* **runs:** improve run execution UX, error diagnostics, case redirection, and runs pagination ([8c16a02](https://github.com/suiflex/suitest/commit/8c16a02b58226a6784d402e7023e6c9b191dfd5f))
* **runs:** selective re-run dialog, aborted step semantics, and sqlite counter sync (Phase 2) ([d52215d](https://github.com/suiflex/suitest/commit/d52215d8e3df8c2da6aa69b98e7da45739bccbbd))
* **web:** pick the agent panel model ([b6fc0ae](https://github.com/suiflex/suitest/commit/b6fc0ae78c97fd13e44032a33a324ed93722d82c))


### Bug Fixes

* **agent:** match antigravity's request envelope ([e480d62](https://github.com/suiflex/suitest/commit/e480d6281cfa825b7b7df0c46035fcb1f7e358a0))
* **agent:** send the codex responses request the backend expects ([4d55261](https://github.com/suiflex/suitest/commit/4d552612b02e84603a4b89d650d5c21713016592))
* **ci:** fix useEffect hook dependencies in RunCaseExplorer and use quay.io for minio ([5e13860](https://github.com/suiflex/suitest/commit/5e13860bd00db0433ff707f676ac73d9dc10d048))
* **ci:** install Kurir binary in version floor ([64f9abd](https://github.com/suiflex/suitest/commit/64f9abd34d0f2192f1d855b5063eb42181491e2c))
* **ci:** move MinIO images to public ECR ([9ed83ab](https://github.com/suiflex/suitest/commit/9ed83ab47e0444ba563d051a812f7d87b78df10d))
* **ci:** move MinIO images to public ECR ([baabb76](https://github.com/suiflex/suitest/commit/baabb76eda47df224aa1b516f50fd8eef780868b))
* **ci:** retry transient dogfood image pulls ([d1ff7a2](https://github.com/suiflex/suitest/commit/d1ff7a2679627452650dd195a3f8842fb068fdf3))
* **ci:** retry transient dogfood image pulls ([e9c7c0e](https://github.com/suiflex/suitest/commit/e9c7c0e071a0bff2d69a2a61e6d68ebf9ea56f1d))
* **ci:** stabilize MCP and M1c smoke jobs ([1729f7c](https://github.com/suiflex/suitest/commit/1729f7c53c63e92582effbd3b0e94865da334b43))
* **ci:** sync pnpm lockfile and allow kurir build script ([a08ac9e](https://github.com/suiflex/suitest/commit/a08ac9e19d5c002a5380801ca85ba87d30e1aff9))
* **ci:** sync pnpm lockfile and allow kurir build script ([92e50b8](https://github.com/suiflex/suitest/commit/92e50b828b8532bc051c55ce720bc4d2b41f4719))
* **ci:** unblock release PR validation ([e631ce6](https://github.com/suiflex/suitest/commit/e631ce63a814e39d1657f69730011e4a956098f8))
* **ci:** use MinIO dev healthcheck tools ([1d62d31](https://github.com/suiflex/suitest/commit/1d62d31efc22d3fd6a7ea068bbc75a1c69ea5143))
* **ci:** use quay.io image registry for minio and mc ([1427f6d](https://github.com/suiflex/suitest/commit/1427f6dc45eeea23bf189f9817a23ee92a54d19f))
* close three gaps found reviewing the branch diff ([97a2e8b](https://github.com/suiflex/suitest/commit/97a2e8b0091d7cea73fe6157b71714bfa485049e))
* **core:** match the codex oauth client's registered flow ([0339c34](https://github.com/suiflex/suitest/commit/0339c340195e8e3355baa7cc944fa056f81e094c))
* **core:** onboard an antigravity account that has never been used ([705783f](https://github.com/suiflex/suitest/commit/705783fdcda81be0818e0a14c162111886a8657d))
* **core:** onboard each code assist product on its own host ([21ff3fb](https://github.com/suiflex/suitest/commit/21ff3fb8e1f0b94cdddf93dfc25c5b5507a5304e))
* **mcp:** add workspace node resolution and etxtbsy retry for kurir ([a90d043](https://github.com/suiflex/suitest/commit/a90d043ec7ee57eef5ae5b9e947b616ee1c4c5b3))
* **mcp:** add workspace node resolution and etxtbsy retry for kurir ([c697e10](https://github.com/suiflex/suitest/commit/c697e100cfb88a3c31e746014ca0615b69df6f6f))
* **mcp:** note lifecycle UTC timestamp synchronization in sync-python ([27ce333](https://github.com/suiflex/suitest/commit/27ce333c1939f7fba4442f594317f56b85e73ddd))
* **runs:** address PR review feedback on fail-fast progression, tenant isolation, and UI state ([3baa4a3](https://github.com/suiflex/suitest/commit/3baa4a312d5f203faf3cfe8a72730f7c2be42359))
* **runs:** address review feedback on timezone serialization and SQLite persistence ([#176](https://github.com/suiflex/suitest/issues/176)) ([575d429](https://github.com/suiflex/suitest/commit/575d42903303ace2821fce72231dc9cca404507d))
* **runs:** preserve historical immutability of completed runs across future case edits ([04a2ed1](https://github.com/suiflex/suitest/commit/04a2ed177544385767a4be09886515ccbc8ea454))
* **runs:** resolve review feedback on polling, status rollups, progress counters, and schema ([9cfb3fb](https://github.com/suiflex/suitest/commit/9cfb3fbab8a4638e9ff6c4f0cfb78ce542fa0eb6))
* **runs:** resolve timestamp timezone offset for test runs ([#176](https://github.com/suiflex/suitest/issues/176)) ([1e1fcb5](https://github.com/suiflex/suitest/commit/1e1fcb54c803d404cf1045ef5933961c73dd1fea))
* **runs:** resolve timestamp timezone offset for test runs ([#176](https://github.com/suiflex/suitest/issues/176)) ([1687513](https://github.com/suiflex/suitest/commit/168751320d9b5dcc3342c910cdc10093f4a13ebc))
* **tests:** correct route, CreateRunBody payload, and status code in test_runs_cancel_rerun ([6c0a361](https://github.com/suiflex/suitest/commit/6c0a361de94b9149c3c7348caeb3747d6c2c8ede))
* **tests:** resolve invalid keyword argument in test_runs_cancel_rerun and fix flaky assertion in test_llm_config_repo ([7f13dd7](https://github.com/suiflex/suitest/commit/7f13dd7f4a2889e4f883d209d8895f3ed5462ac0))
* **web:** preserve skipped step counters and planned cases snapshot in RunSummaryCard ([a525794](https://github.com/suiflex/suitest/commit/a525794122d6e608d04c1b4ff92dbc7143ea5ab4))
* **web:** resolve spaces in filesystem path for eslint tsconfigRootDir ([6ccf760](https://github.com/suiflex/suitest/commit/6ccf7602d70be43b5327791d6bb1bfcbfc49396e))
* **web:** show the server's reason when chat is refused ([9e4b0ce](https://github.com/suiflex/suitest/commit/9e4b0ce1e447385286b09d09b7419ed0dce2914c))


### Performance Improvements

* **web:** index the model list before asking it questions ([da3968d](https://github.com/suiflex/suitest/commit/da3968df87329f04204366c3f74afcd8b6361ae8))

## [0.11.1](https://github.com/suiflex/suitest/compare/v0.11.0...v0.11.1) (2026-09-09)


### Bug Fixes

* **agent:** report a missing LLM client instead of crashing ([c731f49](https://github.com/suiflex/suitest/commit/c731f493f4bac1ee4858c950c72f5900c74f3b82))
* **npx:** install the LLM client into the bundle venv ([83ee80b](https://github.com/suiflex/suitest/commit/83ee80ba5f0df6a99d8df69cc4bdcdcfc531b5ba))
* **npx:** keep the stack alive after the launcher exits on Windows ([a46e72c](https://github.com/suiflex/suitest/commit/a46e72cad832df5e4f099b5df74e18b7102aaa79))

## [0.11.0](https://github.com/suiflex/suitest/compare/v0.10.0...v0.11.0) (2026-09-08)


### Features

* **agent-panel:** strip inline tool-call JSON before display ([6babc66](https://github.com/suiflex/suitest/commit/6babc661b15e1d99a7f9d9d9c9abfe9ef39da7c6))
* **agent-panel:** working indicator, auto-scroll, auto-approve toggle ([edaaf55](https://github.com/suiflex/suitest/commit/edaaf555109781898f0fc03fef1a64b63eaef776))
* **agent:** tool approval buttons and reload-safe chat history ([86700b8](https://github.com/suiflex/suitest/commit/86700b84ac660cb8603667bbe94ca023852c8fc4))
* **agent:** tool-use loop so the panel can read and edit test cases ([9e8b525](https://github.com/suiflex/suitest/commit/9e8b5259cba8b8cacd0794d00eead8d5f9db25af))
* **cases:** inline editable steps tab with drag-reorder and outcome badges ([97a07a2](https://github.com/suiflex/suitest/commit/97a07a2f45d7d61883bf84a11f9e207e85b162ce))
* **dashboard:** first-run onboarding checklist and project bootstrap ([25583af](https://github.com/suiflex/suitest/commit/25583af77ce1c5aa605ffaf293c4ae898510ab74))
* **docs-site:** add google analytics tag ([65abb0e](https://github.com/suiflex/suitest/commit/65abb0e50079630925f955421f538e11cc65cd15))
* **docs-site:** add google analytics tag to landing page ([7ca025d](https://github.com/suiflex/suitest/commit/7ca025de184de2c4fdb41b2c947ac60c7035c505))
* **docs-site:** add google analytics tag to landing page ([06fc2f4](https://github.com/suiflex/suitest/commit/06fc2f436ab1cdfb51a1dac8a185932fcfbf9deb))
* **docs-site:** move google analytics tag to the docs site ([64a6678](https://github.com/suiflex/suitest/commit/64a6678d37ae707dc8432b9a3327efab03f852a3))
* **runs:** add re-run and edit-case entry points to run detail ([a1cc687](https://github.com/suiflex/suitest/commit/a1cc687f1dfe5383d1ff09af9f486390b5a3d3b7))
* **web:** add google analytics tag ([34dc274](https://github.com/suiflex/suitest/commit/34dc2741b6269c9aef9cb6a212050f036bf7b43c))


### Bug Fixes

* **agent-panel:** approve tool calls by opaque call_id ([30be1b6](https://github.com/suiflex/suitest/commit/30be1b6e613033bdd09e94405d959e6ec4d79912))
* **agent:** authorize chat writes only from a recorded pending call ([5db0cd3](https://github.com/suiflex/suitest/commit/5db0cd3661b4bcb1fc178ff6a60b019bf87ec586))
* **agent:** keep partial case.update_meta from clearing unset fields ([18a8c98](https://github.com/suiflex/suitest/commit/18a8c98a4828f2f2b926df3be2067057b8c3df81))
* **api:** accept empty-action draft steps in bulk step replace ([58e40b9](https://github.com/suiflex/suitest/commit/58e40b9a994563fcfaf5574d6535310d32e7d9b3))
* **api:** allow draft steps with empty action in append and relax strict code check ([75ff199](https://github.com/suiflex/suitest/commit/75ff199494af685352ddc75bddf22d1a80a91c44))
* **api:** require code for real-action steps in strict zero validation ([f3bfb21](https://github.com/suiflex/suitest/commit/f3bfb214b430aaecddd711cc084c075a776bd326))
* **api:** resolve steps by internal id when case addressed by public id ([80fcd95](https://github.com/suiflex/suitest/commit/80fcd95e1b6f1d11b0128a7ea3849af30176a545))
* **cases:** New step creates a local draft instead of hitting the API ([01b0a41](https://github.com/suiflex/suitest/commit/01b0a41aaf21b980738bdfb65144b1d2f8384c93))
* **cases:** responsive bulk bar and draggable list-detail splitter ([e457b87](https://github.com/suiflex/suitest/commit/e457b8787890cc273aedf3950181b028f419de06))
* **ci:** refresh openapi snapshot, de-duplicate tool parsing, drop stale e2e disclosure click ([6ca59bf](https://github.com/suiflex/suitest/commit/6ca59bfaa25a675d402f4937832fb9d28a9d10a7))
* **dashboard:** scope onboarding dismissal per workspace ([e79221f](https://github.com/suiflex/suitest/commit/e79221f46cd0fb56c15b432ffc54b6fb9d965233))
* **docs-site:** use the docs site GA4 measurement id ([4f1017b](https://github.com/suiflex/suitest/commit/4f1017bcb4b4753999fd44c27eca2fc5e289a403))
* **invites:** bind acceptance to the invited email and stop account takeover ([6769bad](https://github.com/suiflex/suitest/commit/6769badb3ede085046b02a02d838b9fb315fa1ba))
* **invites:** only claim the explicit placeholder credential ([ab5b119](https://github.com/suiflex/suitest/commit/ab5b1194004d973466ce5e18d74b6137f222c675))


### Miscellaneous Chores

* collapse release-please to one workspace version ([e28741c](https://github.com/suiflex/suitest/commit/e28741c6b86c048932d9aa3f613f811f78962c9e))

### v0.5.0-m1d — M1d — Manual TCM writes + integrations (2026-05-31)

Adds the full manual Test Case Management write surface,
soft-delete/restore, rule-based defect auto-filing, issue-tracker + webhook
integrations, and the frontend write UI — all deterministic, no LLM. 75
commits since ``v0.4.0-m1c``; every M1d-1..M1d-33 acceptance box green.

- **Backend writes** — manual TCM writes with step validation and
  optimistic concurrency; soft-delete + restore for cases/suites/projects/
  requirements; suite/project/requirement CRUD; bulk-update; ad-hoc run
  shortcut; manual defects + rule-based auto-filer/categoriser; admin audit
  log; workspace settings.
- **Integrations** — `IssueTrackerAdapter` protocol + registry; Jira, GitHub,
  Linear, Slack; webhook receivers for GitHub/GitLab/Jira; integration CRUD
  with AES-GCM at rest.
- **Frontend** — `<SplitGenerateButton>`, `<ManualCreateModal>`,
  `<CaseEditor>` route, inline step editor, bulk-ops action bar, `<Toaster>` +
  `undoToast`, interactive defect cards, integrations page, admin audit-log
  table, workspace settings.
- **Quality gates** — auto-defect E2E, golden-path Playwright E2E + `m1d-e2e`
  workflow, visual-regression spec + state audit across the data screens.

Annotated tag ``v0.5.0-m1d``.

### v0.4.0-m1c — M1c — Runner + MCP runtime complete (2026-05-29)

Runner + MCP runtime fully wired. Reproduces the full
``create → enqueue → execute → stream → artifact`` loop end-to-end against
the docker-compose stack.

- **packages/mcp** — generic async MCP client (stdio / SSE / WS / in-process),
  connection pool, registry + routing table, health monitor, invoker,
  workspace session cap.
- **Bundled MCP providers** — `api-http-mcp`, `playwright-mcp`, `postgres-mcp`.
- **apps/runner** — ARQ worker + lifecycle, step executor, run orchestrator,
  artifact pipeline to S3/MinIO.
- **apps/api** — authenticated WebSocket gateway, `POST /runs` +
  cancel/rerun, persisted run-step logs, presigned artifact URLs.
- **apps/web** — run detail page on the live WS stream, MCP provider browser.
- **DoD smoke E2E** — `tests/e2e/test_m1c_smoke.py`.

Scheduled cron runs deferred to M1d. Annotated tag ``v0.4.0-m1c``.

### v0.3.0-m1b — M1b — Frontend read-only complete

App shell, capability boot, read-only screens (Dashboard, Test Cases, Runs,
Defects, Requirements, Analytics, Integrations, Inbox, Audit).

### v0.2.0-m1a — M1a — Backend foundation + seed

FastAPI app, FastAPI-Users JWT auth, capability resolver, read endpoints
across the M1a surface, full Nusantara Retail seed.

### v0.1.0-m0 — M0 — Monorepo skeleton

Initial monorepo skeleton (apps/, packages/, infra/, docs/, pre-commit).
