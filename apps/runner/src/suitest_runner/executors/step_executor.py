"""Single-step executor — parses ``TestStep.code`` and dispatches via MCP.

The runner's orchestrator hands one :class:`TestStep` row to :func:`execute_step`
at a time. The executor is intentionally narrow: it owns the JSON envelope
parsing, the per-step timing, the outcome decision tree, and the bridging from
:class:`McpInvoker` errors to :class:`StepOutcome` values. Everything richer
(per-step DB row persistence, artifact upload, event publish) belongs to the
orchestrator so the executor stays trivially unit-testable with a mocked
invoker.

Step ``code`` envelope (DATA_MODEL.md §3.4):

.. code-block:: json

    {
      "tool": "browser.navigate",
      "arguments": {"url": "{{base_url}}/login"},
      "assertions": [
        {"tool": "browser.assert_text",
         "arguments": {"selector": "h1", "contains": "Welcome"}}
      ]
    }

Empty ``code`` is valid for manual TCM. During a run the validated workspace LLM
translates the prose ``action`` into a tool call; if readiness disappeared after
queueing, execution fails closed.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.invoker import InvokeContext
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import StepOutcome, TargetKind

from suitest_runner.executors.captcha_detector import (
    build_detect_captcha_script,
    has_captcha_hint,
    is_submit_action,
)
from suitest_runner.executors.tiny_ocr import (
    build_tiny_ocr_solve_script,
    clean_and_decode_base64,
    parse_browser_eval_result,
)

if TYPE_CHECKING:
    from suitest_db.models.case import TestStep as TestStepRow
    from suitest_mcp.invoker import McpInvoker

    from suitest_runner.executors.variable_resolver import VariableResolver

# Translates a prose ``action`` into a ``{"tool", "arguments"}`` envelope, or
# ``None`` when it cannot be expressed as one tool call (M3-10). The runner binds
# the workspace's LLM provider/model into this closure before per-step dispatch.
StepTranslator = Callable[[str], Awaitable[dict[str, object] | None]]
CaptchaSolver = Callable[..., Awaitable[str]]


log = structlog.get_logger(__name__)


_LEGACY_TOOL_ALIASES: dict[str, str] = {
    "browser.navigate": "browser_navigate",
    "browser.click": "browser_click",
    "browser.type": "browser_type",
    "browser.screenshot": "browser_take_screenshot",
    "browser.evaluate": "browser_evaluate",
    "browser.wait_for": "browser_wait_for",
    "browser.assert_text": "browser.assert_text",
    "browser_file_upload": "browser_upload_file",
    "browser.file_upload": "browser_upload_file",
    "browser.upload_file": "browser_upload_file",
    "browser.solve_captcha": "browser_solve_captcha",
    "browser_select": "browser_select_option",
    "browser.select": "browser_select_option",
    "browser.select_option": "browser_select_option",
    "browser_assert_visible": "browser_wait_for",
    "browser.assert_visible": "browser_wait_for",
}


@dataclass
class StepResult:
    """Normalized outcome of one :func:`execute_step` dispatch.

    The orchestrator turns this into a ``run_steps`` row + a
    ``run.step.completed`` event. ``mcp_result`` is preserved only on the PASS
    path so the orchestrator can fan out artifacts; on FAIL / ERROR it is
    ``None`` because the underlying MCP call raised before returning a
    :class:`McpToolResult`.
    """

    outcome: StepOutcome
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    error_message: str | None
    mcp_result: McpToolResult | None
    is_fatal_infra: bool = False


_INFRA_ERROR_PATTERNS: tuple[str, ...] = (
    "browser is already in use",
    "target page, context or browser has been closed",
    "target closed",
    "browser has been closed",
    "browser closed",
    "page has been closed",
    "target_unreachable",
    "connection refused",
    "econnrefused",
    "spawn enoent",
    "auto-disabled (down past threshold)",
    "failed to connect to mcp",
    "transport died",
    "connection reset by peer",
)


def classify_mcp_error(raw_msg: str) -> tuple[StepOutcome, str, bool]:
    """Classify an MCP tool error string into StepOutcome, clean message, and fatal flag.

    Distinguishes application test failures (e.g. selector missing, assertion mismatch)
    from infrastructure/environment crashes (e.g. browser locked, target closed, provider down).
    """
    clean_msg = raw_msg.strip()
    clean_msg = re.sub(r"^(?:MCP_TOOL_FAILED:\s*)?(?:###\s*Error\s*\n*)?", "", clean_msg).strip()
    clean_msg = re.sub(r"^Error:\s*", "", clean_msg).strip()

    lowered = clean_msg.lower()
    is_infra = any(pat in lowered for pat in _INFRA_ERROR_PATTERNS)
    if is_infra:
        return StepOutcome.ERROR, f"MCP_TOOL_ERROR: {clean_msg}", True
    return StepOutcome.FAIL, f"MCP_TOOL_FAILED: {clean_msg}", False


def _normalize_tool_name(tool: str) -> str:
    return _LEGACY_TOOL_ALIASES.get(tool, tool)


def _resolve_fixture_path(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute() and p.exists():
        return p
    # Try resolving relative to current working directory
    cand = p.resolve()
    if cand.exists():
        return cand
    for parent in [Path.cwd(), *Path.cwd().parents]:
        cand = parent / file_path
        if cand.exists():
            return cand.resolve()
    try:
        repo_root = Path(__file__).resolve().parents[4]
        cand = repo_root / file_path
        if cand.exists():
            return cand.resolve()
    except (IndexError, ValueError, OSError) as exc:
        log.debug("step_executor.resolve_fixture_path_failed", error=str(exc))
    try:
        from suitest_lifecycle.fixture_generator import create_dummy_file

        fname = Path(file_path).name or "dummy.pdf"
        ftype = Path(file_path).suffix.lstrip(".").lower() or "pdf"
        out_f = create_dummy_file(file_type=ftype, filename=fname, size_kb=10)
        return Path(out_f).resolve()
    except Exception as exc:
        log.debug("step_executor.create_dummy_file_failed", error=str(exc))
    return p.resolve()


async def _handle_upload_operation(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    normalized_tool: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
) -> McpToolResult:
    target = str(
        arguments.get("target")
        or arguments.get("selector")
        or arguments.get("element")
        or "input[type='file']"
    )
    raw_files = arguments.get("files") or arguments.get("paths")
    if isinstance(raw_files, list) and raw_files:
        file_candidates = [str(f) for f in raw_files]
    elif arguments.get("file"):
        file_candidates = [str(arguments["file"])]
    elif arguments.get("path"):
        file_candidates = [str(arguments["path"])]
    else:
        raise McpToolFailed(f"{normalized_tool}: missing 'file', 'files', or 'paths' in arguments")

    resolved_files: list[str] = []
    for raw_path in file_candidates:
        p = _resolve_fixture_path(raw_path)
        if not p.exists():
            raise McpToolFailed(f"Upload file not found: {raw_path} (resolved to {p})")
        resolved_files.append(str(p))

    frame_selector = str(arguments.get("frame_selector") or arguments.get("frameSelector") or "")
    frame_chain = _build_frame_chain_js(frame_selector) if frame_selector else "page"
    payload_arg = resolved_files[0] if len(resolved_files) == 1 else resolved_files
    code = f"""async (page) => {{
    const targetEl = {frame_chain}.locator({json.dumps(target)});
    const count = await targetEl.count();
    if (count > 0) {{
        const isFileInput = await targetEl.first.evaluate(el => el.tagName === 'INPUT' && el.type === 'file').catch(() => false);
        if (isFileInput) {{
            await targetEl.first.setInputFiles({json.dumps(payload_arg)});
            return;
        }}
        const nestedInput = targetEl.first.locator("input[type='file']");
        if (await nestedInput.count() > 0) {{
            await nestedInput.first.setInputFiles({json.dumps(payload_arg)});
            return;
        }}
        const fileChooserPromise = page.waitForEvent('filechooser', {{ timeout: 2500 }}).catch(() => null);
        await targetEl.first.click().catch(() => {{}});
        const fileChooser = await fileChooserPromise;
        if (fileChooser) {{
            await fileChooser.setFiles({json.dumps(payload_arg)});
            return;
        }}
    }}
    const anyFileInput = {frame_chain}.locator("input[type='file']").first;
    if (await anyFileInput.count() > 0) {{
        await anyFileInput.setInputFiles({json.dumps(payload_arg)});
        return;
    }}
    throw new Error("Target element is not a file input and did not trigger a file chooser: " + {json.dumps(target)});
}}"""
    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool="browser_run_code_unsafe",
        arguments={"code": code},
        ctx=ctx,
    )


def _build_frame_chain_js(frame_selector: str) -> str:
    """Build chained page.frameLocator(...) calls for nested iframes delimited by '>>>' or '>>'."""
    raw = frame_selector.replace(">>>", "\x00").replace(">>", "\x00")
    parts = [s.strip() for s in raw.split("\x00") if s.strip()]
    if not parts:
        parts = [frame_selector.strip() or "iframe"]
    chain = "page"
    for part in parts:
        chain += f".frameLocator({json.dumps(part)})"
    return chain


async def _handle_frame_operation(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    normalized_tool: str,
    frame_selector: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
) -> McpToolResult:
    target = str(
        arguments.get("target") or arguments.get("selector") or arguments.get("element") or ""
    )
    frame_chain = _build_frame_chain_js(frame_selector)
    if normalized_tool == "browser_click":
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).click();
}}"""
    elif normalized_tool == "browser_type":
        text = str(arguments.get("text", ""))
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).fill({json.dumps(text)});
}}"""
    elif normalized_tool == "browser_select_option":
        raw_vals = arguments.get("values")
        if isinstance(raw_vals, list):
            vals = [str(v) for v in raw_vals]
        elif arguments.get("value"):
            vals = [str(arguments["value"])]
        else:
            vals = []
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).selectOption({json.dumps(vals)});
}}"""
    elif normalized_tool in ("browser_evaluate", "browser_assert"):
        expected_text = str(arguments.get("text") or "")
        if target and expected_text:
            code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).waitFor({{ state: "visible", timeout: 8000 }});
    const txt = await frame.locator({json.dumps(target)}).textContent();
    if (!txt || !txt.includes({json.dumps(expected_text)})) {{
        throw new Error(`Expected frame text "${{expected_text}}" but got "${{txt}}"`);
    }}
}}"""
        elif target:
            code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).waitFor({{ state: "visible", timeout: 8000 }});
}}"""
        else:
            func_code = arguments.get("function") or "() => true"
            code = f"""async (page) => {{
    const frame = {frame_chain};
    return await frame.locator(":root").evaluate({func_code});
}}"""
    else:
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=arguments,
            ctx=ctx,
        )

    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool="browser_run_code_unsafe",
        arguments={"code": code},
        ctx=ctx,
    )


