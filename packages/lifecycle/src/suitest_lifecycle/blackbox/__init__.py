"""Blackbox DOM Discovery & Testing Engine (ZERO tier, no repo, no LLM).

Shared core used by three consumers (do not fork logic into any single one):

* **Zero** — deterministic end-to-end: discover → generate → run → evidence.
* **MCP**  — each stage is exposed as a ``blackbox_*`` tool for IDE agents.
* **LLM**  — the serialized discovery/graph JSON is handed to models as context.

Import modules directly (``from suitest_lifecycle.blackbox.crawler import …``);
this package intentionally re-exports nothing (no barrel imports).
"""
