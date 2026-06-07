#!/usr/bin/env bash
# M4-16 dogfood smoke — exercise a live Suitest stack end-to-end.
#
# "Suitest tests Suitest": bring the stack up, then drive it through its own
# public surface (health, capabilities, OpenAPI schema, and the CLI's read
# paths). Kept auth-light so it runs in CI without provisioning a session token;
# the authenticated run path is covered by the Playwright golden-path E2E.
#
# Usage: SUITEST_API_URL=http://localhost:4000 tests/dogfood/smoke.sh
set -euo pipefail

API="${SUITEST_API_URL:-http://localhost:4000}"
fail() { echo "DOGFOOD FAIL: $1" >&2; exit 1; }

echo "==> /health"
curl -fsS "${API}/health" | grep -q '"status"' || fail "health not ok"

echo "==> /capabilities (expect a tier)"
caps="$(curl -fsS "${API}/capabilities")"
echo "${caps}" | grep -q '"tier"' || fail "capabilities missing tier"
echo "    ${caps}"

echo "==> OpenAPI schema served"
curl -fsS "${API}/openapi.json" | grep -q '"openapi"' || fail "openapi.json not served"

echo "==> Prometheus /metrics exposed"
# Prometheus exposition format always emits ``# HELP`` / ``# TYPE`` lines for
# every series, so that pair is a stable smoke for ``/metrics`` regardless of
# which collectors (default ProcessCollector, FastAPI request histogram, …)
# the runtime image happens to register.
metrics_body="$(curl -fsS "${API}/metrics")" || fail "/metrics not reachable"
echo "${metrics_body}" | grep -q "^# HELP" || fail "/metrics not exposed: $(echo "${metrics_body}" | head -c 200)"

echo "DOGFOOD OK — Suitest is up and self-describing."