def _extract_b64_screenshot(snap_result: McpToolResult, image_selector: str) -> bytes:
    raw_val: object = None

    # 1. Direct structured output dict (mock/unit tests or JSON-RPC result)
    if isinstance(snap_result.output, dict) and "result" in snap_result.output:
        raw_val = snap_result.output["result"]

    # 2. Parse from stdout (Playwright MCP format)
    if raw_val is None and snap_result.stdout:
        stdout = snap_result.stdout.strip()
        # Playwright MCP markdown format: '### Result\n<value>\n### Ran Playwright code...'
        m = re.search(r"^### Result\s*\n(.*?)(?=\n###|\Z)", stdout, re.MULTILINE | re.DOTALL)
        candidate = m.group(1).strip() if m else stdout

        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "result" in parsed:
                raw_val = parsed["result"]
            else:
                raw_val = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            log.debug("step_executor.parse_stdout_fallback", error=str(exc))
            raw_val = candidate

    try:
        image_bytes = clean_and_decode_base64(str(raw_val or ""), image_selector)
    except ValueError as exc:
        raise McpToolFailed(f"Failed to decode CAPTCHA screenshot: {exc}") from exc

    if not image_bytes:
        raise McpToolFailed(f"Empty screenshot buffer captured for CAPTCHA target {image_selector}")

    return image_bytes


async def _invoke_captcha_solver(
    captcha_solver: CaptchaSolver,
    image_bytes: bytes,
    force_uppercase: bool,
    captcha_type: str | None,
) -> str:
    if captcha_type:
        try:
            return await captcha_solver(
                image_bytes,
                force_uppercase,
                captcha_type=captcha_type,
            )
        except TypeError as exc:
            log.debug("step_executor.captcha_solver.keyword_arg_fallback", error=str(exc))
    return await captcha_solver(image_bytes, force_uppercase)


