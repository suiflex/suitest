#!/usr/bin/env bash
# M4-1 LOCAL-tier live smoke. Boots a CPU-only Ollama via the docker-compose
# ``local-smoke`` profile, pulls a tiny instruct model, then drives one real
# completion through the runtime's own LiteLLMProvider (scripts/validate_local_tier.py).
#
# This is what flips M4-1 from "code-complete" to "validated": it exercises the
# provider->model mapping + base_url plumbing end-to-end against a live server,
# with no GPU and no external network beyond the model pull. Reusable from the
# Makefile (`make local-smoke`) and from CI (.github/workflows/m4-local-tier.yml).
set -euo pipefail

MODEL="${SUITEST_LOCAL_SMOKE_MODEL:-qwen2.5:0.5b}"
COMPOSE_FILE="infra/docker/docker-compose.yml"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  echo "--- tearing down ollama ---"
  SUITEST_LOCAL_SMOKE_MODEL="$MODEL" docker compose -f "$COMPOSE_FILE" --profile local-smoke down -v || true
}
trap cleanup EXIT

echo "--- booting CPU Ollama (model: $MODEL) ---"
export SUITEST_LOCAL_SMOKE_MODEL="$MODEL"
# `up` blocks on ollama-pull (restart:no) finishing, so the model is present
# before we smoke. --wait surfaces a non-zero exit if a dependency is unhealthy.
docker compose -f "$COMPOSE_FILE" --profile local-smoke up -d --wait ollama

echo "--- pulling model $MODEL ---"
docker compose -f "$COMPOSE_FILE" --profile local-smoke run --rm ollama-pull

echo "--- smoke: one completion through LiteLLMProvider ---"
uv run python scripts/validate_local_tier.py ollama \
  --model "$MODEL" \
  --base-url "http://localhost:11434"

echo "PASS  LOCAL tier (ollama) validated against a live server."
