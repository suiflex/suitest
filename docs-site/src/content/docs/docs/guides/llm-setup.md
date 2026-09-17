---
title: Bring your own LLM
description: Connect and validate the workspace LLM used by Suitest MCP, runs, and AI workflows.
---

Suitest uses the LLM configured for each workspace. The provider may be a
hosted API, a self-hosted model, or a supported sign-in provider; all options
unlock the same Suitest features after a successful connection test.

Manual test case management remains available before an LLM is configured.
MCP startup, test runs, and AI workflows require the workspace LLM status to be
`ready`.

## Configure a provider

1. Open **Settings, then LLM**.
2. Select a provider and model.
3. Enter the required API key, base URL, or complete the provider sign-in.
4. Save the configuration.
5. Select **Test connection**.

Saving or changing a provider clears its validation state. A successful test
records `last_validated_at` and enables MCP and runs for the workspace without
a restart.

## Provider requirements

| Provider | Requirements |
|---|---|
| `ollama`, `llamacpp`, `vllm`, `lmstudio` | Reachable `base_url`; no provider API key |
| `anthropic`, `openai`, `gemini`, `groq`, `openrouter`, `azure`, `deepseek` | Provider API key |
| `bedrock`, `vertex` | IAM or ambient credentials |
| `chatgpt` | Sign in with ChatGPT |
| `google-vertex` | Google sign-in and a GCP project with Vertex AI enabled |
| `google-codeassist` | Google sign-in; uses Code Assist quota |
| `antigravity` | Sign in with Antigravity |
| `custom` | OpenAI-compatible `base_url`; key requirements depend on the gateway |
| `mock` | Deterministic development and CI responses |

Configuration is per workspace and takes effect without a process restart.
Provider secrets are stored AES-GCM encrypted and are shown only as a redacted
hint after saving.

## How MCP uses the LLM

The MCP config contains the Suitest API URL and an API key. The server verifies
that key and the workspace LLM status during startup. LLM work is sent to the
Suitest `/api/v1/llm/complete` proxy; the MCP process never receives the
provider secret or delegates inference to the MCP client.

Suitest uses the configured model for test planning, code generation, runtime
translation, and failure diagnosis. Generated code still passes structural and
compilation checks before execution.

## Keeping inference private

Run Ollama, llama.cpp, vLLM, or LM Studio on infrastructure reachable by the
Suitest API and configure its base URL in the workspace. This keeps model
traffic inside your network while preserving the same product behavior.

See [LLM readiness](/docs/reference/llm-readiness/) for the complete state
contract and [Self-hosting](/docs/guides/self-hosting/) for deployment details.