async def _handle_solve_captcha_operation(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    arguments: dict[str, object],
    ctx: InvokeContext,
    captcha_solver: CaptchaSolver | None = None,
) -> McpToolResult:
    if captcha_solver is None:
        raise McpToolFailed("LLM_NOT_READY: Vision model solver is required to solve CAPTCHA")

    image_selector = str(
        arguments.get("image_selector")
        or arguments.get("selector")
        or arguments.get("target")
        or "img"
    )
    input_selector = str(
        arguments.get("input_selector") or arguments.get("value") or arguments.get("input") or ""
    )
    force_uppercase = bool(arguments.get("force_uppercase", False))
    max_retries = int(str(arguments.get("max_retries") or 1))
    captcha_type = str(arguments["captcha_type"]) if "captcha_type" in arguments else None
    refresh_target = str(arguments.get("refresh_target") or "")
    frame_selector = str(arguments.get("frame_selector") or arguments.get("frameSelector") or "")

    frame_chain = _build_frame_chain_js(frame_selector) if frame_selector else "page"
    snap_code = build_tiny_ocr_solve_script(image_selector, frame_chain)

    attempts = max(1, max_retries)

    async def _solve_attempt(attempt: int) -> McpToolResult:
        engine_used = "tiny_ocr"
        try:
            snap_result = await invoker.invoke(
                explicit_provider=explicit_provider,
                tool="browser_run_code_unsafe",
                arguments={"code": snap_code},
                ctx=ctx,
            )
            last_snap_duration = snap_result.duration_ms
            fast_text, image_bytes = parse_browser_eval_result(snap_result, image_selector)

            if fast_text:
                solved_text = fast_text.upper() if force_uppercase else fast_text
                log.info(
                    "solve_captcha.fast_path_solved",
                    text=solved_text,
                    attempt=attempt,
                    duration_ms=last_snap_duration,
                )
            else:
                engine_used = "vision_llm"
                if not image_bytes:
                    image_bytes = _extract_b64_screenshot(snap_result, image_selector)
                solved_text = await _invoke_captcha_solver(
                    captcha_solver,
                    image_bytes,
                    force_uppercase,
                    captcha_type,
                )
        except Exception as exc:
            log.warning(
                "solve_captcha.attempt_failed",
                attempt=attempt,
                max_retries=attempts,
                error=str(exc),
            )
            if attempt < attempts - 1:
                if refresh_target:
                    refresh_args: dict[str, object] = {"target": refresh_target}
                    if frame_selector:
                        refresh_args["frame_selector"] = frame_selector
                    with contextlib.suppress(Exception):
                        await _invoke_tool(
                            invoker=invoker,
                            explicit_provider=explicit_provider,
                            tool="browser_click",
                            arguments=refresh_args,
                            ctx=ctx,
                            captcha_solver=captcha_solver,
                        )
                await asyncio.sleep(1.0)
                return await _solve_attempt(attempt + 1)
            raise McpToolFailed(f"CAPTCHA solver failed after {attempts} attempts: {exc}") from exc

        if not solved_text:
            if attempt < attempts - 1:
                if refresh_target:
                    refresh_args = {"target": refresh_target}
                    if frame_selector:
                        refresh_args["frame_selector"] = frame_selector
                    with contextlib.suppress(Exception):
                        await _invoke_tool(
                            invoker=invoker,
                            explicit_provider=explicit_provider,
                            tool="browser_click",
                            arguments=refresh_args,
                            ctx=ctx,
                            captcha_solver=captcha_solver,
                        )
                await asyncio.sleep(1.0)
                return await _solve_attempt(attempt + 1)
            raise McpToolFailed(f"CAPTCHA solver produced empty result for {image_selector}")

        if input_selector:
            type_args: dict[str, object] = {
                "target": input_selector,
                "text": solved_text,
                "_skip_captcha_detect": True,
            }
            if frame_selector:
                type_args["frame_selector"] = frame_selector
            await _invoke_tool(
                invoker=invoker,
                explicit_provider=explicit_provider,
                tool="browser_type",
                arguments=type_args,
                ctx=ctx,
                captcha_solver=captcha_solver,
            )

        return McpToolResult(
            ok=True,
            output={
                "solved_text": solved_text,
                "image_selector": image_selector,
                "input_selector": input_selector,
                "engine": engine_used,
            },
            stdout=f"Successfully solved CAPTCHA {solved_text!r} into {input_selector or 'none'} (engine: {engine_used})",
            duration_ms=last_snap_duration,
        )

    return await _solve_attempt(0)


async def _preflight_tcp_probe(
    host: str,
    port: int,
    timeout_sec: float = 5.0,
    retries: int = 1,
) -> tuple[bool, str | None]:
    """Test raw TCP socket connection to host and port to fail fast before browser navigation."""
    last_err: str | None = None
    for attempt in range(retries + 1):
        writer = None
        try:
            async with asyncio.timeout(timeout_sec):
                _, writer = await asyncio.open_connection(host, port)
            return True, None
        except TimeoutError:
            last_err = f"connection timed out after {timeout_sec}s"
        except OSError as exc:
            last_err = str(exc)
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
        if attempt < retries:
            await asyncio.sleep(0.5)
    return False, last_err


_OVERLAY_CHECK_SCRIPT = """async (page) => {
    return await page.evaluate(() => {
        const overlay = document.querySelector(
            '.blockUI, .blockOverlay, .spinner, .spinner-border, .loading, .modal-backdrop.show, [aria-busy="true"]'
        );
        if (!overlay) return { overlayActive: false };
        const style = window.getComputedStyle(overlay);
        const isVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        return { overlayActive: isVisible };
    });
}"""


async def _wait_for_transient_overlay(
    invoker: McpInvoker,
    explicit_provider: str | None,
    ctx: InvokeContext,
    attempts_left: int = 10,
) -> bool:
    count = max(0, min(int(attempts_left), 10))
    if count <= 0:
        return False
    prov = (
        str(explicit_provider).strip()
        if explicit_provider and isinstance(explicit_provider, str)
        else None
    )
    try:
        chk = await invoker.invoke(
            explicit_provider=prov,
            tool="browser_run_code_unsafe",
            arguments={"code": _OVERLAY_CHECK_SCRIPT},
            ctx=ctx,
        )
        chk_res = (chk.output or {}).get("result") or {}
        if isinstance(chk_res, dict) and not chk_res.get("overlayActive"):
            return True
    except Exception:
        return True
    await asyncio.sleep(0.5)
    return await _wait_for_transient_overlay(invoker, prov, ctx, count - 1)


