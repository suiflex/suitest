"""DOM CAPTCHA Detector matching Suitest Recorder heuristics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

SUBMIT_TRIGGER_PATTERN = re.compile(
    r"(submit|login|masuk|sign[-\s]?in|log[-\s]?in|kirim|register|daftar)",
    re.IGNORECASE,
)


def is_submit_action(target_selector: str, tool_name: str) -> bool:
    """Check if target element selector or tool represents a form submission action."""
    if tool_name not in ("browser_click", "browser.click"):
        return False
    return bool(SUBMIT_TRIGGER_PATTERN.search(target_selector))


@dataclass(frozen=True)
class CaptchaDetectResult:
    is_captcha: bool
    input_selector: str | None = None
    image_selector: str | None = None
    refresh_target: str | None = None
    is_empty: bool = True


def build_detect_captcha_script(
    target_input_selector: str | None = None,
    frame_chain: str = "page",
) -> str:
    """Generate Playwright JavaScript snippet to detect captcha input and nearest image.

    Uses identical DOM heuristics as apps/web/public/recorder_agent.js:
    - isCaptchaField: checks name, id, placeholder, aria-label, data-testid, and className.
    - findNearestCaptchaImage: checks closest form/card containers with semantic and Euclidean distance priority.
    """
    target_json = json.dumps(target_input_selector)
    return f"""async (page) => {{
    const frame = {frame_chain};

    function isCaptchaField(el) {{
        if (!el || !el.tagName) return false;
        if (el.tagName.toLowerCase() !== "input") return false;
        const name = (el.name || "").toLowerCase();
        const id = (el.id || "").toLowerCase();
        const placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
        const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
        const testId = (el.getAttribute("data-test") || el.getAttribute("data-testid") || "").toLowerCase();
        const className = (el.className || "").toLowerCase();
        const combined = name + " " + id + " " + placeholder + " " + ariaLabel + " " + testId + " " + className;
        return /captcha|secur(ity)?[-\\s_]?code|verif(ication)?[-\\s_]?code|kode[-\\s_]?keamanan/i.test(combined);
    }}

    function findNearestCaptchaImage(inputEl) {{
        if (!inputEl) return null;
        const container = inputEl.closest("form") || inputEl.closest(".card, .login-box, .auth-box, div") || document.body;
        const images = Array.from(container.querySelectorAll("img, canvas"));

        for (let i = 0; i < images.length; i++) {{
            const img = images[i];
            const imgStr = ((img.id || "") + " " + (img.className || "") + " " + (img.getAttribute("src") || "") + " " + (img.getAttribute("alt") || "") + " " + (img.getAttribute("data-testid") || "")).toLowerCase();
            if (/captcha|secur|code|verif|token/i.test(imgStr)) {{
                return img;
            }}
        }}

        if (images.length > 0 && typeof inputEl.getBoundingClientRect === "function") {{
            const inputRect = inputEl.getBoundingClientRect();
            let bestImg = null;
            let minDistance = Infinity;
            for (let j = 0; j < images.length; j++) {{
                const cand = images[j];
                const cRect = typeof cand.getBoundingClientRect === "function" ? cand.getBoundingClientRect() : {{ top: 0, left: 0 }};
                const dist = Math.abs(cRect.top - inputRect.top) + Math.abs(cRect.left - inputRect.left);
                if (dist < minDistance) {{
                    minDistance = dist;
                    bestImg = cand;
                }}
            }}
            if (bestImg) return bestImg;
        }}
        return images[0] || null;
    }}

    const targetInputSel = {target_json};
    let inputEl = null;

    if (targetInputSel) {{
        try {{
            inputEl = await frame.locator(targetInputSel).elementHandle();
        }} catch (_) {{}}
    }}

    if (!inputEl) {{
        const inputs = await frame.$$("input");
        for (const inp of inputs) {{
            const isMatch = await inp.evaluate((el) => isCaptchaField(el));
            if (isMatch) {{
                inputEl = inp;
                break;
            }}
        }}
    }}

    if (!inputEl) {{
        return {{ is_captcha: false }};
    }}

    const detection = await inputEl.evaluate((el) => {{
        const isMatch = isCaptchaField(el);
        if (!isMatch) return {{ is_captcha: false }};

        const imgEl = findNearestCaptchaImage(el);
        const imgSel = imgEl ? (imgEl.id ? "#" + imgEl.id : (imgEl.getAttribute("data-testid") ? "[data-testid='" + imgEl.getAttribute("data-testid") + "']" : "img")) : "img";
        const val = (el.value || "").trim();

        let refreshSel = null;
        if (imgEl && (imgEl.style.cursor === "pointer" || imgEl.onclick || imgEl.getAttribute("onclick"))) {{
            refreshSel = imgSel;
        }}

        const inpSel = el.id ? "#" + el.id : (el.name ? "input[name='" + el.name + "']" : (el.getAttribute("data-testid") ? "[data-testid='" + el.getAttribute("data-testid") + "']" : "input"));

        return {{
            is_captcha: true,
            is_empty: val === "",
            input_selector: inpSel,
            image_selector: imgSel,
            refresh_target: refreshSel,
        }};
    }});

    return detection;
}}"""
