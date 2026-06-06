# Example: OpenAPI contract suite (ZERO tier)

Generate a deterministic contract suite (happy path + schema validation +
required-field + auth-negative) from an OpenAPI spec — no LLM required.

```bash
curl -X POST "$SUITEST_API_URL/api/v1/generators/openapi" \
  -H "Authorization: Bearer $SUITEST_TOKEN" \
  -H "X-Workspace-Id: $SUITEST_WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  --data @request.json
```

`openapi.json` is a tiny Orders API; `request.json` points the generator at it.
Add `"includeLlmEdgeCases": true` (CLOUD/LOCAL tier) to enrich with boundary/fuzz
cases on top of the deterministic core.