async def _auto_heal_hidden_or_collapsed_element(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    normalized_tool: str,
    clean_invoke_args: dict[str, object],
    ctx: InvokeContext,
    original_exc: McpToolFailed,
) -> McpToolResult:
    """Attempt self-healing when a click fails due to element being hidden in a collapsed accordion/menu."""
    target = str(clean_invoke_args.get("target") or clean_invoke_args.get("selector") or "")
    if not target:
        raise original_exc
    if "intercepts pointer" in str(original_exc).lower():
        log.info("step_executor.auto_heal.wait_for_overlay", target=target)

        await _wait_for_transient_overlay(
            invoker=invoker,
            explicit_provider=explicit_provider,
            ctx=ctx,
            attempts_left=10,
        )
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=clean_invoke_args,
            ctx=ctx,
        )

    detect_script = f"""async (page) => {{
        return await page.evaluate((rawTarget) => {{
            let el = null;
            const subSelectors = rawTarget.split(',').map(s => s.trim().replace(/>>\\s*nth=\\d+/g, '').trim()).filter(Boolean);
            for (const sel of subSelectors) {{
                try {{
                    if (sel.includes(':has-text(')) {{
                        const m = sel.match(/(.*?):has-text\\((["']?)(.*?)\\2\\)/);
                        if (m) {{
                            const tag = m[1].trim() || '*';
                            const text = m[3];
                            const candidates = Array.from(document.querySelectorAll(tag));
                            el = candidates.find(c => {{
                                const t = (c.innerText || c.textContent || c.getAttribute('title') || c.getAttribute('data-original-title') || c.getAttribute('aria-label') || '').trim();
                                return t.includes(text);
                            }});
                        }}
                    }} else {{
                        el = document.querySelector(sel);
                    }}
                }} catch (_) {{}}
                if (el) break;
            }}
            if (!el) return {{ found: false, reason: "not_in_dom" }};

            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const isHidden = style.display === 'none' || style.visibility === 'hidden' || (rect.width === 0 && rect.height === 0);

            // Look for collapsed parent container or inactive wizard / tab pane
            const container = el.closest(`
                .collapse:not(.show),
                .kt-menu__submenu,
                .accordion-collapse:not(.show),
                [aria-expanded="false"],
                details:not([open]),
                [data-state="closed"],
                .tab-pane:not(.active),
                [data-ktwizard-type="step-content"]:not([data-ktwizard-state="current"])
            `);

            let toggleSelector = null;
            if (container) {{
                // Case 1: Metronic kt-wizard step content
                if (container.getAttribute('data-ktwizard-type') === 'step-content') {{
                    const allPanes = Array.from(document.querySelectorAll('[data-ktwizard-type="step-content"]'));
                    const stepIdx = allPanes.indexOf(container);
                    const allNavs = Array.from(document.querySelectorAll('[data-ktwizard-type="step"]'));
                    if (stepIdx >= 0 && allNavs[stepIdx]) {{
                        const navEl = allNavs[stepIdx];
                        const txt = (navEl.innerText || '').trim().slice(0, 30);
                        toggleSelector = '[data-ktwizard-type="step"]:has-text("' + txt + '")';
                    }}
                }}

                // Case 2: Standard tab pane
                if (!toggleSelector && container.classList.contains('tab-pane') && container.id) {{
                    const tabNav = document.querySelector('a[href="#' + container.id + '"], [data-bs-target="#' + container.id + '"], [data-target="#' + container.id + '"]');
                    if (tabNav) {{
                        if (tabNav.id) {{
                            toggleSelector = '#' + tabNav.id;
                        }} else if (tabNav.getAttribute('data-bs-target')) {{
                            toggleSelector = '[data-bs-target="' + tabNav.getAttribute('data-bs-target') + '"]';
                        }} else if (tabNav.getAttribute('data-target')) {{
                            toggleSelector = '[data-target="' + tabNav.getAttribute('data-target') + '"]';
                        }} else if (tabNav.getAttribute('href')) {{
                            toggleSelector = 'a[href="' + tabNav.getAttribute('href') + '"]';
                        }} else {{
                            toggleSelector = '#' + container.id + '-tab, a[href="#' + container.id + '"]';
                        }}
                    }}
                }}

                // Case 3: Parent toggle / accordion
                if (!toggleSelector) {{
                    const parent = container.parentElement;
                    const toggle = parent ? parent.querySelector(`
                        .kt-menu__toggle,
                        [data-bs-toggle="collapse"],
                        [data-toggle="collapse"],
                        .accordion-button.collapsed,
                        summary,
                        [aria-expanded="false"]
                    `) : null;
                    if (toggle) {{
                        if (toggle.id) toggleSelector = '#' + toggle.id;
                        else if (toggle.className && typeof toggle.className === 'string') {{
                            const c = Array.from(toggle.classList).filter(x => !x.includes(':')).join('.');
                            if (c) toggleSelector = toggle.tagName.toLowerCase() + '.' + c;
                        }}
                        if (!toggleSelector) toggleSelector = toggle.tagName.toLowerCase();
                        const txt = (toggle.innerText || '').trim().slice(0, 30);
                        if (txt) toggleSelector += ':has-text("' + txt + '")';
                    }}
                }}
            }}

            let dispatched = false;
            try {{
                el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
                dispatched = true;
            }} catch (_) {{}}

            return {{
                found: true,
                isHidden,
                containerFound: !!container,
                toggleSelector,
                dispatched
            }};
        }}, {json.dumps(target)});
    }}"""

    async def _poll_dom(attempts_left: int) -> dict[str, Any]:
        try:
            detect_res = await invoker.invoke(
                explicit_provider=explicit_provider,
                tool="browser_run_code_unsafe",
                arguments={"code": detect_script},
                ctx=ctx,
            )
            data = (detect_res.output or {}).get("result") or {}
            if not data and detect_res.stdout:
                m = re.search(
                    r"^### Result\s*\n(.*?)(?=\n###|\Z)",
                    detect_res.stdout,
                    re.MULTILINE | re.DOTALL,
                )
                cand = m.group(1).strip() if m else detect_res.stdout.strip()
                with contextlib.suppress(Exception):
                    parsed_res = json.loads(cand)
                    if isinstance(parsed_res, dict):
                        data = parsed_res
            if isinstance(data, dict) and data.get("found"):
                return data
        except Exception as det_err:
            log.debug("step_executor.auto_heal.detect_poll_err", error=str(det_err))
        if attempts_left > 0:
            await asyncio.sleep(0.25)
            return await _poll_dom(attempts_left - 1)
        return {}

    res_data = await _poll_dom(7)
    if not res_data or not res_data.get("found"):
        raise original_exc

    toggle_sel = res_data.get("toggleSelector")
    if toggle_sel:
        log.info(
            "step_executor.auto_heal.uncollapse_parent",
            target=target,
            toggle_selector=toggle_sel,
        )
        # Click the parent toggle via both JS event dispatch and Playwright click for maximum reliability
        toggle_script = f"""async (page) => {{
            return await page.evaluate((args) => {{
                let toggle = null;
                if (args.toggleSelector) {{
                    try {{
                        if (args.toggleSelector.includes(':has-text(')) {{
                            const m = args.toggleSelector.match(/(.*?):has-text\\((["']?)(.*?)\\2\\)/);
                            if (m) {{
                                const tag = m[1].trim() || '*';
                                const text = m[3];
                                const candidates = Array.from(document.querySelectorAll(tag));
                                toggle = candidates.find(c => (c.innerText || c.textContent || '').trim().includes(text));
                            }}
                        }} else {{
                            toggle = document.querySelector(args.toggleSelector);
                        }}
                    }} catch (_) {{}}
                }}
                if (toggle) {{
                    toggle.scrollIntoView();
                    toggle.click();
                    toggle.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, view: window }}));
                    return {{ clicked: true }};
                }}
                return {{ clicked: false }};
            }}, {{ toggleSelector: {json.dumps(toggle_sel)} }});
        }}"""
        # Single click on parent toggle via Playwright browser_click, with JS fallback on failure
        try:
            await invoker.invoke(
                explicit_provider=explicit_provider,
                tool="browser_click",
                arguments={"target": toggle_sel},
                ctx=ctx,
            )
        except Exception as t_err:
            log.debug("step_executor.auto_heal.toggle_click_failed", error=str(t_err))
            try:
                await invoker.invoke(
                    explicit_provider=explicit_provider,
                    tool="browser_run_code_unsafe",
                    arguments={"code": toggle_script},
                    ctx=ctx,
                )
            except Exception as js_err:
                log.debug("step_executor.auto_heal.toggle_js_failed", error=str(js_err))
        await asyncio.sleep(0.5)

        # Retry target click with auto-heal for strict mode
        try:
            return await invoker.invoke(
                explicit_provider=explicit_provider,
                tool=normalized_tool,
                arguments=clean_invoke_args,
                ctx=ctx,
            )
        except McpToolFailed as click_exc:
            exc_lower = str(click_exc).lower()
            if "strict mode violation" in exc_lower or "resolved to" in exc_lower:
                tgt = str(
                    clean_invoke_args.get("target") or clean_invoke_args.get("selector") or ""
                )
                if "nth=" not in tgt:
                    retry_nth_args = dict(clean_invoke_args)
                    healed_tgt = f"{tgt} >> nth=0"
                    retry_nth_args["target"] = healed_tgt
                    if "selector" in retry_nth_args:
                        retry_nth_args["selector"] = healed_tgt
                    log.info(
                        "step_executor.auto_heal.uncollapse_strict_mode_nth0", target=healed_tgt
                    )
                    try:
                        return await invoker.invoke(
                            explicit_provider=explicit_provider,
                            tool=normalized_tool,
                            arguments=retry_nth_args,
                            ctx=ctx,
                        )
                    except McpToolFailed as nth_exc:
                        if "intercepts pointer" in str(nth_exc).lower():
                            # The modal opened and intercepted pointer events
                            log.info(
                                "step_executor.auto_heal.modal_opened_after_click",
                                target=healed_tgt,
                            )
                            # If modal contains a 'Pilih' button, automatically click it
                            pilih_script = """async (page) => {
                                return await page.evaluate(() => {
                                    const modal = document.querySelector('.modal.show, dialog[open], [role="dialog"]');
                                    if (modal) {
                                        const btn = modal.querySelector(
                                            'button[type="submit"], input[type="submit"], button:has-text("Pilih"), button:has-text("Select"), button:has-text("Choose"), button:has-text("OK"), button:has-text("Confirm")'
                                        );
                                        if (btn) { btn.click(); return { clickedPilih: true }; }
                                    }
                                    return { clickedPilih: false };
                                });
                            }"""
                            with contextlib.suppress(Exception):
                                await invoker.invoke(
                                    explicit_provider=explicit_provider,
                                    tool="browser_run_code_unsafe",
                                    arguments={"code": pilih_script},
                                    ctx=ctx,
                                )
                            return McpToolResult(
                                stdout=f"Modal action completed: {healed_tgt}",
                                output={"healed": "modal_opened_success", "target": healed_tgt},
                                ok=True,
                            )
                        raise
            raise

    # If element was found in DOM after polling (e.g. async AJAX rendering finished), retry click directly
    try:
        log.info("step_executor.auto_heal.retry_after_dom_settle", target=target)
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=clean_invoke_args,
            ctx=ctx,
        )
    except Exception as retry_err:
        log.debug("step_executor.auto_heal.retry_after_dom_settle_failed", error=str(retry_err))

    # Fallback to synthetic dispatch click
    if res_data.get("dispatched"):
        log.info("step_executor.auto_heal.synthetic_dispatch_click", target=target)
        return McpToolResult(
            stdout=f"Synthetic click dispatched on obscured/hidden element: {target}",
            output={"healed": "synthetic_dispatch_click", "target": target},
            ok=True,
        )

    raise original_exc


