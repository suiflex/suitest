# Contributing to Suitest

Thanks for your interest in contributing! Suitest is an MCP-native, self-hostable
testing platform. This guide gets you from clone to merged PR.

## Code of conduct

By participating you agree to uphold our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Contributor License Agreement (CLA)

Before your first pull request can be merged, you must sign our
[Contributor License Agreement](./CLA.md). It is a one-time step: when you open
your first PR, the CLA bot comments with instructions and you sign by replying
with a single comment on the PR. Your signature is recorded on the
`cla-signatures` branch and covers all future contributions.

The CLA keeps the project's licensing flexible (see [`CLA.md`](./CLA.md) § 4)
while guaranteeing your contributions always remain available under the
[Apache License 2.0](./LICENSE).

## Getting started

```bash
git clone https://github.com/suiflex/suitest
cd suitest
cp .env.example .env
docker compose -f infra/docker/docker-compose.yml --profile zero up -d   # pg + redis + minio + api + web + runner
```

Python deps are managed with [`uv`](https://docs.astral.sh/uv/), frontend deps with
[`pnpm`](https://pnpm.io/). Install dev tooling:

```bash
uv sync                # Python workspace
pnpm install           # frontend workspace
pre-commit install     # ruff + black + mypy + secret scan on commit
```

## How we work

- **`docs/ROADMAP.md` is the single entry point.** Pick the next unchecked
  acceptance criterion in the active milestone; one PR = one criterion.
- **ZERO-tier first.** Every feature must work (or gracefully degrade) with no
  LLM configured before any AI enrichment is added.
- **Backend first, frontend second.** Pydantic schema + Alembic migration +
  service test, then wire the UI.
- Read [`CLAUDE.md`](./CLAUDE.md) for the full coding rules (typing, MCP/LLM
  routing, capability gating, audit logging).

## Quality gates (must pass before merge)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .                     # strict, no `Any`
uv run pytest                     # pytest-asyncio strict mode
pnpm -C apps/web typecheck && pnpm -C apps/web test
```

CI runs all of the above plus Docker image builds. A PR needs green CI + one
review before squash-merge to `main`.

## Commit & PR conventions

- Branch: `feat/<scope>-<short-desc>` (e.g. `feat/agent-prd-parser`).
- Commits: [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat(api): add X`, `fix(runner): handle Y`.
- Reference the milestone criterion in the PR (`Closes #M4-9`).
- Keep PRs small and focused.

## Reporting bugs / requesting features

Use the GitHub issue templates. For security issues, **do not open a public
issue** — see [SECURITY.md](./SECURITY.md).

## License

The project is licensed under the [Apache License 2.0](./LICENSE). By
contributing, you agree to the terms of the
[Contributor License Agreement](./CLA.md), which licenses your contributions
under Apache 2.0 and grants the maintainer the rights described there.
