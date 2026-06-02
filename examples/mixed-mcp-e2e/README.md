# Example: mixed-MCP end-to-end (ZERO tier)

A single test case whose steps use **different** MCP providers — seed Postgres,
call the HTTP API, then verify in the browser. This is the "mixed-MCP" capability
that sets Suitest apart from single-protocol runners.

Steps in `case.json`:
1. `postgres-mcp` — seed a product row.
2. `api-http-mcp` — POST /cart to add it.
3. `playwright-mcp` — open the cart page and assert the item appears.
4. `postgres-mcp` — assert the cart row exists in the DB.

```bash
suitest run --project <projectId> --case <caseId> --wait
```
