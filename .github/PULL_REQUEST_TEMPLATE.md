<!-- One PR = one ROADMAP acceptance criterion. -->

## What

<!-- Short summary of the change. -->

## Roadmap criterion

Closes #M<milestone>-<n>

## Checklist

- [ ] Manual TCM works without an LLM; MCP and runs require validated LLM readiness
- [ ] Capability/autonomy gating added for any LLM-dependent feature
- [ ] `make check-all` passes (ruff + mypy + eslint + tsc)
- [ ] `make test` passes (new tests added for new behavior)
- [ ] `make test-web` passes (if FE touched)
- [ ] Alembic migration added for any schema change
- [ ] Secrets handled via AES-GCM; mutations audit-logged
- [ ] Docs updated (`docs/*`, `ROADMAP.md` checkbox)

## Notes / open questions

<!-- Anything reviewers should know, or questions you couldn't resolve. -->
