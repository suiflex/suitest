"""``run_test_case`` ARQ job — orchestrates one full test run end-to-end.

The orchestrator owns the run lifecycle:

1. Load the run + its step selection (M1c implicit selection: every active case
   in the project's suites, in suite/case/step order).
2. Resolve the validated workspace LLM + routing overrides.
3. Mark the run ``RUNNING``, publish ``run.started``.
4. For each step: publish ``run.step.started`` → dispatch via
   :func:`suitest_runner.executors.step_executor.execute_step` →
   persist a ``run_steps`` row → upload artifacts → publish
   ``run.step.completed``.
5. Aggregate per-outcome counters, update the run with terminal status,
   publish ``run.completed``.
6. On each ``StepOutcome.FAIL``, dispatch to
   :func:`suitest_runner.handlers.step_handler.on_run_step_failed`, which
   hands the row to the M1d-10 :class:`DefectAutoFiler` (categorise →
   dedup-aware insert → ``defect.created`` WS broadcast → enqueue downstream
   notifier / issue-tracker jobs). The hook is wrapped in try/except so a
   degraded defect pipeline never blocks run completion.

Everything that touches the DB happens inside a fresh ``session_factory()``
context manager so the worker's job-level concurrency doesn't share an
``AsyncSession`` across coroutines (SQLAlchemy sessions are not safe for that).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import httpx
import structlog
from sqlalchemy import case, select, update
from suitest_agent.generators.selector_repair import is_selector_changed_failure
from suitest_agent.graphs.execution import translate_single_step
from suitest_agent.providers.litellm_router import get_provider
from suitest_core.autonomy import AutonomyConfig, compute_effective
from suitest_core.capabilities import AutonomyLevel as CoreAutonomy
from suitest_core.llm_credentials import resolve_credential
from suitest_core.wake_lock import async_prevent_sleep
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project
from suitest_db.repositories.llm_configs import LLMConfigRepo, LLMConfigUpdate
from suitest_db.repositories.run_step_logs import RunStepLogRepo
from suitest_db.repositories.runs import RunRepo, RunStepRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_mcp.invoker import InvokeContext, McpInvoker, build_llm_ready_guard
from suitest_mcp.models import McpArtifact
from suitest_mcp.providers.builtin_specs import build_playwright_provider
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import AutonomyLevel, RunStatus, StepOutcome, TargetKind

from suitest_runner.executors.step_executor import StepResult, StepTranslator, execute_step
from suitest_runner.handlers.step_handler import on_run_step_failed
from suitest_runner.observability import get_tracer
from suitest_runner.settings import RunnerSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from suitest_api.schemas.self_heal import SelectorRepairPublic
    from suitest_api.services.defect_auto_filer import DefectAutoFiler
    from suitest_db.models.case import TestStep
    from suitest_db.models.run import Run
    from suitest_db.models.workspace_capability import WorkspaceCapability

log = structlog.get_logger(__name__)

# Refreshing an OAuth LLM credential is one round trip to the auth service.
_LLM_REFRESH_TIMEOUT = 30.0


@runtime_checkable
class _Publisher(Protocol):
    """Minimal Redis publish surface so tests can sub a recorder for ``publish``."""

    async def publish(self, channel: str, message: str | bytes) -> int: ...


def _is_defect_auto_filer(obj: object) -> bool:
    """Duck-typed check for the M1d-10 defect auto-filer.

    We avoid a hard import-time dependency on
    :class:`~suitest_api.services.defect_auto_filer.DefectAutoFiler` (the
    api package is logically downstream of the runner from a deployment
    standpoint, even though both currently live in the same monorepo) by
    structurally checking for the single method the hook calls. This keeps
    the runner importable in test fixtures that monkeypatch ``ctx`` with
    plain stubs.
    """
    return hasattr(obj, "file_for_failed_step") and callable(
        getattr(obj, "file_for_failed_step", None)
    )


def _extract_target_selector(parsed_step: dict[str, object]) -> str | None:
    """Extract a target selector from action arguments or step assertions."""
    args = parsed_step.get("arguments")
    if isinstance(args, dict):
        sel = (
            args.get("selector") or args.get("target") or args.get("locator") or args.get("element")
        )
        if isinstance(sel, str) and sel.strip():
            return sel.strip()
    assertions = parsed_step.get("assertions")
    if isinstance(assertions, list):
        for a in assertions:
            if isinstance(a, dict) and isinstance(a.get("arguments"), dict):
                sel = a["arguments"].get("selector") or a["arguments"].get("target")
                if isinstance(sel, str) and sel.strip():
                    return sel.strip()
    return None


def _has_screenshot_artifact(artifacts: Sequence[object]) -> bool:
    """Check whether a screenshot artifact is present in the list."""
    return any(getattr(a, "kind", None) == "SCREENSHOT" for a in artifacts)


@runtime_checkable
class _LogseqIncrementer(Protocol):
    """Redis ``INCR`` surface used to mint the per-run monotonic ``seq`` counter."""

    async def incr(self, name: str) -> int: ...


async def _build_translator(session: object, *, workspace_id: str) -> StepTranslator | None:
    """Bind the workspace's active LLM into a per-step action→code translator.

    Returns ``None`` when no validated LLM is configured. The provider is resolved once so every
    step in the run reuses the same client (M3-10).
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    if not isinstance(session, AsyncSession):  # pragma: no cover - defensive
        return None
    repo = LLMConfigRepo(session)
    llm = await repo.get_active(workspace_id)
    if llm is None or llm.last_validated_at is None:
        return None
    # A Sign in with ChatGPT config has no stored key — the credential (and any
    # refresh it needs) is resolved centrally, never read off the row here.
    async with httpx.AsyncClient(timeout=_LLM_REFRESH_TIMEOUT) as client:
        credential, persist = await resolve_credential(
            client,
            provider=llm.provider,
            api_key=llm.api_key_encrypted,
            base_url=llm.base_url,
            oauth_tokens_json=llm.oauth_tokens_encrypted,
            # Code Assist names its project in the request envelope, and the
            # project lives on the config rather than in the token.
            config=dict(llm.config_json or {}),
        )
    if persist is not None:
        await repo.update(llm.id, LLMConfigUpdate(oauth_tokens_encrypted=persist))
        await session.commit()
    provider = get_provider(
        credential.provider,
        api_key=credential.api_key,
        base_url=credential.base_url,
        extra_headers=credential.extra_headers or None,
        extra_body=credential.extra_body or None,
    )
    model = llm.model

    async def _translate(action: str) -> dict[str, object] | None:
        return await translate_single_step(provider, model=model, action=action)

    return _translate


def _auto_self_heal_enabled(capability: WorkspaceCapability | None) -> bool:
    """Full self-heal is a hard `auto` rail even when lower-level overrides say true."""
    if capability is None or capability.autonomy_level is not AutonomyLevel.AUTO:
        return False
    raw = capability.features_json.get("autonomy_overrides", {})
    overrides = {key: bool(value) for key, value in raw.items()} if isinstance(raw, dict) else {}
    effective = compute_effective(
        AutonomyConfig(
            level=CoreAutonomy(capability.autonomy_level.value),
            overrides=overrides,
        )
    )
    return effective["exec_self_heal_enabled"]