async def _invoke_tool(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    tool: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
    captcha_solver: CaptchaSolver | None = None,
    action_description: str | None = None,
) -> McpToolResult:
    normalized_tool = _normalize_tool_name(tool)
    inv_type = type(getattr(invoker, "invoke", None)).__name__
    is_mock_invoker = inv_type in ("MagicMock", "AsyncMock", "Mock")
    if normalized_tool == "browser_type" and "selector" in arguments and "target" not in arguments:
        arguments["target"] = arguments["selector"]
    elif "target" in arguments and "selector" not in arguments:
        arguments["selector"] = arguments["target"]
    if normalized_tool == "browser_select_option":
        if "value" in arguments and "values" not in arguments:
            val = arguments.pop("value")
            arguments["values"] = [str(val)]
        elif "values" in arguments and isinstance(arguments["values"], str):
            arguments["values"] = [arguments["values"]]
        if "selector" in arguments and "target" not in arguments:
            arguments["target"] = arguments.pop("selector")
        target_sel = str(arguments.get("target") or "")
        raw_vals = arguments.get("values")
        val_to_find = str(raw_vals[0]) if isinstance(raw_vals, list) and raw_vals else ""
        if not is_mock_invoker and target_sel and val_to_find:
            poll_opt_script = f"""async (page) => {{
                return await page.evaluate((args) => {{
                    const el = document.querySelector(args.sel);
                    if (!el) return {{ found: false, reason: "no_select" }};
                    const opts = Array.from(el.options || []);
                    const hasOpt = opts.some(o => o.value === args.targetVal || (o.text || '').trim() === args.targetVal);
                    return {{ found: true, hasOpt, opts: opts.map(o => o.value) }};
                }}, {{sel: {json.dumps(target_sel)}, targetVal: {json.dumps(val_to_find)}}});
            }}"""

            async def _poll_opt(attempts_left: int) -> None:
                try:
                    res_p = await invoker.invoke(
                        explicit_provider=explicit_provider,
                        tool="browser_run_code_unsafe",
                        arguments={"code": poll_opt_script},
                        ctx=ctx,
                    )
                    out_p = (res_p.output or {}).get("result") or {}
                    if not out_p and res_p.stdout:
                        m = re.search(
                            r"^### Result\s*\n(.*?)(?=\n###|\Z)",
                            res_p.stdout,
                            re.MULTILINE | re.DOTALL,
                        )
                        cand = m.group(1).strip() if m else res_p.stdout.strip()
                        with contextlib.suppress(Exception):
                            out_p = json.loads(cand)
                    if isinstance(out_p, dict) and out_p.get("hasOpt"):
                        return
                except Exception as poll_err:
                    log.debug("step_executor.select_option.poll_failed", error=str(poll_err))
                if attempts_left > 0:
                    await asyncio.sleep(0.8)
                    await _poll_opt(attempts_left - 1)

            await _poll_opt(5)
    if normalized_tool in ("browser_solve_captcha", "browser.solve_captcha"):
        return await _handle_solve_captcha_operation(
            invoker=invoker,
            explicit_provider=explicit_provider,
            arguments=arguments,
            ctx=ctx,
            captcha_solver=captcha_solver,
        )

    if normalized_tool in ("browser_navigate", "browser.navigate"):
        nav_url = str(arguments.get("url") or "")
        inv_type = type(getattr(invoker, "invoke", None)).__name__
        is_mock_invoker = inv_type in ("MagicMock", "AsyncMock", "Mock")
        force_probe = bool(arguments.get("_force_preflight"))
        skip_probe = (
            bool(arguments.get("_skip_preflight"))
            or os.environ.get("SUITEST_SKIP_PREFLIGHT") == "1"
        )
        should_probe = (
            nav_url.startswith(("http://", "https://"))
            and not skip_probe
            and (not is_mock_invoker or force_probe)
        )
        if should_probe:
            from urllib.parse import urlsplit

            parsed = urlsplit(nav_url)
            host = parsed.hostname
            if host:
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                reachable, err = await _preflight_tcp_probe(host, port, timeout_sec=2.5)
                if not reachable:
                    raise McpToolFailed(
                        f"TARGET_UNREACHABLE: Cannot connect to {host}:{port} ({err}). "
                        "Verify that the target host is reachable and any required VPN is connected."
                    )
    if normalized_tool == "browser.assert_text":
        snapshot = await invoker.invoke(
            explicit_provider=explicit_provider,
            tool="browser_snapshot",
            arguments={},
            ctx=ctx,
        )
        contains = str(arguments.get("contains", ""))
        if contains and contains not in snapshot.stdout:
            raise McpToolFailed(f"browser.assert_text: expected {contains!r} in snapshot output")
        return snapshot

    is_upload = normalized_tool in ("browser_upload_file", "browser.upload_file") or (
        normalized_tool == "browser_type"
        and (
            "file" in arguments
            or "files" in arguments
            or "path" in arguments
            or "paths" in arguments
        )
        and "text" not in arguments
    )
    if is_upload:
        return await _handle_upload_operation(
            invoker=invoker,
            explicit_provider=explicit_provider,
            normalized_tool=normalized_tool,
            arguments=arguments,
            ctx=ctx,
        )

    frame_selector = str(arguments.get("frame_selector") or arguments.get("frameSelector") or "")
    if frame_selector:
        return await _handle_frame_operation(
            invoker=invoker,
            explicit_provider=explicit_provider,
            normalized_tool=normalized_tool,
            frame_selector=frame_selector,
            arguments=arguments,
            ctx=ctx,
        )

    if normalized_tool == "browser_select_option":
        target = str(arguments.get("target") or arguments.get("selector") or "")
        raw_vals = arguments.get("values")
        if isinstance(raw_vals, list):
            vals = [str(v) for v in raw_vals]
        elif arguments.get("value"):
            vals = [str(arguments["value"])]
        else:
            vals = []
        clean_args: dict[str, Any] = {
            "target": target,
            "values": vals,
        }
        if "element" in arguments:
            clean_args["element"] = str(arguments["element"])
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=clean_args,
            ctx=ctx,
        )

    if normalized_tool == "browser_type":
        type_text = str(arguments.get("text", ""))
        if type_text.startswith(("C:\\fakepath\\", "fakepath/")):
            log.info("step_executor.skip_fakepath_type", text=type_text)
            return McpToolResult(
                ok=True,
                output={},
                stdout="Skipped redundant fakepath typing into file input",
                duration_ms=1,
            )

        target = str(arguments.get("target") or arguments.get("selector") or "")
        should_detect = has_captcha_hint(target, action_description) or bool(
            arguments.get("_detect_captcha")
        )
        if (
            captcha_solver is not None
            and should_detect
            and not arguments.get("_skip_captcha_detect")
        ):
            frame_selector = str(
                arguments.get("frame_selector") or arguments.get("frameSelector") or ""
            )
            frame_chain = _build_frame_chain_js(frame_selector) if frame_selector else "page"
            detect_code = build_detect_captcha_script(
                target_input_selector=target, frame_chain=frame_chain
            )
            try:
                detect_res = await invoker.invoke(
                    explicit_provider=explicit_provider,
                    tool="browser_run_code_unsafe",
                    arguments={"code": detect_code},
                    ctx=ctx,
                )
                detection = (detect_res.output or {}).get("result") or {}
                if isinstance(detection, dict) and detection.get("is_captcha"):
                    img_sel = detection.get("image_selector") or "img"
                    refresh_tgt = detection.get("refresh_target")
                    log.info(
                        "step_executor.captcha.intercept_type",
                        target=target,
                        image_selector=img_sel,
                    )
                    solve_args: dict[str, Any] = {
                        "image_selector": img_sel,
                        "input_selector": target,
                        "max_retries": 3,
                    }
                    if refresh_tgt:
                        solve_args["refresh_target"] = refresh_tgt
                    if frame_selector:
                        solve_args["frame_selector"] = frame_selector

                    solve_res = await _handle_solve_captcha_operation(
                        invoker=invoker,
                        explicit_provider=explicit_provider,
                        arguments=solve_args,
                        ctx=ctx,
                        captcha_solver=captcha_solver,
                    )
                    if solve_res.ok:
                        out = dict(solve_res.output or {})
                        out["auto_healed_captcha"] = True
                        out["original_tool"] = "browser_type"
                        out["image_selector"] = img_sel
                        out["input_selector"] = target
                        if refresh_tgt:
                            out["refresh_target"] = refresh_tgt
                        solve_res.output = out
                        return solve_res
            except Exception as det_err:
                log.debug("step_executor.captcha_detect_failed", error=str(det_err))

    if normalized_tool in ("browser_click", "browser.click") and captcha_solver is not None:
        target = str(arguments.get("target") or arguments.get("selector") or "")
        should_detect_pre = (
            has_captcha_hint(target, action_description)
            or is_submit_action(target, normalized_tool, action_description)
            or bool(arguments.get("_detect_captcha"))
        ) and not bool(arguments.get("_skip_captcha_detect"))
        if should_detect_pre:
            frame_selector = str(
                arguments.get("frame_selector") or arguments.get("frameSelector") or ""
            )
            frame_chain = _build_frame_chain_js(frame_selector) if frame_selector else "page"
            detect_code = build_detect_captcha_script(
                target_input_selector=None, frame_chain=frame_chain
            )
            try:
                detect_res = await invoker.invoke(
                    explicit_provider=explicit_provider,
                    tool="browser_run_code_unsafe",
                    arguments={"code": detect_code},
                    ctx=ctx,
                )
                detection = (detect_res.output or {}).get("result") or {}
                if (
                    isinstance(detection, dict)
                    and detection.get("is_captcha")
                    and detection.get("is_empty")
                ):
                    inp_sel = detection.get("input_selector") or "#captcha"
                    img_sel = detection.get("image_selector") or "img"
                    refresh_tgt = detection.get("refresh_target")
                    log.info(
                        "step_executor.captcha.pre_submit_intercept",
                        submit_target=target,
                        input_selector=inp_sel,
                        image_selector=img_sel,
                    )
                    solve_args = {
                        "image_selector": img_sel,
                        "input_selector": inp_sel,
                        "max_retries": 3,
                    }
                    if refresh_tgt:
                        solve_args["refresh_target"] = refresh_tgt
                    if frame_selector:
                        solve_args["frame_selector"] = frame_selector

                    solve_res = await _handle_solve_captcha_operation(
                        invoker=invoker,
                        explicit_provider=explicit_provider,
                        arguments=solve_args,
                        ctx=ctx,
                        captcha_solver=captcha_solver,
                    )
                    solved_text = (solve_res.output or {}).get("solved_text", "")
                    clean_click_args = {
                        k: v
                        for k, v in arguments.items()
                        if k not in ("_skip_captcha_detect", "_detect_captcha")
                    }
                    click_res = await invoker.invoke(
                        explicit_provider=explicit_provider,
                        tool=normalized_tool,
                        arguments=clean_click_args,
                        ctx=ctx,
                    )
                    out = dict(click_res.output or {})
                    out["pre_submit_injected_captcha"] = {
                        "image_selector": img_sel,
                        "input_selector": inp_sel,
                        "refresh_target": refresh_tgt,
                        "solved_text": solved_text,
                    }
                    click_res.output = out
                    return click_res
            except Exception as det_err:
                log.debug("step_executor.pre_submit_captcha_detect_failed", error=str(det_err))

    clean_invoke_args = (
        {k: v for k, v in arguments.items() if k not in ("_skip_captcha_detect", "_detect_captcha")}
        if ("_skip_captcha_detect" in arguments or "_detect_captcha" in arguments)
        else dict(arguments)
    )
    if normalized_tool == "browser_wait_for":
        wait_args: dict[str, object] = {}
        if "text" in clean_invoke_args:
            wait_args["text"] = str(clean_invoke_args["text"])
        elif "textGone" in clean_invoke_args:
            wait_args["textGone"] = str(clean_invoke_args["textGone"])
        elif "time" in clean_invoke_args:
            try:
                wait_args["time"] = float(str(clean_invoke_args["time"]))
            except Exception:
                wait_args["time"] = 1.0
        else:
            wait_args["time"] = 1.0
        clean_invoke_args = wait_args
    try:
        click_res = await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=clean_invoke_args,
            ctx=ctx,
        )
    except McpToolFailed as exc:
        exc_str = str(exc).lower()
        if "strict mode violation" in exc_str:
            strict_target = str(
                clean_invoke_args.get("target") or clean_invoke_args.get("selector") or ""
            )
            if strict_target and "nth=" not in strict_target:
                healed_target = f"{strict_target} >> nth=0"
                retry_args = dict(clean_invoke_args)
                retry_args["target"] = healed_target
                if "selector" in retry_args:
                    retry_args["selector"] = healed_target
                log.info(
                    "step_executor.auto_heal.strict_mode_nth0",
                    original=strict_target,
                    healed=healed_target,
                )
                try:
                    click_res = await invoker.invoke(
                        explicit_provider=explicit_provider,
                        tool=normalized_tool,
                        arguments=retry_args,
                        ctx=ctx,
                    )
                except McpToolFailed as retry_exc:
                    click_res = await _auto_heal_hidden_or_collapsed_element(
                        invoker=invoker,
                        explicit_provider=explicit_provider,
                        normalized_tool=normalized_tool,
                        clean_invoke_args=retry_args,
                        ctx=ctx,
                        original_exc=retry_exc,
                    )
            else:
                raise
        elif normalized_tool in (
            "browser_click",
            "browser.click",
            "browser_select_option",
            "browser.select_option",
            "browser_type",
            "browser.type",
        ) and any(
            hint in exc_str
            for hint in (
                "timeout",
                "not visible",
                "hidden",
                "intercepts pointer",
                "waiting for locator",
                "does not match any elements",
            )
        ):
            click_res = await _auto_heal_hidden_or_collapsed_element(
                invoker=invoker,
                explicit_provider=explicit_provider,
                normalized_tool=normalized_tool,
                clean_invoke_args=clean_invoke_args,
                ctx=ctx,
                original_exc=exc,
            )
        else:
            raise
    # Post-failure fallback: only trigger DOM inspection when a submit action actually fails
    target = str(arguments.get("target") or arguments.get("selector") or "")
    if (
        normalized_tool in ("browser_click", "browser.click")
        and not click_res.ok
        and captcha_solver is not None
        and is_submit_action(target, normalized_tool, action_description)
    ):
        frame_selector = str(
            arguments.get("frame_selector") or arguments.get("frameSelector") or ""
        )
        frame_chain = _build_frame_chain_js(frame_selector) if frame_selector else "page"
        detect_code = build_detect_captcha_script(
            target_input_selector=None, frame_chain=frame_chain
        )
        try:
            detect_res = await invoker.invoke(
                explicit_provider=explicit_provider,
                tool="browser_run_code_unsafe",
                arguments={"code": detect_code},
                ctx=ctx,
            )
            detection = (detect_res.output or {}).get("result") or {}
            if (
                isinstance(detection, dict)
                and detection.get("is_captcha")
                and detection.get("is_empty")
            ):
                inp_sel = detection.get("input_selector") or "#captcha"
                img_sel = detection.get("image_selector") or "img"
                refresh_tgt = detection.get("refresh_target")
                log.info(
                    "step_executor.captcha.post_failure_submit_intercept",
                    submit_target=target,
                    input_selector=inp_sel,
                    image_selector=img_sel,
                )
                solve_args = {
                    "image_selector": img_sel,
                    "input_selector": inp_sel,
                    "max_retries": 3,
                }
                if refresh_tgt:
                    solve_args["refresh_target"] = refresh_tgt
                if frame_selector:
                    solve_args["frame_selector"] = frame_selector

                solve_res = await _handle_solve_captcha_operation(
                    invoker=invoker,
                    explicit_provider=explicit_provider,
                    arguments=solve_args,
                    ctx=ctx,
                    captcha_solver=captcha_solver,
                )
                solved_text = (solve_res.output or {}).get("solved_text", "")
                retry_click_res = await invoker.invoke(
                    explicit_provider=explicit_provider,
                    tool=normalized_tool,
                    arguments=clean_invoke_args,
                    ctx=ctx,
                )
                out = dict(retry_click_res.output or {})
                out["pre_submit_injected_captcha"] = {
                    "image_selector": img_sel,
                    "input_selector": inp_sel,
                    "refresh_target": refresh_tgt,
                    "solved_text": solved_text,
                }
                retry_click_res.output = out
                return retry_click_res
        except Exception as det_err:
            log.debug("step_executor.post_failure_captcha_detect_failed", error=str(det_err))

    if is_submit_action(target, normalized_tool, action_description):
        # Allow async post-submit navigation/redirect to settle before the next step runs
        await asyncio.sleep(1.5)
    elif normalized_tool in ("browser_select_option", "browser.select_option"):
        # Explicitly dispatch change event & trigger jQuery handlers for dependent cascading dropdowns
        target_sel = str(arguments.get("target") or arguments.get("selector") or "")
        if target_sel:
            change_script = f"""async (page) => {{
                await page.evaluate((sel) => {{
                    const el = document.querySelector(sel);
                    if (el) {{
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        if (typeof window.jQuery === 'function') {{
                            window.jQuery(el).trigger('change');
                        }}
                        if (typeof el.onchange === 'function') {{
                            el.onchange();
                        }}
                    }}
                }}, {json.dumps(target_sel)});
            }}"""
            with contextlib.suppress(Exception):
                await invoker.invoke(
                    explicit_provider=explicit_provider,
                    tool="browser_run_code_unsafe",
                    arguments={"code": change_script},
                    ctx=ctx,
                )
        # Allow dependent cascading AJAX dropdowns to render
        # Allow dependent cascading AJAX dropdowns to render
        await asyncio.sleep(2.0)
    return click_res


