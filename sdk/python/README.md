# suiflex-suitest-sdk (Python)

Official Python SDK for the [Suitest](https://suitest.dev) API.

```bash
pip install suiflex-suitest-sdk
```

```python
from suitest_sdk import SuitestClient

with SuitestClient("https://suitest.example", token="...", workspace_id="ws_1") as client:
    print(client.capabilities())          # {"tier": "ZERO", ...}
    cases = client.list_cases()
    run = client.create_run(case_id=cases[0]["id"])
    final = client.wait_for_run(run["id"])
    print(final["status"])
    for p in client.list_mcp_providers():
        print(p["name"])
```

The client tracks the OpenAPI schema served at `/openapi.json`; a fully generated
client can be produced from there, but this hand-written client keeps the common
flows ergonomic and dependency-light (only `httpx`).

Licensed Apache-2.0.
