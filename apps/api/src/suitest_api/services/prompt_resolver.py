"""Prompt resolution with the per-workspace override layer (M5-3).

The single entry point services should use to fetch a prompt's text. It checks
for an active :class:`WorkspacePromptOverride` (a DB-backed fork) for the
workspace; if none exists it falls back to the file-based default via
:func:`suitest_agent.prompts.loader.read_prompt`. The file default is therefore
always the safety net — ZERO/default behaviour is unchanged when no fork exists.

Returns ``(content, source)`` where ``source`` is ``"fork:v{n}"`` or
``"file:{version}"`` so callers can stamp reproducibility metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_agent.prompts.loader import prompt_hash, read_prompt
from suitest_db.repositories.prompt_experiments import PromptExperimentRepo
from suitest_db.repositories.prompt_versions import PromptVersionRepo
from suitest_db.repositories.workspace_prompt_overrides import WorkspacePromptOverrideRepo

from suitest_api.services.prompt_experiment_service import choose_variant, variant_override_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.prompt_version import PromptVersion


async def resolve_prompt(
    session: AsyncSession,
    *,
    workspace_id: str,
    prompt_name: str,
    base_version: str = "v1",
) -> tuple[str, str]:
    """Return ``(content, source)`` honouring an active workspace fork if present."""
    active = await WorkspacePromptOverrideRepo(session).get_active(workspace_id, prompt_name)
    if active is not None:
        return active.content, f"fork:v{active.fork_version}"
    return read_prompt(prompt_name, base_version), f"file:{base_version}"


async def _resolve_with_experiment(
    session: AsyncSession,
    *,
    workspace_id: str,
    prompt_name: str,
    base_version: str,
) -> tuple[str, str] | None:
    """Resolve content via an active A/B experiment, recording an impression.

    Returns ``(content, source)`` where ``source`` is ``ab:{exp_id}:{variant}``,
    or ``None`` when no experiment is active for this prompt. The chosen variant's
    content is the file default (override id NULL) or the fork's content.
    """
    exp = await PromptExperimentRepo(session).get_active(workspace_id, prompt_name)
    if exp is None:
        return None
    variant = choose_variant(exp.a_impressions, exp.b_impressions, exp.split_pct)
    override_id = variant_override_id(exp, variant)
    if override_id is None:
        content = read_prompt(prompt_name, base_version)
    else:
        override = await WorkspacePromptOverrideRepo(session).get_by_id(override_id)
        content = (
            override.content if override is not None else read_prompt(prompt_name, base_version)
        )
    await PromptExperimentRepo(session).record_impression(exp.id, variant)
    return content, f"ab:{exp.id}:{variant}"


async def resolve_and_pin(
    session: AsyncSession,
    *,
    workspace_id: str,
    prompt_name: str,
    base_version: str = "v1",
) -> tuple[str, PromptVersion]:
    """Resolve the effective prompt and pin it in ``prompt_versions`` for repro.

    Precedence: an active A/B experiment (M5-4) wins and records an impression;
    otherwise an active fork (M5-3); otherwise the file default. When the result
    is the plain file default the version label is the file ``base_version`` (so
    the pinned row is exactly the canonical default, unchanged from pre-M5-3);
    any override/variant content gets a content-addressed label
    (``{base_version}+{hash12}``) so it never collides with the default or another
    workspace's fork.
    """
    experiment = await _resolve_with_experiment(
        session, workspace_id=workspace_id, prompt_name=prompt_name, base_version=base_version
    )
    if experiment is not None:
        content, source = experiment
    else:
        content, source = await resolve_prompt(
            session, workspace_id=workspace_id, prompt_name=prompt_name, base_version=base_version
        )
    content_hash = prompt_hash(content)
    version_label = (
        base_version if source.startswith("file") else f"{base_version}+{content_hash[:12]}"
    )
    row = await PromptVersionRepo(session).ensure(prompt_name, version_label, content, content_hash)
    return content, row
