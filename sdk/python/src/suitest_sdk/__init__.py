"""Official Python SDK for the Suitest API (M4-5).

A thin, typed ``httpx`` client over the Suitest REST API. The surface tracks the
OpenAPI schema served at ``/openapi.json``; a full codegen client can be
generated from there, but this hand-written client keeps the common flows
(list cases, trigger + poll runs, list MCP providers) ergonomic and dependency-light.

Example::

    from suitest_sdk import SuitestClient

    client = SuitestClient("https://suitest.example", token="...", workspace_id="ws_1")
    cases = client.list_cases()
    run = client.create_run(case_id=cases[0]["id"])
"""

from suitest_sdk.client import SuitestAPIError, SuitestClient

__all__ = ["SuitestAPIError", "SuitestClient"]
__version__ = "0.1.0"