async def _try_auto_self_heal(
    *,
    factory: object,
    test_step: TestStep,
    case_id: str,
    workspace_id: str,
    user_id: str | None,
    result: StepResult,
) -> SelectorRepairPublic | None:
    """Propose one selector patch and stage it in memory for a single retry."""
    if not callable(factory) or not is_selector_changed_failure(
        test_step.code, result.error_message
    ):
        return None
    from suitest_api.services.self_heal_service import SelfHealError, SelfHealService

    try:
        async with factory() as session:
            service = SelfHealService(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            proposal = await service.propose(
                case_id,
                step_id=test_step.id,
                error=result.error_message or "",
                dom_snapshot=result.stderr or None,
            )
            await session.commit()
    except SelfHealError as exc:
        log.warning(
            "runner.self_heal.skip",
            step_id=test_step.id,
            code=exc.code,
            reason=exc.message,
        )
        return None
    except Exception as exc:
        log.warning("runner.self_heal.error", step_id=test_step.id, reason=str(exc))
        return None
    test_step.code = proposal.updated_code
    return proposal


async def _persist_auto_self_heal(
    *,
    factory: object,
    case_id: str,
    workspace_id: str,
    user_id: str | None,
    proposal: SelectorRepairPublic,
) -> bool:
    """Persist a staged repair only after its retry passed."""
    if not callable(factory):
        return False
    from suitest_api.schemas.self_heal import SelectorRepairApplyRequest
    from suitest_api.services.self_heal_service import SelfHealError, SelfHealService

    try:
        async with factory() as session:
            await SelfHealService(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            ).apply(
                case_id,
                SelectorRepairApplyRequest(
                    step_id=proposal.step_id,
                    old_selector=proposal.old_selector,
                    new_selector=proposal.new_selector,
                    code_sha256=proposal.code_sha256,
                    rationale=proposal.rationale,
                ),
                actor_type="agent",
            )
            await session.commit()
    except SelfHealError as exc:
        log.warning(
            "runner.self_heal.persist_skip",
            step_id=proposal.step_id,
            code=exc.code,
            reason=exc.message,
        )
        return False
    except Exception as exc:
        log.warning(
            "runner.self_heal.persist_error",
            step_id=proposal.step_id,
            reason=str(exc),
        )
        return False
    return True


def _build_highlight_script(selector: str) -> str:
    """Build a resilient multi-strategy DOM element highlight script.

    Supports standard CSS selectors, XPath expressions (// or xpath=), and
    Playwright text locators (text= or :has-text()). Automatically clears any
    prior highlighted elements and wraps execution in try/catch to ensure
    it never throws DOMExceptions or disrupts test execution.
    """
    sel_json = json.dumps(selector)
    return (
        "(() => {"
        " try {"
        " document.querySelectorAll('[data-suitest-highlight]').forEach(el => {"
        " el.style.outline = el.getAttribute('data-suitest-prev-outline') || '';"
        " el.style.outlineOffset = el.getAttribute('data-suitest-prev-offset') || '';"
        " el.style.boxShadow = el.getAttribute('data-suitest-prev-shadow') || '';"
        " el.removeAttribute('data-suitest-highlight');"
        " el.removeAttribute('data-suitest-prev-outline');"
        " el.removeAttribute('data-suitest-prev-offset');"
        " el.removeAttribute('data-suitest-prev-shadow');"
        " });"
        f" const sel = {sel_json};"
        " if (!sel || typeof sel !== 'string') return;"
        " let target = null;"
        " try { target = document.querySelector(sel); } catch (_) {}"
        " if (!target && sel.startsWith('id=')) {"
        " try {"
        " const val = sel.slice(3).replace(/^['\"]|['\"]$/g, '');"
        ' target = document.getElementById(val) || document.querySelector(`[id="${val}"]`);'
        " } catch (_) {}"
        " }"
        " if (!target && sel.startsWith('name=')) {"
        " try {"
        " const val = sel.slice(5).replace(/^['\"]|['\"]$/g, '');"
        ' target = document.querySelector(`[name="${val}"]`);'
        " } catch (_) {}"
        " }"
        " if (!target && (sel.startsWith('data-testid=') || sel.startsWith('data-test-id='))) {"
        " try {"
        " const prefixLen = sel.startsWith('data-testid=') ? 12 : 13;"
        " const val = sel.slice(prefixLen).replace(/^['\"]|['\"]$/g, '');"
        ' target = document.querySelector(`[data-testid="${val}"], [data-test-id="${val}"]`);'
        " } catch (_) {}"
        " }"
        " if (!target && sel.startsWith('data-test=')) {"
        " try {"
        " const val = sel.slice(10).replace(/^['\"]|['\"]$/g, '');"
        ' target = document.querySelector(`[data-test="${val}"]`);'
        " } catch (_) {}"
        " }"
        " if (!target && sel.startsWith('role=')) {"
        " try {"
        " const roleMatch = sel.slice(5).match(/^([a-zA-Z0-9_-]+)/);"
        " if (roleMatch) {"
        " const r = roleMatch[1];"
        ' target = document.querySelector(`[role="${r}"]`);'
        " if (!target) {"
        ' const tagMap = { button: \'button, input[type="button"], input[type="submit"]\', link: \'a\', textbox: \'input:not([type="button"]):not([type="submit"]):not([type="reset"]), textarea\', checkbox: \'input[type="checkbox"]\', radio: \'input[type="radio"]\' };'
        " if (tagMap[r]) target = document.querySelector(tagMap[r]);"
        " }"
        " }"
        " } catch (_) {}"
        " }"
        " if (!target && (sel.startsWith('//') || sel.startsWith('xpath='))) {"
        " try {"
        " const xp = sel.startsWith('xpath=') ? sel.slice(6) : sel;"
        " const res = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);"
        " if (res && res.singleNodeValue && res.singleNodeValue.nodeType === Node.ELEMENT_NODE) target = res.singleNodeValue;"
        " } catch (_) {}"
        " }"
        " if (!target && (sel.startsWith('text=') || sel.includes(':has-text('))) {"
        " try {"
        " let needle = '';"
        " if (sel.startsWith('text=')) {"
        " needle = sel.slice(5).replace(/^['\"]|['\"]$/g, '').trim().toLowerCase();"
        " } else {"
        " const m = sel.match(/:has-text\\((['\"]?)(.*?)\\1\\)/);"
        " if (m && m[2]) needle = m[2].trim().toLowerCase();"
        " }"
        " if (needle) {"
        " const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);"
        " let node;"
        " while ((node = walker.nextNode())) {"
        " const txt = (node.textContent || '').trim().toLowerCase();"
        " if (txt.includes(needle)) { target = node; break; }"
        " }"
        " }"
        " } catch (_) {}"
        " }"
        " if (target && target.nodeType === Node.ELEMENT_NODE) {"
        " try { target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' }); } catch (_) {}"
        " target.setAttribute('data-suitest-highlight', 'true');"
        " target.setAttribute('data-suitest-prev-outline', target.style.outline || '');"
        " target.setAttribute('data-suitest-prev-offset', target.style.outlineOffset || '');"
        " target.setAttribute('data-suitest-prev-shadow', target.style.boxShadow || '');"
        " target.style.outline = '4px solid #2563eb';"
        " target.style.outlineOffset = '4px';"
        " target.style.boxShadow = '0 0 0 3px #ffffff, 0 0 0 7px #2563eb, 0 0 24px 8px rgba(37,99,235,0.6)';"
        " }"
        " } catch (_) {}"
        "})()"
    )


def _build_clear_highlight_script() -> str:
    """Build a DOM script that cleanly removes any existing Suitest highlight attributes and styles."""
    return (
        "(() => {"
        " try {"
        " document.querySelectorAll('[data-suitest-highlight]').forEach(el => {"
        " el.style.outline = el.getAttribute('data-suitest-prev-outline') || '';"
        " el.style.outlineOffset = el.getAttribute('data-suitest-prev-offset') || '';"
        " el.style.boxShadow = el.getAttribute('data-suitest-prev-shadow') || '';"
        " el.removeAttribute('data-suitest-highlight');"
        " el.removeAttribute('data-suitest-prev-outline');"
        " el.removeAttribute('data-suitest-prev-offset');"
        " el.removeAttribute('data-suitest-prev-shadow');"
        " });"
        " } catch (_) {}"
        "})()"
    )


class _VideoManager:
    def __init__(
        self,
        *,
        video_mode: str,
        video_size: dict[str, int],
        viewport_dim: str,
        target_pw_provider: str,
        workspace_id: str,
        run_id: str,
        triggered_by: str | None,
        overrides: dict[str, object] | None,
        invoker: McpInvoker,
        factory: Any,
        ctx: dict[str, object],
        case_public_ids: dict[str, str],
    ) -> None:
        self.video_mode = video_mode
        self.video_size = video_size
        self.viewport_dim = viewport_dim
        self.target_pw_provider = target_pw_provider
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.triggered_by = triggered_by
        self.overrides = overrides
        self.invoker = invoker
        self.factory = factory
        self.ctx = ctx
        self.case_public_ids = case_public_ids
        self.active = False
        self.active_case_id: str | None = None

    async def start(self, case_id: str) -> None:
        if self.video_mode not in ("on", "retain-on-failure") or self.active:
            return
        start_ctx = InvokeContext(
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            step_id=None,
            actor_user_id=self.triggered_by,
            target_kind=TargetKind.FE_WEB,
            routing_overrides=self.overrides,
        )
        try:
            vp_parts = self.viewport_dim.split("x")
            vp_w = int(vp_parts[0]) if len(vp_parts) == 2 else 1920
            vp_h = int(vp_parts[1]) if len(vp_parts) == 2 else 1080
            await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_resize",
                arguments={"width": vp_w, "height": vp_h},
                ctx=start_ctx,
            )
        except Exception as exc:
            log.debug("runner.video.resize_before_video_skipped", case_id=case_id, error=str(exc))

        try:
            await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_start_video",
                arguments={"size": self.video_size},
                ctx=start_ctx,
            )
            self.active = True
            self.active_case_id = case_id
        except Exception as exc:
            log.warning("runner.video.start_failed", case_id=case_id, error=str(exc))

    async def stop(
        self,
        case_id: str,
        *,
        has_failure: bool,
        last_step_info: tuple[str, int] | None,
    ) -> None:
        if not self.active or self.active_case_id != case_id:
            return
        self.active = False
        self.active_case_id = None
        if self.video_mode not in ("on", "retain-on-failure"):
            return
        stop_ctx = InvokeContext(
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            step_id=None,
            actor_user_id=self.triggered_by,
            target_kind=TargetKind.FE_WEB,
            routing_overrides=self.overrides,
        )
        try:
            stop_res = await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_stop_video",
                arguments={},
                ctx=stop_ctx,
            )
        except Exception as exc:
            log.warning("runner.video.stop_failed", case_id=case_id, error=str(exc))
            return

        match = re.search(r"-\s*\[(?:Video|video)\]\(([^)]+)\)", stop_res.stdout)
        if not match:
            log.debug("runner.video.path_not_found", stdout=stop_res.stdout)
            return

        video_rel = match.group(1).strip()
        video_path = Path(video_rel)
        if not video_path.is_absolute():
            video_path = Path.cwd() / video_path

        should_keep = self.video_mode == "on" or (
            self.video_mode == "retain-on-failure" and has_failure
        )

        try:
            if should_keep and video_path.is_file():
                raw_bytes = video_path.read_bytes()
                if last_step_info is not None and raw_bytes:
                    from suitest_runner.artifacts import upload_artifacts

                    last_step_id, last_step_order = last_step_info
                    case_pub = self.case_public_ids.get(case_id, "case")
                    video_art = McpArtifact(
                        kind="VIDEO",
                        filename=f"{case_pub.lower()}-video.webm",
                        content_type="video/webm",
                        bytes=raw_bytes,
                    )
                    async with self.factory() as session:
                        await upload_artifacts(
                            session=session,
                            ctx=self.ctx,
                            run_id=self.run_id,
                            run_step_id=last_step_id,
                            step_order=last_step_order,
                            artifacts=[video_art],
                        )
                        await session.commit()
        except Exception as exc:
            log.warning("runner.video.upload_failed", case_id=case_id, error=str(exc))
        finally:
            if video_path.is_file():
                with contextlib.suppress(Exception):
                    video_path.unlink()


