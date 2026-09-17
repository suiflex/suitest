---
title: Release notes
description: Every released version of Suitest, with the changes in each — generated from the changelog.
editUrl: false
---

The whole Suitest workspace shares one version. Every release publishes the
launcher (`@suiflex/suitest`), the MCP server (`@suiflex/suitest-mcp`), both
SDKs and the CLI together on one `vX.Y.Z` tag.

Current: **0.12.0** · [releases](https://github.com/suiflex/suitest/releases)

Single changelog for the whole Suitest workspace. From `0.11.0` on, every
published package — `@suiflex/suitest` (launcher), `@suiflex/suitest-mcp`,
`suiflex-suitest-lifecycle`, `suiflex-suitest-sdk`, `@suiflex/suitest-sdk`,
`suiflex-suitest-cli` — shares one version and ships on one `vX.Y.Z` tag.
Entries keep their `**scope:**` prefix (`mcp`, `launcher`, `api`, `cli`, …)
so each release still shows which parts moved.

Maintained by release-please; do not hand-edit the generated release
sections below.

<!-- release-please writes new releases directly under this line -->

### Historical milestones (pre-0.11)

Before `0.11.0` each package versioned independently. Per-package detail lives
in the git tags (`launcher-v*`, `mcp-v*`, `lifecycle-v*`, `tssdk-v*`,
`pysdk-v*`, `cli-v*`) and in the per-package `CHANGELOG.md` files as they
stood in those tags' trees. The milestone tags that predate package-level
versioning:

### [0.12.0](https://github.com/suiflex/suitest/compare/v0.11.1...v0.12.0) (2026-09-14)


#### Features

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


#### Bug Fixes

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


#### Performance Improvements

* **web:** index the model list before asking it questions ([da3968d](https://github.com/suiflex/suitest/commit/da3968df87329f04204366c3f74afcd8b6361ae8))

### [0.11.1](https://github.com/suiflex/suitest/compare/v0.11.0...v0.11.1) (2026-09-09)


#### Bug Fixes

* **agent:** report a missing LLM client instead of crashing ([c731f49](https://github.com/suiflex/suitest/commit/c731f493f4bac1ee4858c950c72f5900c74f3b82))
* **npx:** install the LLM client into the bundle venv ([83ee80b](https://github.com/suiflex/suitest/commit/83ee80ba5f0df6a99d8df69cc4bdcdcfc531b5ba))
* **npx:** keep the stack alive after the launcher exits on Windows ([a46e72c](https://github.com/suiflex/suitest/commit/a46e72cad832df5e4f099b5df74e18b7102aaa79))

### [0.11.0](https://github.com/suiflex/suitest/compare/v0.10.0...v0.11.0) (2026-09-08)


#### Features

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


#### Bug Fixes

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


#### Miscellaneous Chores

* collapse release-please to one workspace version ([e28741c](https://github.com/suiflex/suitest/commit/e28741c6b86c048932d9aa3f613f811f78962c9e))

#### v0.5.0-m1d — M1d — Manual TCM writes + integrations (2026-05-31)

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

#### v0.4.0-m1c — M1c — Runner + MCP runtime complete (2026-05-29)

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

#### v0.3.0-m1b — M1b — Frontend read-only complete

App shell, capability boot, read-only screens (Dashboard, Test Cases, Runs,
Defects, Requirements, Analytics, Integrations, Inbox, Audit).

#### v0.2.0-m1a — M1a — Backend foundation + seed

FastAPI app, FastAPI-Users JWT auth, capability resolver, read endpoints
across the M1a surface, full Nusantara Retail seed.

#### v0.1.0-m0 — M0 — Monorepo skeleton

Initial monorepo skeleton (apps/, packages/, infra/, docs/, pre-commit).

---

*This page is generated from `CHANGELOG.md` by
`docs-site/scripts/sync-changelog.mjs` on every build. Edit the changelog (or
let release-please write it), not this page.*
