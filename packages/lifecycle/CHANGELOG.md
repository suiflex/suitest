# Changelog

## [0.2.0](https://github.com/suiflex/suitest/compare/lifecycle-v0.1.9...lifecycle-v0.2.0) (2026-09-01)


### Features

* **api:** brand the UAT document and stop losing its screenshot evidence ([450b413](https://github.com/suiflex/suitest/commit/450b413386f623e090d8b9d5e8908fd79312e799))
* detect nuxt/sveltekit/vue and trim evidence video blank frames ([#47](https://github.com/suiflex/suitest/issues/47)) ([34cd703](https://github.com/suiflex/suitest/commit/34cd703647f2772c1c052611bb78a08a0aa67c5c))
* **launch:** open-source launch prep — npx MCP package, branding, English docs, CI ([38f142a](https://github.com/suiflex/suitest/commit/38f142a3435f9a64912b0b0137758f035c5e98ac))
* **lifecycle:** budgeted failure markdown builder ([0e175d4](https://github.com/suiflex/suitest/commit/0e175d4f1218141dd4131ca06beb705ecb7211e9))
* **lifecycle:** CI forge detection + CommentPublisher protocol + GitHub marker upsert ([59be8e8](https://github.com/suiflex/suitest/commit/59be8e894b671610afb3b58556c63d8130c3c853))
* **lifecycle:** console+network excerpt rules for failure bundle ([14b80f8](https://github.com/suiflex/suitest/commit/14b80f8783e37a2257c187131c7d854b13577668))
* **lifecycle:** DOM excerpt around failed selector ([6ebb6e7](https://github.com/suiflex/suitest/commit/6ebb6e76c63ee0ee7b00f02a538d2fd6f36404db))
* **lifecycle:** forge-agnostic PR comment renderer ([2b26493](https://github.com/suiflex/suitest/commit/2b2649388df5e47b9b8062d9f0a5297648c5af5c))
* **lifecycle:** get_failure_context MCP tool ([715ba9c](https://github.com/suiflex/suitest/commit/715ba9c1e351318c97b68a1aebcd1278390ade49))
* **lifecycle:** harden MCP retest flow — binding repair, change detection, stale cases ([055337c](https://github.com/suiflex/suitest/commit/055337ce8956ca924750bffe86bc57563641eb6a))
* **lifecycle:** LlmClient seam + sampling client + fallback chain ([94cc7f9](https://github.com/suiflex/suitest/commit/94cc7f9654208dea652cac93459f518f24e98410))
* **lifecycle:** load failed cases from last local run output ([6ea780d](https://github.com/suiflex/suitest/commit/6ea780d7dd4bb4e266939126647d56dfa902e644))
* **lifecycle:** no-repo discovery — OpenAPI/Postman analyzers + frontend DOM crawl ([2304f2a](https://github.com/suiflex/suitest/commit/2304f2a4d4c8f2a1fb34e707f0bca26fefb4a42a))
* **lifecycle:** publish run evidence incrementally ([#29](https://github.com/suiflex/suitest/issues/29)) ([b162ea7](https://github.com/suiflex/suitest/commit/b162ea79bed1b795e88512218aaa839a4dc50da9))
* **lifecycle:** record client sampling capability at initialize ([5770f34](https://github.com/suiflex/suitest/commit/5770f34db958b85e1f87c4403dd746e8158e0ef7))
* **lifecycle:** report llm source+model in generation envelope ([3e84cdd](https://github.com/suiflex/suitest/commit/3e84cddfef05af629f1a91b8f62351108729999e))
* **lifecycle:** resolve_llm chain — sampling first, bridge fallback ([d91ecf2](https://github.com/suiflex/suitest/commit/d91ecf2bc9545f8a818f55bfa7859029dacc9317))
* **lifecycle:** sampling/createMessage server-&gt;client with timeout ([a1e2051](https://github.com/suiflex/suitest/commit/a1e2051c05290c29e99401a6eef1ea3c962d9cb6))
* **lifecycle:** suitest ci entry point — run, comment, exit code ([aa86f00](https://github.com/suiflex/suitest/commit/aa86f009ed537386332b44fb4a3bb7332dd476b8))
* **lifecycle:** SUITEST_MODE=local skips credential gate ([b80c5e8](https://github.com/suiflex/suitest/commit/b80c5e8aa5d781b5657fc7a79512a399f867705f))
* **lifecycle:** TestSprite-parity testing lifecycle + web ingest, recording, LLM enrichment ([c6de40b](https://github.com/suiflex/suitest/commit/c6de40b0ae117a6f1ad641ec422b74321b2f6751))
* **M14:** desktop testing plumbing + forgeguard gate (FE_DESKTOP, routing, slint-mcp contract, slint-demo) ([ed77baf](https://github.com/suiflex/suitest/commit/ed77bafc6723338bfa601905d9760de9c5e453b7))
* **mcp:** self-contained npx publish + run logs in web UI ([521ad27](https://github.com/suiflex/suitest/commit/521ad2744a7b627b67fc3a5409c3ec147fff8743))
* **testing:** add testing intelligence workflows ([8a97e4d](https://github.com/suiflex/suitest/commit/8a97e4d9cec1be4d56f03b2865884d972ce120ed))
* **testing:** add testing intelligence workflows ([ccf5dfe](https://github.com/suiflex/suitest/commit/ccf5dfe98fc6ff2d5f9b778bf9a3905325b8617c))


### Bug Fixes

* **api:** restore rate limiting under fastapi 0.139 nested routers; audit actor coercion never crashes ([9e761db](https://github.com/suiflex/suitest/commit/9e761db3974559a85c476aa391294e6b2edcb841))
* **ci:** green main pipeline after dependency bumps ([c65ff7f](https://github.com/suiflex/suitest/commit/c65ff7fb1036abe9c72c45f07b065f0f1830d724))
* **ci:** make lifecycle publish idempotent ([288165a](https://github.com/suiflex/suitest/commit/288165aabb0ad9a786ec78a2c4e1a4d100b9dfd6))
* **lifecycle:** MCP server refuses to start without valid API credentials ([4f7c8c7](https://github.com/suiflex/suitest/commit/4f7c8c7c29d74a9869898056316c362a031003ad))
* **lifecycle:** run on Python 3.11 and provision the backend test dependency ([cb67950](https://github.com/suiflex/suitest/commit/cb67950a6b4fab042c8e04c5b4a046c08b46120e))
* local-runtime + MCP client compatibility (heatmap, eval, Playwright, Codex/Copilot) ([d6a2e8e](https://github.com/suiflex/suitest/commit/d6a2e8ec7fd581018e4e8c0d185444a3ef7127dd))
* **mcp:** answer ping/resources/prompts so Codex and Copilot connect ([f59ba97](https://github.com/suiflex/suitest/commit/f59ba97c3eb010f0abc9c0e959adce7c7c007b20))
* **mcp:** auto-provision Playwright on demand for blackbox tools ([5a32d09](https://github.com/suiflex/suitest/commit/5a32d0919715e2f0344bab846dfe87028024f487))
* **publish:** bind by API key and heal a dead projectId; sign local JWTs per install ([91fc82e](https://github.com/suiflex/suitest/commit/91fc82ede0b8f0592841c9d670028a24b10a9c3d))
* **release:** correct drifted __version__ constants ([98618f2](https://github.com/suiflex/suitest/commit/98618f2d28392fdcaa7c6804b5bfb76a16ead873))
* ship MCP onboarding and release safeguards ([32751de](https://github.com/suiflex/suitest/commit/32751deec12ae7765703ceea830f4fbb86b37ed1))
* ship MCP onboarding theme and workspace updates ([9d48783](https://github.com/suiflex/suitest/commit/9d48783425dd01b93d1b24a92bb0ef6f09080f10))
* **whitebox:** run pytest with the project's own interpreter ([f931b19](https://github.com/suiflex/suitest/commit/f931b19ba8ac95f3038f63235b007cf86e23ffae))
