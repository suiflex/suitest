# Eval fixture licensing (M4-8a)

All fixtures in this directory are **original synthetic content** authored for
the Suitest eval harness. None is scraped, proprietary, or derived from a
third-party dataset.

**License: CC0 1.0 Universal (public domain dedication).**

| Fixture set | Path | Count | Source | License |
|-------------|------|-------|--------|---------|
| PRDs | `prds/prd-*.md` | 20 | Synthetic (authored for Suitest) | CC0-1.0 |
| OpenAPI specs | `openapi/api-*.yaml` | 10 | Synthetic minimal OpenAPI 3.0.3 | CC0-1.0 |
| Failed runs | `failed_runs/run-*.json` | 15 | Synthetic step-failure logs | CC0-1.0 |

## Audit notes

- **No proprietary content.** Every PRD describes a generic e-commerce/SaaS
  feature in our own words; no customer or third-party text is reused.
- **No scraped specs.** The OpenAPI documents are hand-written minimal specs
  (list/create/get per resource), not exported from any real API.
- **No real failure logs.** Step-failure strings are fabricated to exercise the
  rule-based diagnosis buckets (FLAKE / REGRESSION / INFRA / MANUAL_TRIAGE).
  Golden categories are locked to the current `DefectCategorizer` output so the
  ZERO-tier eval is deterministically green (regression lock).
- Golden expectations live in each set's `index.json`.

Per ROADMAP M4-8a, all fixtures are CC0 / public-domain — compatible with the
Apache-2.0 project license. Any future fixture MUST be CC0 / Apache-2 / MIT /
public-domain or be replaced with a synthetic equivalent.
