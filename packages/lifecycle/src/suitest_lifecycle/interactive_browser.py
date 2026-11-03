"""Stateful Interactive Browser Session Manager and MCP Tools (Task 8 / Pilar 4).

Provides step-by-step interactive browser control for LLMs/Agents with:
- Per-session lifecycle (session_id)
- Inactivity TTL Reaper (300 seconds default)
- Concurrency limiter (max 3 active sessions)
- Complete action traceability (recording action_history for TCM export)
- In-browser Tiny OCR CAPTCHA solving
"""

from __future__ import annotations

import base64
import concurrent.futures
import contextlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

try:
    from suitest_shared.ocr import (
        build_tiny_ocr_element_eval_script,
        classify_ocr_output,
    )
except ImportError:
    build_tiny_ocr_element_eval_script = None  # type: ignore[assignment]
    classify_ocr_output = None  # type: ignore[assignment]

from suitest_lifecycle.tool_result import envelope as _envelope

logger = logging.getLogger(__name__)

_SENSITIVE_INPUT_RE = re.compile(
    r"(?:"
    r"type=[\"']password[\"']|"
    r"autocomplete=[\"'](?:current-|new-)?password[\"']|"
    r"password|"
    r"passwd|"
    r"(?<![a-zA-Z])pass(?![a-zA-Z])|"
    r"(?<![a-zA-Z])pwd(?![a-zA-Z])|"
    r"pin|"
    r"cvv|"
    r"secret|"
    r"token|"
    r"api[-_]?key|"
    r"auth[-_]?token"
    r")",
    re.IGNORECASE,
)


def _is_sensitive_input(
    target: str = "",
    extra: dict[str, Any] | None = None,
    value: str = "",
) -> bool:
    """Determine whether an input represents sensitive data (e.g. password/credentials)."""
    if extra and (
        extra.get("is_secret")
        or str(extra.get("input_type") or "").lower() == "password"
        or str(extra.get("type") or "").lower() == "password"
    ):
        return True
    t_lower = (target or "").lower()
    return bool(_SENSITIVE_INPUT_RE.search(t_lower))


@dataclass
class BrowserAction:
    order: int
    action: str
    target: str = ""
    value: str = ""
    timestamp: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "action": self.action,
            "target": self.target,
            "value": self.value,
            "timestamp": self.timestamp,
            **self.extra,
        }