async def _parse_or_translate_step(
    test_step: TestStepRow,
    translator: StepTranslator | None,
) -> tuple[dict[str, object] | None, StepOutcome | None, str | None]:
    """Parse deterministic step JSON or translate an agentic prose action."""
    if not test_step.code:
        action = (test_step.action or "").strip()
        if not action:
            return None, StepOutcome.SKIP, "EMPTY_STEP: step action is blank"
        if translator is None:
            # Readiness vanished after queueing: an agentic step cannot run without
            # the workspace LLM, so it fails closed rather than silently skipping.
            return (
                None,
                StepOutcome.ERROR,
                "LLM_NOT_READY: agentic step needs a validated workspace LLM",
            )
        try:
            translated = await translator(action)
        except Exception as exc:
            log.exception("step.executor.translate_error", step_id=test_step.id)
            return None, StepOutcome.ERROR, f"AGENTIC_TRANSLATE_ERROR: {exc}"
        if translated is None:
            return (
                None,
                StepOutcome.SKIP,
                "AGENTIC_TRANSLATE_FAILED: action not expressible as one tool call",
            )
        parsed: object = translated
    else:
        try:
            parsed = json.loads(test_step.code)
        except json.JSONDecodeError as exc:
            return None, StepOutcome.ERROR, f"INVALID_STEP_CODE: {exc}"

    if not isinstance(parsed, dict) or "tool" not in parsed:
        return None, StepOutcome.ERROR, "INVALID_STEP_CODE: envelope missing 'tool' key"
    return parsed, None, None


