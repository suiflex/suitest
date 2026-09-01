# Contributing to Suitest

Suitest is an MCP-native, self-hostable testing platform: manual test case
management, deterministic runs driven by pluggable MCP servers, and optional AI
on top when you bring your own LLM. This guide gets you from clone to merged PR.

By participating you agree to uphold our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Quick links

- [`docs/ROADMAP.md`](./docs/ROADMAP.md) — the single entry point for what to work on
- [`docs/PRODUCT.md`](./docs/PRODUCT.md) — what the product is for, and who for
- [`CLAUDE.md`](./CLAUDE.md) — the full coding rules, binding on humans and agents alike
- [`SECURITY.md`](./SECURITY.md) · [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) · [`CLA.md`](./CLA.md)
- [Issues](https://github.com/suiflex/suitest/issues/new/choose) · [Discussions](https://github.com/suiflex/suitest/discussions)

Read the ROADMAP before you start. It decides order and scope, and if it
disagrees with any other doc, it wins — update the doc in the same PR.

## Contributor License Agreement (CLA)

Before your first pull request can be merged, you must sign our
[Contributor License Agreement](./CLA.md). It is a one-time step: when you open
your first PR, the CLA bot comments with instructions and you sign by replying
with a single comment on the PR. Your signature is recorded on the
`cla-signatures` branch and covers all future contributions. The PR carries a
`cla: signed` or `cla: not signed` label showing where it stands.

The CLA keeps the project's licensing flexible (see [`CLA.md`](./CLA.md) § 4)
while guaranteeing your contributions always remain available under the
[Apache License 2.0](./LICENSE).

## How to contribute

- **Small fix** — typo, broken link, obvious bug: open a PR directly.
- **New MCP provider, a schema change, anything that moves a capability tier** —
  open an issue first. These touch contracts other parts of the system rely on,
  and it is cheaper to disagree before the code exists.
- **A question** — Discussions, not an issue.
- **A security problem** — [SECURITY.md](./SECURITY.md). Never a public issue.

## Getting started

Two workspaces live side by side in this repo:

- **Python**, managed with [`uv`](https://docs.astral.sh/uv/) — `apps/api`,
  `apps/runner`, and `packages/{agent,core,db,mcp,shared,lifecycle}`.
- **Node**, managed with [`pnpm`](https://pnpm.io/) — `apps/web`,
  `packages/mcp-npx`, `docs-site`. There is no root `package.json`; frontend
  commands run with `apps/web` as the working directory.

You need Python 3.12 (the workspace pins `>=3.12,<3.13`) and Node 22 with pnpm.
`.python-version` and `.node-version` carry the exact versions CI uses.

### Pick your setup

There are two ways to run Suitest while you work on it, and they are not
interchangeable. Choose by what you are changing:

| | **Docker stack** | **Local bundle (npx)** |
|---|---|---|
| What you are changing | `apps/api`, `apps/web`, `apps/runner`, `packages/*` | `packages/suitest-npx`, packaging, first-run experience |
| Database | Postgres + pgvector | SQLite, in `./.suitest/` |
| Also runs | Redis, MinIO | neither — a local supervisor replaces the ARQ worker |
| Where the dashboard lives | Vite on `:3000`, proxying to the API on `:4000` | one process on `:4000` serving both |
| Hot reload | yes, both ends | no — rebuild and restart |
| Postgres-backed tests | run | **skip themselves** |
| Needs Docker | yes | no |

**Most contributions want the Docker stack.** Take the local bundle if you are
working on the launcher itself, or if Docker is not available to you — but see
the note about skipped tests below before you rely on a green test run.

### Docker stack

```bash
git clone https://github.com/suiflex/suitest
cd suitest

# Services first: the last two steps of `make setup` migrate and seed the
# database, so they fail against a Postgres that is not up yet.
docker compose -f infra/docker/docker-compose.yml --profile zero up -d

make setup      # .env → uv sync + pnpm install + pre-commit hooks → migrate → seed
make dev        # API (:4000) + web (:3000) + ARQ runner, together
```

Open the dashboard on `:3000`. The Vite dev server proxies `/api` to `:4000`,
so both ends hot-reload.

If you run Postgres and Redis on the host rather than in compose, read the
"Running the platform locally" notes in [`CLAUDE.md`](./CLAUDE.md) first — two
defaults point at compose hostnames, and the failures they cause look unrelated
to their cause.

### Local bundle (npx)

This is how the product ships: one command, SQLite, no services to run. To
exercise it against your working tree rather than a published release, build the
bundle assets and point the launcher at them:

```bash
bash scripts/build-bundle-assets.sh            # → dist/bundle/{web,wheels}

cd ~/some-project                              # any directory you want to test in
SUITEST_BUNDLE_WHEELS_DIR=<repo>/dist/bundle/wheels \
SUITEST_BUNDLE_WEB_DIST=<repo>/dist/bundle/web \
node <repo>/packages/suitest-npx/bin/suitest.js up
```

Then `suitest.js down` to stop, `status` to check, `onboard` for the guided
first run. Add `--yes` if the directory does not look like a project root.

Things worth knowing before you lose an afternoon to them:

- **Rebuild the bundle after every code change.** The launcher installs wheels
  into `./.suitest/.venv`, so editing the source changes nothing until
  `build-bundle-assets.sh` runs again. The venv reinstalls itself whenever the
  wheels change, but the *web* half is a separate build — rebuild both.
- **The API serves the dashboard here**, unlike the Docker stack. Anything under
  `/api`, `/auth` or `/ws` that no route matches returns a 404 that says the API
  is older than the web bundle. If you see that, your two halves are out of sync.
- **Admin credentials are generated on first run** into
  `./.suitest/credentials.json`. That file also holds the encryption key and an
  API key — never paste it into an issue, a PR or a screenshot.
- **Postgres-backed tests skip themselves** with no database reachable, so
  `make test` can report success having executed almost nothing. Check the skip
  count, and run the suite against the Docker stack before you open a PR.

## Build, lint, test

Everything is wrapped in the Makefile. Run `make help` for the full list.

```
make lint            # ruff check + ruff format --check
make lint-fix        # ruff --fix + format
make typecheck       # mypy strict, one call per package
make test            # pytest (asyncio strict mode)
make test-cov        # pytest with coverage
make lint-web        # eslint --max-warnings=0
make typecheck-web   # tsc --noEmit
make test-web        # vitest
make check-all       # every linter and typechecker, no tests
make ci              # check-all + test + test-web
```

**Run `make ci` before opening a PR.**

Two invocations are scoped on purpose, and collapsing them breaks the build:

- `ruff` runs against `apps packages`, not `.`
- `mypy` runs **once per package**. A single `mypy .` fails with "Duplicate
  module named conftest".

`pre-commit` (installed by `make setup`) runs ruff, ruff-format, mypy and a
secret scan on the files you touch.

A green local `make test` is not proof on its own if you are on the local
bundle — see the skip-count warning above.

### What CI covers

`.github/workflows/ci.yml` gates every PR:

| Job | What it runs |
|---|---|
| `changes` | Path filter; the jobs below are skipped when nothing relevant moved |
| `python-lint` | ruff check, ruff format --check, mypy per package |
| `python-test` | pytest against pgvector + redis, after `alembic upgrade head`; also re-exports the OpenAPI spec and fails if `packages/shared/openapi.json` is stale |
| `ts-lint` | `pnpm typecheck` + `pnpm lint` in `apps/web` |
| `ts-test` | vitest |
| `web-lighthouse` | Frontend budgets; soft fail |
| `build-images` | The four Docker images, after the lint and test jobs pass |
| `version-floor` | Proves the published npx/uvx packages still boot on Node 18 and Python 3.11 |
| `mcp-package` | npx and uvx packaging smoke test |

End-to-end suites, the air-gapped checks and the eval harness run in their own
workflows, on a schedule or on demand.

## Adding a bundled MCP provider

MCP is the plugin layer, so a new provider touches five places that no compiler
will remind you about — the registry, the in-process runtime's lazy module list,
the builtin spec and its tool catalog, the default routing table, and the docs.
The checklist lives in [`CLAUDE.md`](./CLAUDE.md) § 5; follow it there rather
than from memory, and open an issue before you start.

## Commit conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), and
`release-please` parses them to generate the changelog and version bump for
every published artifact. Nothing is versioned by hand:

| Path | Tag | Published as |
|------|-----|--------------|
| `packages/mcp-npx` | `mcp-v*` | npm `@suiflex/suitest-mcp` |
| `packages/lifecycle` | `lifecycle-v*` | PyPI `suiflex-suitest-lifecycle` |
| `sdk/typescript` | `tssdk-v*` | npm `@suiflex/suitest-sdk` |
| `sdk/python` | `pysdk-v*` | PyPI `suiflex-suitest-sdk` |
| `cli` | `cli-v*` | PyPI `suiflex-suitest-cli` |
| `.` → `packages/suitest-npx` | `launcher-v*` | npm `@suiflex/suitest` + GHCR images |

Two `linked-versions` groups keep artifacts that ship together on one version:
`mcp` + `lifecycle` (the npm package vendors the lifecycle sources at
`prepack`), and `pysdk` + `cli` (one `pysdk-v*` tag publishes both). Bumping
either member bumps both, so a change to `packages/lifecycle` alone still
produces a new `@suiflex/suitest-mcp` release.

Two constraints on those groups are load-bearing, and both were learned the
hard way:

- **`merge: false` stays.** With merging on, the plugin folds a group into one
  PR titled `chore(main): release <group> libraries`. That title carries no
  `${component}` and no `${version}`, so the release stage cannot parse it, no
  tag is cut, and every subsequent run aborts with *"There are untagged,
  merged release PRs outstanding"* until the labels are cleared by hand.
- **Group members stay on the same version line.** The plugin takes the
  maximum across only the members that had commits in that cycle and forces it
  onto the rest — a member sitting on an older line gets *downgraded*, not
  left alone.

The remaining packages — `apps/*` and `packages/{core,db,mcp,shared,agent}` —
are never published on their own; they ship inside the launcher bundle and
their `version` fields are not maintained.

- Types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `build`, `ci`
- Subject ≤ 72 characters, imperative mood, no trailing period
- Body wrapped at 72, explaining **why** — the diff already shows the what
- One logical change per commit, so `git revert` stays safe and obvious
- Never hand-edit the changelog sections `release-please` manages

## Branching & pull requests

Branch off `main`, named for the type of the leading commit: `feat/...`,
`fix/...`, `refactor/...`, `chore/...`, `docs/...`.

- One PR = one roadmap acceptance criterion. Reference it (`Closes #M4-9`).
- Fill in the PR template: what, roadmap criterion, checklist, notes.
- Tick the test-plan boxes you actually ran. An honest unticked box is far more
  useful than a ticked one nobody checked.
- Green CI plus one review, then squash-merge.

### AI-assisted pull requests

Contributions written with an AI assistant are welcome and need no special
label. Two conditions: show the commands you actually ran, and be able to
explain the code you are proposing. A PR the author cannot discuss is not
reviewable, whoever or whatever wrote it.

Both conditions are ones assistants are bad at on their own — they will report
a suite as passing when it skipped, and describe a cause they inferred rather
than checked. [ForgeGuard](https://github.com/suiflex/ForgeGuard) exists to hold
them to it, and we suggest it for AI-assisted work here:

```bash
forgeguard init            # install rules and hooks for your agent
forgeguard gate            # static rules + this repo's quality commands
forgeguard review          # the same, over changed files only
```

It also tracks an objective and its evidence across a session
(`forgeguard task`), so what the agent claims it verified and what it actually
ran stay attached to each other. Optional, and nothing in CI depends on it —
`.forgeguard/` is gitignored, so it never reaches your diff.

## Reporting bugs & requesting features

Use the GitHub issue templates. For security issues, **do not open a public
issue** — see [SECURITY.md](./SECURITY.md).

## License

The project is licensed under the [Apache License 2.0](./LICENSE). By
contributing, you agree to the terms of the
[Contributor License Agreement](./CLA.md), which licenses your contributions
under Apache 2.0 and grants the maintainer the rights described there.