class _HighlightManager:
    def __init__(
        self,
        *,
        enabled: bool,
        target_pw_provider: str,
        workspace_id: str,
        run_id: str,
        triggered_by: str | None,
        overrides: dict[str, object] | None,
        invoker: McpInvoker,
    ) -> None:
        self.enabled = enabled
        self.target_pw_provider = target_pw_provider
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.triggered_by = triggered_by
        self.overrides = overrides
        self.invoker = invoker

    def _ctx(self, step_id: str, target_kind: Any) -> InvokeContext:
        return InvokeContext(
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            step_id=step_id,
            actor_user_id=self.triggered_by,
            target_kind=TargetKind(target_kind),
            routing_overrides=self.overrides,
        )

    async def pre_clear(self, step_id: str, target_kind: Any, is_web_step: bool) -> None:
        if not self.enabled or not is_web_step:
            return
        try:
            ctx = self._ctx(step_id, target_kind)
            js = _build_clear_highlight_script()
            await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_evaluate",
                arguments={"function": js, "script": js},
                ctx=ctx,
            )
        except Exception as err:
            log.debug("runner.highlight.pre_clear_failed", error=str(err))

    async def apply(
        self, step_id: str, target_kind: Any, is_web_step: bool, code: str | None
    ) -> tuple[bool, str | None]:
        if not self.enabled or not is_web_step or not code:
            return False, None
        try:
            parsed = json.loads(code)
            if isinstance(parsed, dict):
                sel = _extract_target_selector(parsed)
                if sel:
                    ctx = self._ctx(step_id, target_kind)
                    js = _build_highlight_script(sel)
                    await self.invoker.invoke(
                        explicit_provider=self.target_pw_provider,
                        tool="browser_evaluate",
                        arguments={"function": js, "script": js},
                        ctx=ctx,
                    )
                    await asyncio.sleep(0.20)
                    return True, sel
        except Exception as exc:
            log.debug("runner.highlight.failed", error=str(exc))
        return False, None

    async def reapply(self, step_id: str, target_kind: Any, target_sel: str | None) -> None:
        if not self.enabled or not target_sel:
            return
        try:
            ctx = self._ctx(step_id, target_kind)
            js = _build_highlight_script(target_sel)
            await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_evaluate",
                arguments={"function": js, "script": js},
                ctx=ctx,
            )
            await asyncio.sleep(0.10)
        except Exception as err:
            log.debug("runner.highlight.reapply_failed", error=str(err))

    async def post_clear(self, step_id: str, target_kind: Any) -> None:
        if not self.enabled:
            return
        try:
            ctx = self._ctx(step_id, target_kind)
            js = _build_clear_highlight_script()
            await self.invoker.invoke(
                explicit_provider=self.target_pw_provider,
                tool="browser_evaluate",
                arguments={"function": js, "script": js},
                ctx=ctx,
            )
        except Exception as err:
            log.debug("runner.highlight.clear_failed", error=str(err))