class InteractiveSession:
    """Encapsulates a live, stateful Playwright browser session."""

    def __init__(
        self,
        session_id: str,
        playwright_obj: Any,
        browser: Any,
        context: Any,
        page: Any,
    ) -> None:
        self.session_id = session_id
        self.playwright = playwright_obj
        self.browser = browser
        self.context = context
        self.page = page
        self.created_at = time.time()
        self.last_activity = time.time()
        self.action_history: list[BrowserAction] = []
        self._closed = False

    def touch(self) -> None:
        self.last_activity = time.time()

    def is_expired(self, ttl_seconds: float = 300.0) -> bool:
        return (time.time() - self.last_activity) > ttl_seconds

    def record_action(
        self,
        action: str,
        target: str = "",
        value: str = "",
        **extra: Any,
    ) -> None:
        self.touch()
        order = len(self.action_history) + 1
        self.action_history.append(
            BrowserAction(
                order=order,
                action=action,
                target=target,
                value=value,
                extra=extra,
            )
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self.page.close()
        with contextlib.suppress(Exception):
            self.context.close()
        with contextlib.suppress(Exception):
            self.browser.close()


def _extract_session_target_url(
    session: InteractiveSession | None,
    actions: list[dict[str, Any]],
    default_url: str = "",
) -> str:
    """Extract recorded target URL from active session or navigation history."""
    if default_url:
        return default_url
    if session and getattr(session, "page", None):
        with contextlib.suppress(Exception):
            p_url = str(session.page.url or "")
            if p_url and p_url.startswith(("http://", "https://")):
                return p_url
    for a in actions:
        if a.get("action") == "navigate":
            cand = str(
                a.get("value") or a.get("target") or (a.get("extra") or {}).get("current_url") or ""
            )
            if cand and cand.startswith(("http://", "https://")):
                return cand
    return ""


def _save_session_case_file(
    session_id: str,
    created_at: float,
    actions: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Persist session action trace into disk JSON case file."""
    if not actions:
        return ""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    case_file = str(out_path / f"{session_id}.case.json")
    sanitized_steps = []
    for a in actions:
        val = a.get("value", "")
        if (
            a.get("action") == "type"
            and _is_sensitive_input(a.get("target", ""), extra=a.get("extra"), value=val)
            and not (isinstance(val, str) and val.startswith("{{") and val.endswith("}}"))
        ):
            t_low = str(a.get("target", "")).lower()
            val = "{{password}}" if ("pass" in t_low or "pwd" in t_low) else "{{secret}}"
        sanitized_steps.append(
            {
                "order": a["order"],
                "action": a["action"],
                "target": a.get("target", ""),
                "value": val,
            }
        )
    payload = {
        "session_id": session_id,
        "recorded_at": created_at,
        "steps": sanitized_steps,
    }
    Path(case_file).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return case_file


def _auto_publish_session(
    session_id: str,
    steps: list[dict[str, Any]],
    case_name: str = "",
    target_url: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Auto-publish formatted steps to TCM web platform and return metadata."""
    from suitest_lifecycle.tools import create_test_case

    tc_name = case_name or f"Interactive Test {session_id[:8]}"
    create_kwargs = dict(kwargs)
    if target_url and "target_url" not in create_kwargs:
        create_kwargs["target_url"] = target_url

    try:
        tc_res = create_test_case(name=tc_name, steps=steps, **create_kwargs)
        if isinstance(tc_res, dict) and tc_res.get("success"):
            raw_data = tc_res.get("data")
            data_obj = raw_data if isinstance(raw_data, dict) else {}
            pub_id = str(data_obj.get("public_id") or data_obj.get("publicId") or "TC")
            web_base = (
                (
                    os.environ.get("SUITEST_WEB_URL")
                    or os.environ.get("SUITEST_API_URL")
                    or "http://localhost:5173"
                )
                .replace(":8000", ":5173")
                .rstrip("/")
            )
            return {
                "auto_publish": True,
                "case_id": pub_id,
                "dashboard_url": f"{web_base}/cases/{pub_id}",
            }
        err_msg = str(
            (tc_res.get("summary") if isinstance(tc_res, dict) else "")
            or "Failed to auto-publish test case to TCM"
        )
        errors = (
            tc_res.get("errors") if isinstance(tc_res, dict) and tc_res.get("errors") else [err_msg]
        )
        return {"auto_publish": False, "publish_error": err_msg, "errors": errors}
    except Exception as exc:
        return {"auto_publish": False, "publish_error": str(exc), "errors": [str(exc)]}


class InteractiveSessionManager:
    """Manages active interactive browser sessions with concurrency cap and TTL reaper."""

    MAX_SESSIONS = 3
    DEFAULT_TTL = 300.0  # 5 minutes

    def __init__(self) -> None:
        self._sessions: dict[str, InteractiveSession] = {}
        self._playwright: Any = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return self._executor.submit(fn, *args, **kwargs).result()

    def reap_expired(self) -> list[str]:
        """Close and remove sessions that exceeded inactivity TTL."""
        expired_ids: list[str] = []
        for sess_id, sess in list(self._sessions.items()):
            if sess.is_expired(self.DEFAULT_TTL):
                logger.info("interactive_browser.session_expired: %s", sess_id)
                sess.close()
                del self._sessions[sess_id]
                expired_ids.append(sess_id)
        return expired_ids

    def _open_session_impl(
        self,
        headless: bool = True,
        viewport: dict[str, int] | None = None,
        storage_state_path: str = "",
    ) -> str:
        self.reap_expired()
        if len(self._sessions) >= self.MAX_SESSIONS:
            raise ValueError(
                f"Maximum {self.MAX_SESSIONS} concurrent browser sessions reached. "
                "Close an active session using suitest_browser_close."
            )

        if self._playwright is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()

        vp = viewport or {"width": 1280, "height": 800}
        browser = self._playwright.chromium.launch(headless=headless)

        context_kwargs: dict[str, Any] = {"viewport": vp}
        if storage_state_path and Path(storage_state_path).is_file():
            context_kwargs["storage_state"] = str(storage_state_path)

        ctx = browser.new_context(**context_kwargs)
        page = ctx.new_page()

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = InteractiveSession(
            session_id=session_id,
            playwright_obj=self._playwright,
            browser=browser,
            context=ctx,
            page=page,
        )
        self._sessions[session_id] = session
        return session_id

    def open_session(
        self,
        headless: bool = True,
        viewport: dict[str, int] | None = None,
        storage_state_path: str = "",
    ) -> str:
        return cast(
            "str", self._run(self._open_session_impl, headless, viewport, storage_state_path)
        )

    def run_on_session(self, session_id: str, fn: Any) -> Any:
        def _wrapper() -> Any:
            sess = self.get_session(session_id)
            return fn(sess)

        return self._run(_wrapper)

    def get_session(self, session_id: str) -> InteractiveSession:
        self.reap_expired()
        session = self._sessions.get(session_id)
        if not session or session._closed:
            raise ValueError(
                f"Browser session '{session_id}' not found or has expired (TTL {int(self.DEFAULT_TTL)}s)."
            )
        session.touch()
        return session

    @staticmethod
    def _format_steps(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Translate recorded interactive browser actions into standard TCM step definitions."""
        steps: list[dict[str, Any]] = []
        for idx, act in enumerate(actions, start=1):
            action_type = act.get("action", "")
            target = act.get("target", "")
            val = act.get("value", "")
            extra = act.get("extra") or {}

            tool_name = "browser_click"
            tool_args: dict[str, Any] = {}
            step_action = f"Step {idx}: {action_type}"
            step_expected = f"Successfully executed {action_type}"

            if action_type == "navigate":
                tool_name = "browser_navigate"
                url = target or val
                tool_args = {"url": url}
                step_action = f"Navigate to {url}"
                step_expected = "Page loads successfully"
            elif action_type == "click":
                tool_name = "browser_click"
                tool_args = {"target": target}
                step_action = f"Click element '{target}'"
                step_expected = f"Element '{target}' is clicked"
            elif action_type == "type":
                tool_name = "browser_type"
                if _is_sensitive_input(target, extra=extra, value=val):
                    t_lower = target.lower()
                    var_name = "password" if ("pass" in t_lower or "pwd" in t_lower) else "secret"
                    secret_ref = (
                        val
                        if (isinstance(val, str) and val.startswith("{{") and val.endswith("}}"))
                        else f"{{{{{var_name}}}}}"
                    )
                    tool_args = {"target": target, "text": secret_ref}
                    step_action = f"Type secret into '{target}'"
                    step_expected = "Sensitive input populated via secret reference"
                else:
                    tool_args = {"target": target, "text": val}
                    step_action = f"Type into '{target}'"
                    step_expected = "Input value populated"
            elif action_type == "select":
                tool_name = "browser_select_option"
                tool_args = {"target": target, "values": [str(val)]}
                step_action = f"Select option '{val}' in '{target}'"
                step_expected = f"Option '{val}' selected"
            elif action_type == "solve_captcha":
                tool_name = "browser_solve_captcha"
                tool_args = {
                    "image_selector": extra.get("image_selector", target),
                    "input_selector": extra.get("input_selector", val),
                }
                step_action = "Solve CAPTCHA challenge"
                step_expected = "CAPTCHA resolved"

            steps.append(
                {
                    "action": step_action,
                    "expected": step_expected,
                    "code": {"tool": tool_name, "arguments": tool_args},
                    "mcp_provider": "playwright-mcp",
                    "target_kind": "FE_WEB",
                    "order": idx,
                }
            )
        return steps

    def _close_session_impl(
        self,
        session_id: str,
        save_as_case: bool = False,
        output_dir: str = "suitest-output/cases",
        auto_publish: bool = False,
        case_name: str = "",
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        session = self._sessions.pop(session_id, None)
        if not session:
            raise ValueError(
                f"Browser session '{session_id}' not found or has expired (TTL {int(self.DEFAULT_TTL)}s)."
            )

        actions = [a.to_json() for a in session.action_history]
        target_url = _extract_session_target_url(
            session=session,
            actions=actions,
            default_url=str(kwargs.get("target_url") or ""),
        )
        created_at = session.created_at
        session.close()

        case_file = (
            _save_session_case_file(session_id, created_at, actions, output_dir)
            if save_as_case
            else ""
        )

        meta: dict[str, Any] = {"session_id": session_id, "steps_count": len(actions)}
        if auto_publish and actions:
            pub_meta = _auto_publish_session(
                session_id=session_id,
                steps=self._format_steps(actions),
                case_name=case_name,
                target_url=target_url,
                **kwargs,
            )
            meta.update(pub_meta)

        return actions, case_file, meta

    def close_session(
        self,
        session_id: str,
        save_as_case: bool = False,
        output_dir: str = "suitest-output/cases",
        auto_publish: bool = False,
        case_name: str = "",
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        return cast(
            "tuple[list[dict[str, Any]], str, dict[str, Any]]",
            self._run(
                self._close_session_impl,
                session_id,
                save_as_case,
                output_dir,
                auto_publish,
                case_name,
                **kwargs,
            ),
        )

    def _close_all_impl(self) -> None:
        for sess in self._sessions.values():
            sess.close()
        self._sessions.clear()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
            self._playwright = None

    def close_all(self) -> None:
        self._run(self._close_all_impl)


# Global module singleton for the MCP stdio runtime process
_GLOBAL_MANAGER = InteractiveSessionManager()


# --------------------------------------------------------------------------- #
# MCP Tool Implementations
# --------------------------------------------------------------------------- #


def suitest_browser_open(
    headless: bool = True,
    viewport: dict[str, int] | None = None,
    storage_state_path: str = "",
    require_auth: bool = False,
    credentials: dict[str, str] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Open a new stateful interactive browser session with pre-flight auth check."""
    if require_auth and not credentials and not storage_state_path:
        return {
            "success": False,
            "status": "NEEDS_CLARIFICATION",
            "summary": "Target authentication credentials required before opening browser session. Provide credentials or storage_state_path to avoid Inactivity TTL Reaper expiration.",
            "data": {"pending_fields": ["username", "password"]},
            "errors": ["missing_credentials"],
        }
    try:
        session_id = _GLOBAL_MANAGER.open_session(
            headless=headless,
            viewport=viewport,
            storage_state_path=storage_state_path,
        )
        return _envelope(
            success=True,
            summary=f"Opened interactive browser session '{session_id}'",
            data={"session_id": session_id},
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Failed to open browser session: {exc}",
            errors=[str(exc)],
        )


def suitest_browser_navigate(
    session_id: str = "",
    url: str = "",
    wait_strategy: str = "domcontentloaded",
    **_: Any,
) -> dict[str, Any]:
    """Navigate to a target URL in the specified interactive session."""
    if not session_id or not url:
        return _envelope(
            False, "session_id and url are required", errors=["missing required parameters"]
        )
    try:

        def _nav(sess: InteractiveSession) -> tuple[str, str]:
            strategy = (
                wait_strategy
                if wait_strategy in ("load", "domcontentloaded", "networkidle", "commit")
                else "domcontentloaded"
            )
            sess.page.goto(url, wait_until=strategy, timeout=25000)
            curr_url = sess.page.url
            title = sess.page.title()
            sess.record_action("navigate", target="", value=url, current_url=curr_url, title=title)
            return curr_url, title

        curr_url, title = _GLOBAL_MANAGER.run_on_session(session_id, _nav)
        return _envelope(
            success=True,
            summary=f"Navigated to '{url}' — landed on '{curr_url}'",
            data={"session_id": session_id, "url": curr_url, "title": title},
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Navigation failed on session '{session_id}': {exc}",
            errors=[str(exc)],
        )


def suitest_browser_click(
    session_id: str = "",
    target: str = "",
    timeout_ms: int = 10000,
    **_: Any,
) -> dict[str, Any]:
    """Click an element matching selector in the interactive session."""
    if not session_id or not target:
        return _envelope(
            False, "session_id and target selector are required", errors=["missing parameters"]
        )
    try:

        def _click(sess: InteractiveSession) -> None:
            loc = sess.page.locator(target)
            if hasattr(loc, "first"):
                loc = loc.first

            # If not immediately visible, check for parent collapsible container
            if not loc.is_visible():
                uncollapse_info = sess.page.evaluate(
                    """(rawTarget) => {
                        let el = null;
                        try {
                            if (rawTarget.includes(':has-text(')) {
                                const m = rawTarget.match(/(.*?):has-text\\((["']?)(.*?)\\2\\)/);
                                if (m) {
                                    const tag = m[1] || '*';
                                    const text = m[3];
                                    const candidates = Array.from(document.querySelectorAll(tag));
                                    el = candidates.find(c => (c.innerText || c.textContent || '').trim().includes(text));
                                }
                            }
                        } catch (_) {}
                        if (!el) {
                            try { el = document.querySelector(rawTarget); } catch (_) {}
                        }
                        if (!el) return null;
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
                        if (!container) return null;

                        let toggleSel = '';
                        if (container.getAttribute('data-ktwizard-type') === 'step-content') {
                            const allPanes = Array.from(document.querySelectorAll('[data-ktwizard-type="step-content"]'));
                            const stepIdx = allPanes.indexOf(container);
                            const allNavs = Array.from(document.querySelectorAll('[data-ktwizard-type="step"]'));
                            if (stepIdx >= 0 && allNavs[stepIdx]) {
                                const navEl = allNavs[stepIdx];
                                const txt = (navEl.innerText || '').trim().slice(0, 30);
                                toggleSel = '[data-ktwizard-type="step"]:has-text("' + txt + '")';
                            }
                        }
                        if (!toggleSel && container.classList.contains('tab-pane') && container.id) {
                            const tabNav = document.querySelector('a[href="#' + container.id + '"], [data-bs-target="#' + container.id + '"], [data-target="#' + container.id + '"]');
                            if (tabNav) {
                                if (tabNav.id) toggleSel = '#' + tabNav.id;
                                else if (tabNav.getAttribute('data-bs-target')) toggleSel = `[data-bs-target="${tabNav.getAttribute('data-bs-target')}"]`;
                                else if (tabNav.getAttribute('data-target')) toggleSel = `[data-target="${tabNav.getAttribute('data-target')}"]`;
                                else if (tabNav.getAttribute('href')) toggleSel = `a[href="${tabNav.getAttribute('href')}"]`;
                                else toggleSel = '#' + container.id + '-tab, a[href="#' + container.id + '"]';
                            }
                        }
                        if (!toggleSel) {
                            const parent = container.parentElement;
                            const toggle = parent ? parent.querySelector(`
                                .kt-menu__toggle,
                                [data-bs-toggle="collapse"],
                                [data-toggle="collapse"],
                                .accordion-button.collapsed,
                                summary,
                                [aria-expanded="false"]
                            `) : null;
                            if (!toggle) return null;
                            if (toggle.id) toggleSel = '#' + toggle.id;
                            else if (toggle.className && typeof toggle.className === 'string') {
                                const c = Array.from(toggle.classList).filter(x => !x.includes(':')).join('.');
                                if (c) toggleSel = toggle.tagName.toLowerCase() + '.' + c;
                            }
                            if (!toggleSel) toggleSel = toggle.tagName.toLowerCase();
                            const txt = (toggle.innerText || '').trim().slice(0, 30);
                            if (txt) toggleSel += ':has-text("' + txt + '")';
                        }
                        return toggleSel ? { toggleSelector: toggleSel } : null;
                    }""",
                    target,
                )
                if uncollapse_info and uncollapse_info.get("toggleSelector"):
                    toggle_sel = uncollapse_info["toggleSelector"]
                    t_loc = sess.page.locator(toggle_sel).first
                    if t_loc.is_visible():
                        t_loc.click()
                        sess.record_action("click", target=toggle_sel)
                        sess.page.wait_for_timeout(400)

            try:
                loc.wait_for(state="visible", timeout=timeout_ms)
                loc.click()
            except Exception:
                # Fallback to dispatch event click if element is in DOM
                dispatched = sess.page.evaluate(
                    """(rawTarget) => {
                        let el = null;
                        try {
                            if (rawTarget.includes(':has-text(')) {
                                const m = rawTarget.match(/(.*?):has-text\\((["']?)(.*?)\\2\\)/);
                                if (m) {
                                    const tag = m[1] || '*';
                                    const text = m[3];
                                    const candidates = Array.from(document.querySelectorAll(tag));
                                    el = candidates.find(c => (c.innerText || c.textContent || '').trim().includes(text));
                                }
                            }
                        } catch (_) {}
                        if (!el) {
                            try { el = document.querySelector(rawTarget); } catch (_) {}
                        }
                        if (el) {
                            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                            return true;
                        }
                        return false;
                    }""",
                    target,
                )
                if not dispatched:
                    raise
            sess.record_action("click", target=target)

        _GLOBAL_MANAGER.run_on_session(session_id, _click)
        return _envelope(
            success=True,
            summary=f"Clicked '{target}'",
            data={"session_id": session_id, "target": target},
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Click failed on '{target}': {exc}",
            errors=[str(exc)],
        )


def suitest_browser_type(
    session_id: str = "",
    target: str = "",
    text: str = "",
    timeout_ms: int = 10000,
    **_: Any,
) -> dict[str, Any]:
    """Fill text into an input or textarea matching selector."""
    if not session_id or not target:
        return _envelope(False, "session_id and target are required", errors=["missing parameters"])
    try:

        def _type(sess: InteractiveSession) -> None:
            loc = sess.page.locator(target)
            if hasattr(loc, "first"):
                loc = loc.first
            loc.wait_for(state="visible", timeout=timeout_ms)
            inp_type = ""
            with contextlib.suppress(Exception):
                inp_type = str(loc.get_attribute("type") or "")
            loc.fill(text)
            extra_info: dict[str, Any] = {"input_type": inp_type}
            if _is_sensitive_input(target, extra=extra_info, value=text):
                t_lower = target.lower()
                var_name = "password" if ("pass" in t_lower or "pwd" in t_lower) else "secret"
                stored_val = (
                    text
                    if (isinstance(text, str) and text.startswith("{{") and text.endswith("}}"))
                    else f"{{{{{var_name}}}}}"
                )
                extra_info["is_secret"] = True
                sess.record_action("type", target=target, value=stored_val, **extra_info)
            else:
                sess.record_action("type", target=target, value=text, **extra_info)

        _GLOBAL_MANAGER.run_on_session(session_id, _type)
        return _envelope(
            success=True,
            summary=f"Typed text into '{target}'",
            data={"session_id": session_id, "target": target},
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Type failed on '{target}': {exc}",
            errors=[str(exc)],
        )


def suitest_browser_select(
    session_id: str = "",
    target: str = "",
    value: str = "",
    timeout_ms: int = 10000,
    **_: Any,
) -> dict[str, Any]:
    """Select an option in a select dropdown matching selector."""
    if not session_id or not target:
        return _envelope(False, "session_id and target are required", errors=["missing parameters"])
    try:

        def _select(sess: InteractiveSession) -> None:
            loc = sess.page.locator(target)
            if hasattr(loc, "first"):
                loc = loc.first
            loc.wait_for(state="visible", timeout=timeout_ms)
            loc.select_option(value=value)
            sess.record_action("select", target=target, value=value)

        _GLOBAL_MANAGER.run_on_session(session_id, _select)
        return _envelope(
            success=True,
            summary=f"Selected '{value}' in '{target}'",
            data={"session_id": session_id, "target": target, "value": value},
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Select failed on '{target}': {exc}",
            errors=[str(exc)],
        )


def suitest_browser_solve_captcha(
    session_id: str = "",
    image_target: str = "#img-captcha",
    input_target: str = "#captcha",
    **_: Any,
) -> dict[str, Any]:
    """Locally decode and solve CAPTCHA in the active session."""
    if not session_id:
        return _envelope(False, "session_id is required", errors=["missing session_id"])
    try:

        def _solve(sess: InteractiveSession) -> tuple[str, str, bool]:
            img_loc = sess.page.locator(image_target)
            if hasattr(img_loc, "first"):
                img_loc = img_loc.first
            img_loc.wait_for(state="visible", timeout=8000)

            if build_tiny_ocr_element_eval_script is None:
                raise RuntimeError("suitest_shared.ocr not available in standalone stdlib mode")
            eval_script = build_tiny_ocr_element_eval_script()
            res = img_loc.evaluate(eval_script)

            solved_text = ""
            source = "tiny_ocr"
            if isinstance(res, dict) and res.get("status") == "solved":
                solved_text = str(res.get("text") or "")
                source = str(res.get("source") or "tiny_ocr")

            raw_ocr = str(res.get("rawOcr") or "") if isinstance(res, dict) else ""
            if not solved_text and raw_ocr:
                classified = classify_ocr_output(raw_ocr)
                if classified.get("status") == "solved":
                    solved_text = str(classified.get("text") or "")
                    source = str(classified.get("source") or "local_math")

            filled = False
            if solved_text and input_target:
                with contextlib.suppress(Exception):
                    inp = sess.page.locator(input_target)
                    if hasattr(inp, "first"):
                        inp = inp.first
                    inp.fill(solved_text)
                    filled = True

            sess.record_action(
                "solve_captcha",
                target=image_target,
                value=solved_text,
                input_target=input_target,
                filled=filled,
            )
            return solved_text, source, filled

        solved_text, source, filled = _GLOBAL_MANAGER.run_on_session(session_id, _solve)
        return _envelope(
            success=bool(solved_text),
            summary=(
                f"CAPTCHA solved: '{solved_text}' ({source})"
                if solved_text
                else "CAPTCHA could not be solved locally"
            ),
            data={
                "session_id": session_id,
                "solved_text": solved_text,
                "source": source,
                "filled": filled,
            },
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"CAPTCHA solve failed: {exc}",
            errors=[str(exc)],
        )


def suitest_browser_snapshot(
    session_id: str = "",
    include_screenshot: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """Capture structured page snapshot (URL, inputs, buttons, screenshot base64)."""
    if not session_id:
        return _envelope(False, "session_id is required", errors=["missing session_id"])
    try:

        def _snap(sess: InteractiveSession) -> dict[str, Any]:
            from suitest_lifecycle.blackbox.crawler import _EXTRACT_JS

            data = sess.page.evaluate(_EXTRACT_JS)
            b64_shot = ""
            if include_screenshot:
                with contextlib.suppress(Exception):
                    raw_bytes = sess.page.screenshot(type="png")
                    b64_shot = "data:image/png;base64," + base64.b64encode(raw_bytes).decode(
                        "ascii"
                    )

            sess.touch()
            return {
                "session_id": session_id,
                "url": sess.page.url,
                "title": sess.page.title(),
                "inputs_count": len(data.get("inputs", [])),
                "buttons_count": len(data.get("buttons", [])),
                "has_captcha": bool(data.get("hasCaptcha")),
                "inputs": data.get("inputs", []),
                "buttons": data.get("buttons", []),
                "screenshot_base64": b64_shot,
            }

        snap_data = _GLOBAL_MANAGER.run_on_session(session_id, _snap)
        return _envelope(
            success=True,
            summary=f"Snapshot captured: '{snap_data['title']}' ({snap_data['url']})",
            data=snap_data,
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Snapshot failed: {exc}",
            errors=[str(exc)],
        )


def suitest_browser_close(
    session_id: str = "",
    save_as_case: bool = False,
    output_dir: str = "suitest-output/cases",
    auto_publish: bool = False,
    case_name: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Close an active interactive browser session, optionally saving action trace or auto-publishing to TCM."""
    if not session_id:
        return _envelope(False, "session_id is required", errors=["missing session_id"])
    try:
        actions, case_file, meta = _GLOBAL_MANAGER.close_session(
            session_id,
            save_as_case=save_as_case,
            output_dir=output_dir,
            auto_publish=auto_publish,
            case_name=case_name,
            **kwargs,
        )
        artifacts = [case_file] if case_file else []
        if auto_publish and not meta.get("auto_publish", False):
            err_msg = meta.get("publish_error", "Failed to auto-publish test case to TCM")
            errors = meta.get("errors") or [err_msg]
            return _envelope(
                success=False,
                summary=f"Closed browser session '{session_id}' but auto-publish failed: {err_msg}",
                data={"session_id": session_id, "actions_count": len(actions), **meta},
                errors=errors,
                artifacts=artifacts,
            )
        return _envelope(
            success=True,
            summary=f"Closed browser session '{session_id}' (recorded {len(actions)} actions)",
            data={"session_id": session_id, "actions_count": len(actions), **meta},
            artifacts=artifacts,
        )
    except Exception as exc:
        return _envelope(
            success=False,
            summary=f"Failed to close session: {exc}",
            errors=[str(exc)],
        )


INTERACTIVE_BROWSER_TOOLS = {
    "suitest_browser_open": suitest_browser_open,
    "suitest_browser_navigate": suitest_browser_navigate,
    "suitest_browser_click": suitest_browser_click,
    "suitest_browser_type": suitest_browser_type,
    "suitest_browser_select": suitest_browser_select,
    "suitest_browser_solve_captcha": suitest_browser_solve_captcha,
    "suitest_browser_snapshot": suitest_browser_snapshot,
    "suitest_browser_close": suitest_browser_close,
}

__all__ = [
    "INTERACTIVE_BROWSER_TOOLS",
    "InteractiveSession",
    "InteractiveSessionManager",
    "suitest_browser_click",
    "suitest_browser_close",
    "suitest_browser_navigate",
    "suitest_browser_open",
    "suitest_browser_select",
    "suitest_browser_snapshot",
    "suitest_browser_solve_captcha",
    "suitest_browser_type",
]
