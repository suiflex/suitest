#!/usr/bin/env python
"""Validate the LOCAL LLM tier against a live local server (M4-1).

LOCAL tier (Ollama / llama.cpp / vLLM / LM Studio) cannot be validated in CI
without a running model server, so this is a **manual** smoke script: point it
at a server you control and it runs one completion through the same
``LiteLLMProvider`` the runtime uses, confirming the provider→model mapping +
``base_url`` plumbing works end-to-end.

Usage::

    # Ollama (must be `ollama serve` + `ollama pull llama3.1`)
    uv run python scripts/validate_local_tier.py ollama --model llama3.1

    # vLLM OpenAI server on :8000
    uv run python scripts/validate_local_tier.py vllm \
        --model Qwen/Qwen2.5-7B-Instruct --base-url http://localhost:8000/v1

Exit code 0 = the server answered; non-zero = misconfig / unreachable. Defaults
for ``--base-url`` / ``--model`` come from ``LOCAL_TIER_DEFAULTS``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from suitest_agent.providers.base import ChatMessage, ModelCall
from suitest_agent.providers.litellm_router import (
    LOCAL_TIER_DEFAULTS,
    LiteLLMProvider,
)


async def _run(provider: str, model: str, base_url: str) -> int:
    client = LiteLLMProvider(provider=provider, api_key="not-needed", base_url=base_url)
    call = ModelCall(
        model=model,
        messages=[ChatMessage(role="user", content="Reply with the single word: OK")],
        temperature=0.0,
        seed=7,
    )
    try:
        result = await client.complete(call)
    except Exception as exc:  # surface any failure to the operator
        print(f"FAIL  {provider} @ {base_url} ({model}): {exc}", file=sys.stderr)
        return 1
    print(f"OK    {provider} @ {base_url} ({model}) → {result.content[:80]!r}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a LOCAL LLM provider.")
    parser.add_argument("provider", choices=sorted(LOCAL_TIER_DEFAULTS))
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    args = parser.parse_args()
    defaults = LOCAL_TIER_DEFAULTS[args.provider]
    model = args.model or defaults["example_model"]
    base_url = args.base_url or defaults["base_url"]
    return asyncio.run(_run(args.provider, model, base_url))


if __name__ == "__main__":
    raise SystemExit(main())