async def _maybe_capture_screenshot(
    *,
    result: StepResult,
    is_web_step: bool,
    screenshot_mode: str,
    target_pw_provider: str,
    test_step: Any,
    invoker: McpInvoker,
    workspace_id: str,
    run_id: str,
    triggered_by: str | None,
    overrides: dict[str, object] | None,
) -> None:
    artifacts = result.mcp_result.artifacts if result.mcp_result is not None else []
    has_shot = _has_screenshot_artifact(artifacts)
    has_failure = result.outcome in (StepOutcome.FAIL, StepOutcome.ERROR)
    should_capture = is_web_step and (
        (not has_shot and screenshot_mode == "on")
        or (has_failure and screenshot_mode in ("on", "only-on-failure"))
    )
    if not should_capture:
        return
    try:
        if has_failure:
            await asyncio.sleep(0.25)
        else:
            await asyncio.sleep(0.15)
        shot_ctx = InvokeContext(
            workspace_id=workspace_id,
            run_id=run_id,
            step_id=test_step.id,
            actor_user_id=triggered_by,
            target_kind=TargetKind(test_step.target_kind),
            routing_overrides=overrides,
        )
        shot_res = await invoker.invoke(
            explicit_provider=target_pw_provider if is_web_step else test_step.mcp_provider,
            tool="browser_take_screenshot",
            arguments={},
            ctx=shot_ctx,
        )
        if shot_res.artifacts:
            if result.mcp_result is None:
                result.mcp_result = shot_res
            else:
                result.mcp_result.artifacts.extend(shot_res.artifacts)
    except Exception as exc:
        log.warning(
            "runner.auto_screenshot.failed",
            run_id=run_id,
            step_id=test_step.id,
            error=str(exc),
        )


async def _finalize_skipped_cases(
    session: AsyncSession,
    *,
    run_id: str,
    planned_case_ids: set[str],
    executed_case_ids: set[str],
    completed_time: datetime,
    cancelled: bool,
) -> None:
    skipped_case_ids = planned_case_ids - executed_case_ids
    if not skipped_case_ids:
        return
    skip_status = "CANCELLED" if cancelled else "SKIP"
    await session.execute(
        update(TestCase)
        .where(TestCase.id.in_(skipped_case_ids))
        .values(
            last_run_id=run_id,
            last_run_at=completed_time,
            last_run_result=skip_status,
            last_duration_ms=0,
        )
    )


def _determine_final_run_status(
    summary: dict[str, int],
    *,
    cancelled: bool,
    run_id: str,
) -> RunStatus:
    if cancelled:
        return RunStatus.CANCELLED
    if summary["total"] == 0:
        log.warning("runner.run.empty_selection", run_id=run_id)
        return RunStatus.ERROR
    if summary["failed"] > 0:
        return RunStatus.FAIL
    if summary["errored"] > 0:
        return RunStatus.ERROR
    return RunStatus.PASS