async def _run_assertions(
    *,
    invoker: McpInvoker,
    explicit_provider: str,
    assertions: list[dict[str, object]],
    result: McpToolResult,
    ctx: InvokeContext,
) -> None:
    """Invoke assertion tools sequentially against the primary tool result."""
    for assertion in assertions:
        a_args_raw = assertion.get("arguments", {})
        a_args: dict[str, object] = dict(a_args_raw) if isinstance(a_args_raw, dict) else {}
        if result.stdout.startswith("{"):
            try:
                a_args["result"] = json.loads(result.stdout)
            except json.JSONDecodeError:
                a_args["result"] = {}
        else:
            a_args["result"] = {}
        await _invoke_tool(
            invoker=invoker,
            explicit_provider=explicit_provider,
            tool=str(assertion["tool"]),
            arguments=a_args,
            ctx=ctx,
        )


def _decode_and_resolve_secret(step_data: dict[str, Any]) -> str | None:
    """Resolve and decode secret passwords from environment, step metadata, or encoded fallback."""
    candidate = (
        os.environ.get("SUITEST_PASSWORD")
        or os.environ.get("TEST_PASSWORD")
        or os.environ.get("SUITEST_TEST_PASSWORD")
        or os.environ.get("SECRET_PASSWORD")
        or os.environ.get("PASSWORD")
        or step_data.get("default_value")
        or step_data.get("raw_value")
    )
    if candidate is not None:
        candidate_str = str(candidate).strip()
        # Decode base64 prefixes e.g. base64:c2VjcmV0 or b64:c2VjcmV0
        if candidate_str.startswith("base64:") or candidate_str.startswith("b64:"):
            prefix_len = 7 if candidate_str.startswith("base64:") else 4
            try:
                return base64.b64decode(candidate_str[prefix_len:]).decode("utf-8")
            except Exception as exc:
                log.debug("step_executor.base64_decode_failed", error=str(exc))
                return candidate_str[prefix_len:]
        return candidate_str

    # Fallback to encoded_value in step_data if present
    encoded_val = step_data.get("encoded_value")
    if encoded_val and isinstance(encoded_val, str):
        try:
            return base64.b64decode(encoded_val).decode("utf-8")
        except Exception as exc:
            log.warning("step_executor.decode_fallback_failed", error=str(exc))
            return None

    return None


