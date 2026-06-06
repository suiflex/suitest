"""Versioned agent prompts (M3-5).

Prompt text lives in ``v{N}/{name}.md`` files alongside this package. The loader
computes ``sha256(content)`` and the API layer reconciles it with the
``prompt_versions`` table so a generation/diagnosis run records exactly which
prompt produced it. Editing a prompt in place is a drift error — bump the version.
"""
