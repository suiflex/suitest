# Example: Playwright browser E2E (ZERO tier)

Drive a real browser through the bundled `playwright-mcp` provider — no LLM.

1. Bring up the stack: `docker compose -f infra/docker/docker-compose.yml --profile zero up -d`
2. Create the case from `case.json` (steps target `mcp_provider: playwright-mcp`, `target_kind: FE_WEB`).
3. Run it:

```bash
suitest run --project <projectId> --case <caseId> --branch main --wait
```

`case.json` is a minimal login smoke: navigate → fill → click → assert. Each step
streams logs + a screenshot artifact to MinIO.
