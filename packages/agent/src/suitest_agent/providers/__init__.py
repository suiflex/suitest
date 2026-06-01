"""LLM provider layer (M3-1). LiteLLM router + deterministic mock.

Import submodules directly (no barrel re-exports per CLAUDE.md §2.2).
``litellm`` is imported lazily inside :mod:`litellm_router` so that ZERO tier and
the test suite never pull the heavy dependency at module import time.
"""