async def _finalize_run(
    *,
    factory: Any,
    redis_client: object,
    invoker: McpInvoker,
    run_id: str,
    workspace_id: str,
    headless_mode: bool,
    clean_session: bool,
    selection: list[Any],
    summary: dict[str, int],
    case_outcome: dict[str, str],
    case_has_failure: dict[str, bool],
    case_duration_ms: dict[str, int],
    current_case_id: str | None,
    t0: float,
    cancelled: bool,
) -> dict[str, object]:
    total_planned_steps = len(selection)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    failed_total = summary["failed"] + summary["errored"]
    final_status = _determine_final_run_status(
        summary,
        cancelled=cancelled,
        run_id=run_id,
    )

    async with factory() as session:
        completed_time = datetime.now(UTC)
        run_row = await RunRepo(session).get_by_id(run_id)
        if run_row is not None and run_row.status in (
            RunStatus.INTERRUPTED,
            RunStatus.CANCELLED,
        ):
            log.info(
                "runner.finalize.skip_terminal_status",
                run_id=run_id,
                status=run_row.status.value,
            )
            final_status = run_row.status
        else:
            await RunRepo(session).update_status(
                run_id,
                final_status,
                completed_at=completed_time,
                duration_ms=duration_ms,
                total_steps=total_planned_steps,
                passed_steps=summary["passed"],
                failed_steps=failed_total,
            )
            if summary["total"] == 0 and run_row is not None:
                meta = dict(run_row.metadata_json or {})
                if not meta.get("error"):
                    meta["error"] = "Cannot execute run: selected test cases contain no steps"
                    run_row.metadata_json = meta
        planned_cases: list[Any] = []
        if run_row is not None and isinstance(run_row.metadata_json, dict):
            planned_cases = run_row.metadata_json.get("planned_cases") or []
        planned_case_ids = {
            item["case_id"]
            for item in planned_cases
            if isinstance(item, dict) and isinstance(item.get("case_id"), str)
        }

        executed_case_ids = {c_id for c_id, _, _ in selection if c_id}
        if executed_case_ids:
            status_whens = []
            dur_whens = []
            for c_id in executed_case_ids:
                c_status = case_outcome.get(
                    c_id,
                    "FAIL" if case_has_failure.get(c_id, False) else "PASS",
                )
                if cancelled and c_id == current_case_id and not case_has_failure.get(c_id, False):
                    c_status = "CANCELLED"
                c_dur = case_duration_ms.get(c_id, 0)
                status_whens.append((TestCase.id == c_id, c_status))
                dur_whens.append((TestCase.id == c_id, c_dur))

            await session.execute(
                update(TestCase)
                .where(TestCase.id.in_(executed_case_ids))
                .values(
                    last_run_id=run_id,
                    last_run_at=completed_time,
                    last_run_result=case(*status_whens, else_=TestCase.last_run_result),
                    last_duration_ms=case(*dur_whens, else_=TestCase.last_duration_ms),
                )
            )

        await _finalize_skipped_cases(
            session,
            run_id=run_id,
            planned_case_ids=planned_case_ids,
            executed_case_ids=executed_case_ids,
            completed_time=completed_time,
            cancelled=cancelled,
        )
        await session.commit()

    await _publish(
        redis_client,
        run_id,
        "run.completed",
        {
            "runId": run_id,
            "status": final_status.value,
            "totalSteps": total_planned_steps,
            "passedSteps": summary["passed"],
            "failedSteps": failed_total,
            "durationMs": duration_ms,
        },
        factory=factory,
    )

    if summary["failed"] > 0 and not cancelled:
        await _try_file_defect(factory, run_id)

    if clean_session and hasattr(invoker, "pool") and hasattr(invoker.pool, "recycle_provider"):
        try:
            target_provider = (
                f"builtin:playwright-mcp:{workspace_id}"
                if headless_mode
                else f"builtin:playwright-mcp:{workspace_id}:headed"
            )
            await invoker.pool.recycle_provider(target_provider)
        except Exception as exc:
            log.debug("runner.clean_session.final_recycle_failed", error=str(exc))

    return {
        "run_id": run_id,
        "status": final_status.value,
        "total": summary["total"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "errored": summary["errored"],
        "skipped": summary["skipped"],
    }


async def _init_run_record(
    factory: Any,
    registry: McpRegistry,
    run_id: str,
) -> (
    tuple[
        Run,
        list[tuple[str, int, TestStep]],
        dict[str, str],
        str,
        dict[str, object] | None,
        StepTranslator | None,
        bool,
        str | None,
    ]
    | dict[str, object]
):
    async with factory() as session:
        run_repo = RunRepo(session)
        run, selection = await run_repo.get_with_selection(run_id)
        if run is None:
            log.warning("runner.job.missing_run", run_id=run_id)
            return {"error": "RUN_NOT_FOUND", "run_id": run_id}

        case_ids = {case_id for case_id, _, _ in selection}
        case_public_ids: dict[str, str] = {}
        if case_ids and hasattr(session, "execute"):
            try:
                cases_stmt = select(TestCase.id, TestCase.public_id).where(
                    TestCase.id.in_(case_ids)
                )
                case_public_ids = dict(
                    (str(r[0]), str(r[1])) for r in (await session.execute(cases_stmt)).all()
                )
            except Exception as exc:
                log.debug("runner.case_public_ids.query_failed", error=str(exc))

        project = await session.get(Project, run.project_id)
        workspace_id = project.workspace_id if project is not None else None
        if workspace_id is None:
            log.warning("runner.job.missing_project", run_id=run_id)
            await run_repo.update_status(run_id, RunStatus.FAIL)
            await session.commit()
            return {"error": "RUN_PROJECT_MISSING", "run_id": run_id}

        if workspace_id not in registry._by_workspace:
            await registry.load_for_workspace(session, workspace_id)

        capability = await WorkspaceCapabilityRepo(session).get(workspace_id)
        auto_self_heal = _auto_self_heal_enabled(capability)
        overrides_raw = capability.features_json.get("routing_overrides") if capability else None
        overrides: dict[str, object] | None = (
            overrides_raw if isinstance(overrides_raw, dict) else None
        )
        triggered_by = run.triggered_by
        translator = await _build_translator(session, workspace_id=workspace_id)

        total_planned_steps = len(selection)
        await run_repo.update_status(
            run_id,
            RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            total_steps=total_planned_steps,
            passed_steps=0,
            failed_steps=0,
        )
        await session.commit()

    return (
        run,
        selection,
        case_public_ids,
        workspace_id,
        overrides,
        translator,
        auto_self_heal,
        triggered_by,
    )


async def _execute_and_heal_step(
    *,
    invoker: McpInvoker,
    test_step: TestStep,
    case_id: str,
    run_id: str,
    workspace_id: str,
    triggered_by: str | None,
    overrides: dict[str, object] | None,
    translator: StepTranslator | None,
    auto_self_heal: bool,
    factory: Any,
    highlight_applied: bool,
    target_sel: str | None,
    highlight_mgr: _HighlightManager,
    is_web_step: bool,
    screenshot_mode: str,
    target_pw_provider: str,
) -> tuple[StepResult, bool, dict[str, object] | None]:
    try:
        result = await execute_step(
            invoker=invoker,
            test_step=test_step,
            run_id=run_id,
            workspace_id=workspace_id,
            actor_user_id=triggered_by,
            routing_overrides=overrides,
            translator=translator,
        )
        selector_change_detected = is_selector_changed_failure(
            test_step.code,
            result.error_message,
        )
        self_heal_state: dict[str, object] | None = None
        if auto_self_heal and result.outcome == StepOutcome.FAIL:
            original_error = result.error_message
            repair_proposal = await _try_auto_self_heal(
                factory=factory,
                test_step=test_step,
                case_id=case_id,
                workspace_id=workspace_id,
                user_id=triggered_by,
                result=result,
            )
            if repair_proposal is not None:
                self_heal_state = {
                    "failureKind": "selector_changed",
                    "oldSelector": repair_proposal.old_selector,
                    "newSelector": repair_proposal.new_selector,
                    "retryCount": 1,
                }
                result = await execute_step(
                    invoker=invoker,
                    test_step=test_step,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    actor_user_id=triggered_by,
                    routing_overrides=overrides,
                    translator=translator,
                )
                self_heal_state["originalError"] = original_error or ""
                self_heal_state["retryOutcome"] = result.outcome.value
                self_heal_state["persisted"] = (
                    await _persist_auto_self_heal(
                        factory=factory,
                        case_id=case_id,
                        workspace_id=workspace_id,
                        user_id=triggered_by,
                        proposal=repair_proposal,
                    )
                    if result.outcome == StepOutcome.PASS
                    else False
                )

        if highlight_applied and target_sel:
            await highlight_mgr.reapply(test_step.id, test_step.target_kind, target_sel)

        await _maybe_capture_screenshot(
            result=result,
            is_web_step=is_web_step,
            screenshot_mode=screenshot_mode,
            target_pw_provider=target_pw_provider,
            test_step=test_step,
            invoker=invoker,
            workspace_id=workspace_id,
            run_id=run_id,
            triggered_by=triggered_by,
            overrides=overrides,
        )
    finally:
        if highlight_applied:
            await highlight_mgr.post_clear(test_step.id, test_step.target_kind)
    return result, selector_change_detected, self_heal_state


async def _record_step_persistence(
    *,
    factory: Any,
    ctx: dict[str, object],
    redis_client: object,
    run_id: str,
    case_id: str,
    step_order: int,
    test_step: TestStep,
    result: StepResult,
    selector_change_detected: bool,
    self_heal_state: dict[str, object] | None,
    summary: dict[str, int],
) -> tuple[bool, tuple[str, int]]:
    cancelled = False
    async with factory() as session:
        run_step_repo = RunStepRepo(session)
        state_snap = {
            **(
                dict(result.mcp_result.output)
                if result.mcp_result is not None and result.mcp_result.output
                else {}
            ),
            **({"failureKind": "selector_changed"} if selector_change_detected else {}),
            **({"selfHeal": self_heal_state} if self_heal_state else {}),
            **(
                {"action": test_step.action, "description": test_step.action}
                if test_step.action
                else {}
            ),
        } or None
        run_step = await run_step_repo.create_step(
            run_id=run_id,
            case_id=case_id,
            step_order=step_order,
            outcome=result.outcome,
            started_at=result.started_at,
            completed_at=result.completed_at,
            duration_ms=result.duration_ms,
            stdout=result.stdout or None,
            stderr=result.stderr or None,
            error_message=result.error_message,
            state_snapshot=state_snap,
        )
        if result.mcp_result is not None and result.mcp_result.artifacts:
            from suitest_runner.artifacts import upload_artifacts

            await upload_artifacts(
                session=session,
                ctx=ctx,
                run_id=run_id,
                run_step_id=run_step.id,
                step_order=step_order,
                artifacts=result.mcp_result.artifacts,
            )
        repo = RunRepo(session)
        r_check = await repo.get_by_id(run_id)
        if r_check is not None and r_check.status == RunStatus.CANCELLED:
            cancelled = True
        else:
            await repo.update_status(
                run_id,
                RunStatus.RUNNING,
                passed_steps=summary["passed"],
                failed_steps=summary["failed"] + summary["errored"],
            )
        await session.commit()
        last_step_info = (run_step.id, step_order)
    if result.outcome == StepOutcome.FAIL:
        auto_filer = ctx.get("defect_auto_filer")
        typed_filer: DefectAutoFiler | None = (
            cast("DefectAutoFiler", auto_filer) if _is_defect_auto_filer(auto_filer) else None
        )
        try:
            await on_run_step_failed(
                auto_filer=typed_filer,
                run_step=run_step,
            )
        except Exception as exc:
            log.warning("runner.step.fail.hook_error", reason=str(exc))

    if not cancelled:
        await _publish(
            redis_client,
            run_id,
            "run.step.completed",
            {
                "runId": run_id,
                "stepIndex": step_order,
                "outcome": result.outcome.value,
                "durationMs": result.duration_ms,
                "error": result.error_message,
                "failureKind": ("selector_changed" if selector_change_detected else None),
                "selfHeal": self_heal_state,
            },
            factory=factory,
            run_step_id=run_step.id,
        )
    return cancelled, last_step_info


def _update_outcomes(
    *,
    result: StepResult,
    case_id: str,
    summary: dict[str, int],
    case_outcome: dict[str, str],
    case_has_failure: dict[str, bool],
    failed_case_ids: set[str],
) -> None:
    if result.outcome == StepOutcome.PASS:
        summary["passed"] += 1
        if case_outcome.get(case_id) not in ("FAIL", "ERROR"):
            case_outcome[case_id] = "PASS"
    elif result.outcome == StepOutcome.FAIL:
        summary["failed"] += 1
        failed_case_ids.add(case_id)
        case_has_failure[case_id] = True
        case_outcome[case_id] = "FAIL"
    elif result.outcome == StepOutcome.ERROR:
        summary["errored"] += 1
        failed_case_ids.add(case_id)
        case_has_failure[case_id] = True
        if case_outcome.get(case_id) != "FAIL":
            case_outcome[case_id] = "ERROR"
    elif result.outcome == StepOutcome.SKIP:
        summary["skipped"] += 1
        if case_id not in case_outcome:
            case_outcome[case_id] = "SKIP"


def _build_runtime_managers(
    *,
    run: Run,
    workspace_id: str,
    run_id: str,
    triggered_by: str | None,
    overrides: dict[str, object] | None,
    registry: McpRegistry,
    invoker: McpInvoker,
    factory: Any,
    ctx: dict[str, object],
    case_public_ids: dict[str, str],
) -> tuple[_VideoManager, _HighlightManager, str, str, bool, bool]:
    playwright_cfg = (run.metadata_json or {}).get("playwright_config")
    if not isinstance(playwright_cfg, dict):
        playwright_cfg = {}
    screenshot_mode = str(playwright_cfg.get("screenshot") or "only-on-failure")
    highlight_steps = bool(
        playwright_cfg.get("highlight_steps") or playwright_cfg.get("highlightSteps", False)
    )
    headless_mode = bool(playwright_cfg.get("headless", True))
    video_mode = str(playwright_cfg.get("video") or "off")
    if highlight_steps and headless_mode and screenshot_mode == "off" and video_mode == "off":
        highlight_steps = False
    video_quality = str(
        playwright_cfg.get("video_quality") or playwright_cfg.get("videoQuality") or "1080p"
    )
    quality_sizes: dict[str, dict[str, int]] = {
        "360p": {"width": 640, "height": 360},
        "480p": {"width": 854, "height": 480},
        "720p": {"width": 1280, "height": 720},
        "1080p": {"width": 1920, "height": 1080},
    }
    video_size = quality_sizes.get(video_quality, {"width": 1920, "height": 1080})
    clean_session = bool(
        playwright_cfg.get(
            "clean_session_between_cases",
            playwright_cfg.get("cleanSessionBetweenCases", True),
        )
    )

    raw_vp = playwright_cfg.get("viewport") or playwright_cfg.get("viewport_size")
    if raw_vp and isinstance(raw_vp, str):
        viewport_dim = raw_vp
    elif raw_vp and isinstance(raw_vp, dict) and "width" in raw_vp and "height" in raw_vp:
        viewport_dim = f"{raw_vp['width']}x{raw_vp['height']}"
    else:
        viewport_dim = "1920x1080"
    registry.register_provider(
        workspace_id,
        build_playwright_provider(
            workspace_id,
            headless=headless_mode,
            video=video_mode,
            viewport_size=viewport_dim,
        ),
    )

    target_pw_provider = (
        f"builtin:playwright-mcp:{workspace_id}"
        if headless_mode
        else f"builtin:playwright-mcp:{workspace_id}:headed"
    )

    video_mgr = _VideoManager(
        video_mode=video_mode,
        video_size=video_size,
        viewport_dim=viewport_dim,
        target_pw_provider=target_pw_provider,
        workspace_id=workspace_id,
        run_id=run_id,
        triggered_by=triggered_by,
        overrides=overrides,
        invoker=invoker,
        factory=factory,
        ctx=ctx,
        case_public_ids=case_public_ids,
    )
    highlight_mgr = _HighlightManager(
        enabled=highlight_steps,
        target_pw_provider=target_pw_provider,
        workspace_id=workspace_id,
        run_id=run_id,
        triggered_by=triggered_by,
        overrides=overrides,
        invoker=invoker,
    )
    return (
        video_mgr,
        highlight_mgr,
        target_pw_provider,
        screenshot_mode,
        headless_mode,
        clean_session,
    )


async def _handle_case_transition(
    *,
    case_id: str,
    current_case_id: str | None,
    video_mgr: _VideoManager,
    case_has_failure: dict[str, bool],
    last_run_step_by_case: dict[str, tuple[str, int]],
    clean_session: bool,
    invoker: McpInvoker,
    target_pw_provider: str,
) -> None:
    if current_case_id is not None and case_id != current_case_id:
        await video_mgr.stop(
            current_case_id,
            has_failure=case_has_failure.get(current_case_id, False),
            last_step_info=last_run_step_by_case.get(current_case_id),
        )
        if clean_session and hasattr(invoker, "pool") and hasattr(invoker.pool, "recycle_provider"):
            try:
                await invoker.pool.recycle_provider(target_pw_provider)
            except Exception as exc:
                log.warning("runner.clean_session.recycle_failed", error=str(exc))


@contextlib.asynccontextmanager
async def _step_heartbeat(
    factory: Any, run_id: str, interval_seconds: float = 60.0
) -> AsyncIterator[None]:
    """Periodically touch run.updated_at while a step is actively executing.

    Guarantees long-running steps (e.g. Playwright waits or deployments) are not
    falsely declared INTERRUPTED by the API while the runner is healthy.
    """
    stop_event = asyncio.Event()

    async def _heartbeat_loop() -> None:
        while not stop_event.is_set():
            try:
                await asyncio.sleep(interval_seconds)
                if stop_event.is_set():
                    break
                if callable(factory):
                    async with factory() as session:
                        r = await RunRepo(session).get_by_id(run_id)
                        if r is not None:
                            if r.status in (RunStatus.CANCELLED, RunStatus.INTERRUPTED):
                                break
                            r.updated_at = datetime.now(UTC)
                            await session.commit()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.debug("runner.step_heartbeat.error", run_id=run_id, error=str(exc))

    task = asyncio.create_task(_heartbeat_loop())
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _is_run_cancelled(factory: Any, run_id: str) -> bool:
    """Check whether the run has been cancelled or interrupted."""
    async with factory() as session:
        r_check = await RunRepo(session).get_by_id(run_id)
        if r_check is not None:
            if r_check.status in (RunStatus.CANCELLED, RunStatus.INTERRUPTED):
                return True
            r_check.updated_at = datetime.now(UTC)
            await session.commit()
        return False


async def _run_test_case_body(ctx: dict[str, object], run_id: str) -> dict[str, object]:
    """Execute one test run."""
    factory = ctx.get("session_factory")
    redis_client = ctx.get("redis")
    invoker = ctx.get("invoker")
    registry = ctx.get("registry")
    if not callable(factory):
        return {"error": "RUNNER_CTX_INVALID", "field": "session_factory"}
    if not isinstance(invoker, McpInvoker):
        return {"error": "RUNNER_CTX_INVALID", "field": "invoker"}
    if not isinstance(registry, McpRegistry):
        return {"error": "RUNNER_CTX_INVALID", "field": "registry"}

    tracer = get_tracer()
    with tracer.start_as_current_span(
        "runner.run_test_case",
        attributes={"job.queue": "suitest:runs", "run.id": run_id},
    ):
        init_res = await _init_run_record(factory, registry, run_id)
        if isinstance(init_res, dict):
            return init_res
        (
            run,
            selection,
            case_public_ids,
            workspace_id,
            overrides,
            translator,
            auto_self_heal,
            triggered_by,
        ) = init_res

        await _publish(
            redis_client,
            run_id,
            "run.started",
            {"runId": run_id},
            factory=factory,
        )

        (
            video_mgr,
            highlight_mgr,
            target_pw_provider,
            screenshot_mode,
            headless_mode,
            clean_session,
        ) = _build_runtime_managers(
            run=run,
            workspace_id=workspace_id,
            run_id=run_id,
            triggered_by=triggered_by,
            overrides=overrides,
            registry=registry,
            invoker=invoker,
            factory=factory,
            ctx=ctx,
            case_public_ids=case_public_ids,
        )

        summary = {"total": 0, "passed": 0, "failed": 0, "errored": 0, "skipped": 0}
        t0 = time.perf_counter()
        cancelled = False
        failed_case_ids: set[str] = set()
        current_case_id: str | None = None
        last_run_step_by_case: dict[str, tuple[str, int]] = {}
        case_has_failure: dict[str, bool] = {}
        case_duration_ms: dict[str, int] = {}
        case_outcome: dict[str, str] = {}

        playwright_cfg = (run.metadata_json or {}).get("playwright_config")
        if not isinstance(playwright_cfg, dict):
            playwright_cfg = {}
        prevent_sleep = bool(
            playwright_cfg.get(
                "prevent_sleep",
                playwright_cfg.get("preventSleep", False),
            )
        )
        sleep_ctx = (
            async_prevent_sleep(f"suitest-run-{run_id}")
            if prevent_sleep
            else contextlib.nullcontext()
        )

        async with sleep_ctx:
            for case_id, step_order, test_step in selection:
                await _handle_case_transition(
                    case_id=case_id,
                    current_case_id=current_case_id,
                    video_mgr=video_mgr,
                    case_has_failure=case_has_failure,
                    last_run_step_by_case=last_run_step_by_case,
                    clean_session=clean_session,
                    invoker=invoker,
                    target_pw_provider=target_pw_provider,
                )
                current_case_id = case_id
                if await _is_run_cancelled(factory, run_id):
                    log.info("runner.job.cancelled_by_user", run_id=run_id)
                    cancelled = True
                    break

                if case_id in failed_case_ids:
                    log.info(
                        "runner.step.skip_after_case_failure",
                        run_id=run_id,
                        case_id=case_id,
                        step_order=step_order,
                    )
                    continue

                step_target_kind = (
                    test_step.target_kind.value
                    if hasattr(test_step.target_kind, "value")
                    else str(test_step.target_kind)
                )
                is_web_step = (
                    step_target_kind in ("FE_WEB", "web", "frontend")
                    or (test_step.mcp_provider and "playwright" in test_step.mcp_provider)
                    or not test_step.mcp_provider
                )
                if is_web_step:
                    await video_mgr.start(case_id)

                summary["total"] += 1
                await _publish(
                    redis_client,
                    run_id,
                    "run.step.started",
                    {
                        "runId": run_id,
                        "stepIndex": step_order,
                        "action": test_step.action,
                        "mcpProvider": test_step.mcp_provider,
                        "targetKind": step_target_kind,
                    },
                    factory=factory,
                )

                await highlight_mgr.pre_clear(test_step.id, test_step.target_kind, is_web_step)
                highlight_applied, target_sel = await highlight_mgr.apply(
                    test_step.id, test_step.target_kind, is_web_step, test_step.code
                )

                async with _step_heartbeat(factory, run_id):
                    (
                        result,
                        selector_change_detected,
                        self_heal_state,
                    ) = await _execute_and_heal_step(
                        invoker=invoker,
                        test_step=test_step,
                        case_id=case_id,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        triggered_by=triggered_by,
                        overrides=overrides,
                        translator=translator,
                        auto_self_heal=auto_self_heal,
                        factory=factory,
                        highlight_applied=highlight_applied,
                        target_sel=target_sel,
                        highlight_mgr=highlight_mgr,
                        is_web_step=is_web_step,
                        screenshot_mode=screenshot_mode,
                        target_pw_provider=target_pw_provider,
                    )

                case_duration_ms[case_id] = case_duration_ms.get(case_id, 0) + int(
                    result.duration_ms or 0
                )
                _update_outcomes(
                    result=result,
                    case_id=case_id,
                    summary=summary,
                    case_outcome=case_outcome,
                    case_has_failure=case_has_failure,
                    failed_case_ids=failed_case_ids,
                )

                cancelled, last_run_step_by_case[case_id] = await _record_step_persistence(
                    factory=factory,
                    ctx=ctx,
                    redis_client=redis_client,
                    run_id=run_id,
                    case_id=case_id,
                    step_order=step_order,
                    test_step=test_step,
                    result=result,
                    selector_change_detected=selector_change_detected,
                    self_heal_state=self_heal_state,
                    summary=summary,
                )
                if cancelled:
                    log.info("runner.job.cancelled_by_user", run_id=run_id)
                    break

                settings_obj = ctx.get("settings")
                if (
                    isinstance(settings_obj, RunnerSettings)
                    and settings_obj.evidence_recording
                    and settings_obj.evidence_pause_ms > 0
                ):
                    await asyncio.sleep(settings_obj.evidence_pause_ms / 1000)

                if getattr(result, "is_fatal_infra", False):
                    log.error(
                        "runner.job.fatal_infra_circuit_breaker",
                        run_id=run_id,
                        step_order=step_order,
                        error=result.error_message,
                    )
                    break

        if current_case_id is not None and video_mgr.active:
            await video_mgr.stop(
                current_case_id,
                has_failure=case_has_failure.get(current_case_id, False),
                last_step_info=last_run_step_by_case.get(current_case_id),
            )

        return await _finalize_run(
            factory=factory,
            redis_client=redis_client,
            invoker=invoker,
            run_id=run_id,
            workspace_id=workspace_id,
            headless_mode=headless_mode,
            clean_session=clean_session,
            selection=selection,
            summary=summary,
            case_outcome=case_outcome,
            case_has_failure=case_has_failure,
            case_duration_ms=case_duration_ms,
            current_case_id=current_case_id,
            t0=t0,
            cancelled=cancelled,
        )


async def run_test_case(ctx: dict[str, object], run_id: str) -> dict[str, object]:
    """Execute one test run."""
    import re

    if not isinstance(run_id, str) or not re.match(r"^[A-Za-z0-9_-]+$", run_id):
        return {"error": "INVALID_RUN_ID", "run_id": str(run_id)}
    factory = ctx.get("session_factory")
    tracer = get_tracer()
    try:
        with tracer.start_as_current_span(
            "runner.run_test_case",
            attributes={"job.queue": "suitest:runs", "run.id": run_id},
        ):
            return await _run_test_case_body(ctx=ctx, run_id=run_id)
    except asyncio.CancelledError:
        log.warning("runner.job.cancelled_or_interrupted", run_id=run_id)
        if callable(factory):
            async with factory() as session:
                repo = RunRepo(session)
                r = await repo.get_by_id(run_id)
                if r is not None and r.status not in (
                    RunStatus.PASS,
                    RunStatus.FAIL,
                    RunStatus.ERROR,
                    RunStatus.CANCELLED,
                    RunStatus.INTERRUPTED,
                ):
                    now = datetime.now(UTC)
                    r.status = RunStatus.CANCELLED
                    r.completed_at = now
                    meta = dict(r.metadata_json) if r.metadata_json else {}
                    meta["error"] = "Run execution was cancelled"
                    meta["interrupted"] = False
                    r.metadata_json = meta
                    await session.commit()
        raise
    except Exception as exc:
        log.error("runner.job.unhandled_exception", run_id=run_id, error=str(exc))
        if callable(factory):
            async with factory() as session:
                repo = RunRepo(session)
                r = await repo.get_by_id(run_id)
                if r is not None and r.status not in (
                    RunStatus.PASS,
                    RunStatus.FAIL,
                    RunStatus.ERROR,
                    RunStatus.CANCELLED,
                    RunStatus.INTERRUPTED,
                ):
                    now = datetime.now(UTC)
                    r.status = RunStatus.ERROR
                    r.completed_at = now
                    meta = dict(r.metadata_json) if r.metadata_json else {}
                    meta["error"] = f"Run failed with unexpected error: {exc}"
                    meta["interrupted"] = True
                    r.metadata_json = meta
                    await session.commit()
        return {"error": "UNHANDLED_EXCEPTION", "detail": str(exc), "run_id": run_id}


async def _publish(
    redis_client: object,
    run_id: str,
    event: str,
    data: dict[str, object],
    *,
    factory: object = None,
    run_step_id: str | None = None,
    level: str = "info",
) -> None:
    """Publish ``{"event": ..., "data": ...}`` to Redis AND persist to ``run_step_logs``.

    Typed against a structural :class:`_Publisher` so test stubs (a recorder
    that just appends to a list) satisfy the contract without inheriting
    :class:`redis.asyncio.Redis`. When ``factory`` is callable AND the redis
    client supports ``INCR``, an explicit per-run monotonic sequence is
    minted via ``INCR run:<id>:logseq`` and the payload is appended to
    ``run_step_logs``. Persistence is best-effort: a transient DB / Redis
    failure logs a warning but never blocks the publish hot path (the runs
    UI degrades to the live socket stream).
    """
    payload = json.dumps({"event": event, "data": data})
    if isinstance(redis_client, _Publisher):
        await redis_client.publish(f"run:{run_id}", payload)
    if not callable(factory) or not isinstance(redis_client, _LogseqIncrementer):
        return
    try:
        seq = int(await redis_client.incr(f"run:{run_id}:logseq"))
        async with factory() as session:
            await RunStepLogRepo(session).append(
                run_id=run_id,
                run_step_id=run_step_id,
                level=level,
                message=payload,
                seq=seq,
            )
            await session.commit()
    except Exception as exc:
        log.warning("runner.log.persist_skip", run_id=run_id, reason=str(exc))


async def _try_file_defect(factory: object, run_id: str) -> None:
    """Best-effort defect ingest after a failed run.

    The :class:`DefectService` lives in ``apps/api`` and the runner does not
    hard-depend on it; we late-import and swallow any error (import-time,
    constructor signature drift, missing method) so a defect-pipeline outage
    can never poison a completed run record. M2 will move the service into a
    shared package and let us drop this duck-typing.
    """
    if not callable(factory):
        return
    try:
        from suitest_api.services.defect_service import DefectService

        async with factory() as session:
            # DefectService takes (ctx, repo) today, which the runner doesn't
            # have around. We only call it when both pieces are reachable —
            # for now the missing args path falls through to the warn log.
            if not hasattr(DefectService, "file_for_failed_run"):
                return
            log.info("runner.defect.not_wired", run_id=run_id)
            _ = session
    except Exception as exc:
        log.warning("runner.defect.skip", run_id=run_id, reason=str(exc))