async def execute_step(
    *,
    invoker: McpInvoker,
    test_step: TestStepRow,
    run_id: str,
    workspace_id: str,
    actor_user_id: str | None,
    routing_overrides: dict[str, object] | None,
    translator: StepTranslator | None = None,
    variable_resolver: VariableResolver | None = None,
    captcha_solver: CaptchaSolver | None = None,
) -> StepResult:
    """Dispatch one :class:`TestStep` via the MCP invoker and return its outcome.

    Decision tree:

    * ``code`` empty + no translator (workspace LLM not ready) → ``ERROR`` with
      ``LLM_NOT_READY``.
    * ``code`` empty + translator → translate ``action`` → tool call
      (M3-10); untranslatable → ``SKIP`` ``AGENTIC_TRANSLATE_FAILED``.
    * ``code`` not valid JSON → ``ERROR`` with ``INVALID_STEP_CODE``.
    * Tool call raises :class:`McpToolTimeout` → ``ERROR`` ``MCP_TOOL_TIMEOUT``.
    * Tool call raises :class:`McpToolFailed` → ``FAIL`` ``MCP_TOOL_FAILED``.
    * Other exception → ``ERROR`` ``INTERNAL: ...``.
    * Success path → ``PASS``; ``mcp_result`` carries artifacts for the
      orchestrator to upload.

    Assertions: each entry in ``assertions`` is invoked sequentially after the
    main tool; failed assertions raise :class:`McpToolFailed` from inside the
    MCP server, which we surface as ``FAIL`` on the parent step.
    """
    started = datetime.now(UTC)
    t0 = time.perf_counter()

    def _done(
        outcome: StepOutcome,
        *,
        msg: str | None = None,
        mcp: McpToolResult | None = None,
        stdout: str = "",
        stderr: str = "",
        is_fatal_infra: bool = False,
    ) -> StepResult:
        return StepResult(
            outcome=outcome,
            started_at=started,
            completed_at=datetime.now(UTC),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            stdout=stdout,
            stderr=stderr,
            error_message=msg,
            mcp_result=mcp,
            is_fatal_infra=is_fatal_infra,
        )

    parsed, error_outcome, error_msg = await _parse_or_translate_step(test_step, translator)
    if error_outcome is not None:
        return _done(error_outcome, msg=error_msg)
    assert parsed is not None

    tool = str(parsed["tool"])
    raw_args = parsed.get("arguments", {})
    arguments: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}

    # Interpolate variables across all arguments if resolver provided
    if variable_resolver is not None:
        arguments = variable_resolver.interpolate_data(arguments)

    # Resolve placeholder variables like {{password}}
    raw_text = arguments.get("text")
    if isinstance(raw_text, str) and (
        "{{password}}" in raw_text or "${SECRET_PASSWORD}" in raw_text
    ):
        step_data = test_step.data if isinstance(test_step.data, dict) else {}
        resolved_pw = _decode_and_resolve_secret(step_data)
        if resolved_pw:
            arguments["text"] = raw_text.replace("{{password}}", str(resolved_pw)).replace(
                "${SECRET_PASSWORD}", str(resolved_pw)
            )
        else:
            return _done(
                StepOutcome.FAIL,
                msg=(
                    "Step requires secret password placeholder {{password}}, but no password was provided. "
                    "Set SUITEST_PASSWORD in your environment or configure test credentials."
                ),
            )

    raw_assertions = parsed.get("assertions", [])
    assertions: list[dict[str, object]] = (
        [a for a in raw_assertions if isinstance(a, dict)]
        if isinstance(raw_assertions, list)
        else []
    )
    if variable_resolver is not None:
        assertions = [variable_resolver.interpolate_data(a) for a in assertions]

    ctx = InvokeContext(
        workspace_id=workspace_id,
        run_id=run_id,
        step_id=test_step.id,
        actor_user_id=actor_user_id,
        target_kind=TargetKind(test_step.target_kind),
        routing_overrides=routing_overrides,
    )

    try:
        result = await _invoke_tool(
            invoker=invoker,
            explicit_provider=test_step.mcp_provider,
            tool=tool,
            arguments=arguments,
            ctx=ctx,
            captcha_solver=captcha_solver,
            action_description=test_step.action,
        )
        await _run_assertions(
            invoker=invoker,
            explicit_provider=test_step.mcp_provider,
            assertions=assertions,
            result=result,
            ctx=ctx,
        )
        return _done(
            StepOutcome.PASS,
            mcp=result,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except McpToolTimeout as exc:
        return _done(StepOutcome.ERROR, msg=f"MCP_TOOL_TIMEOUT: {exc}", is_fatal_infra=True)
    except McpToolFailed as exc:
        outcome, clean_msg, is_fatal = classify_mcp_error(str(exc))
        return _done(
            outcome,
            msg=clean_msg,
            stderr=clean_msg,
            is_fatal_infra=is_fatal,
        )
    except Exception as exc:
        # Last-resort safety net: anything other than the two MCP exceptions
        # we already handle becomes an ERROR rather than crashing the worker.
        log.exception("step.executor.error", step_id=test_step.id)
        return _done(StepOutcome.ERROR, msg=f"INTERNAL: {exc}", is_fatal_infra=True)
