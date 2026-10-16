"""In-browser Tiny WASM OCR with Canvas Pixel Pre-Filter and Local Math Evaluator.

Allows Suitest Runner to solve simple text/math CAPTCHAs in < 150ms directly inside
the browser page context without making a roundtrip to a remote Vision LLM.
Automatically falls back to Vision LLM if the canvas pre-filter detects high noise/distortion,
or if the post-filter detects ambiguous OCR output.
"""

from __future__ import annotations

import functools
import gzip
import json
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_ASSET_PATH = Path(__file__).parent.parent / "assets" / "ocrad.js.gz"


@functools.cache
def load_ocrad_source() -> str:
    """Load and decompress bundled ocrad.js source into memory."""
    if not _ASSET_PATH.exists():
        return ""
    with gzip.open(_ASSET_PATH, "rt", encoding="utf-8") as f:
        return f.read()


def evaluate_math_expression(cleaned: str) -> int | None:
    """Evaluate simple arithmetic expression like '12 + 5 = ?', '8 - 3', '6 x 7'."""
    m = re.match(
        r"^(\d{1,4})\s*([\+\-\*xX\/])\s*(\d{1,4})(?:\s*=\s*\??|\s*\??)?$",
        cleaned.strip(),
    )
    if not m:
        return None
    a = int(m.group(1))
    op = m.group(2).lower()
    b = int(m.group(3))
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op in ("*", "x"):
        return a * b
    if op == "/" and b != 0:
        return a // b
    return None


def classify_ocr_output(raw_text: str) -> dict[str, Any]:
    """Sanitize and classify raw OCR text into solved or fallback.

    Returns dict with keys:
    - status: "solved" | "fallback"
    - text: str (when solved)
    - source: "tiny_ocr" | "local_math"
    - reason: str (when fallback)
    """
    if not raw_text:
        return {"status": "fallback", "reason": "empty_text"}
    cleaned = raw_text.strip()

    # 1. Math check
    math_val = evaluate_math_expression(cleaned)
    if math_val is not None:
        return {"status": "solved", "text": str(math_val), "source": "local_math"}

    # 2. Alphanumeric sanitization
    alpha_num = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    if len(alpha_num) >= 4:
        return {"status": "solved", "text": alpha_num, "source": "tiny_ocr"}

    return {"status": "fallback", "reason": "text_too_short_or_ambiguous", "raw": cleaned}


def build_tiny_ocr_solve_script(
    image_selector: str,
    frame_chain: str = "page",
) -> str:
    """Generate Playwright JavaScript snippet that runs pre-filter and in-browser Tiny OCR."""
    ocrad_code = load_ocrad_source()
    image_selector_json = json.dumps(image_selector)

    return f"""async (page) => {{
    const frame = {frame_chain};
    const target = frame.locator({image_selector_json});
    await target.waitFor({{ state: "visible", timeout: 8000 }});

    await target.evaluate(async (img) => {{
        if (img && img.tagName && img.tagName.toLowerCase() === "img") {{
            if (img.complete && img.naturalWidth > 0) return true;
            return new Promise((resolve) => {{
                img.addEventListener("load", () => resolve(true), {{ once: true }});
                img.addEventListener("error", () => resolve(false), {{ once: true }});
                setTimeout(() => resolve(img.complete && img.naturalWidth > 0), 5000);
            }});
        }}
        return true;
    }});

    const evalResult = await target.evaluate((img) => {{
        try {{
            if (!img) return {{ status: "fallback", reason: "element_not_found" }};
            const c = document.createElement("canvas");
            const w = img.naturalWidth || img.width || img.clientWidth || 120;
            const h = img.naturalHeight || img.height || img.clientHeight || 40;
            c.width = w > 0 ? w : 120;
            c.height = h > 0 ? h : 40;
            const ctx = c.getContext("2d");
            if (!ctx) return {{ status: "fallback", reason: "no_canvas_context" }};

            ctx.drawImage(img, 0, 0, c.width, c.height);
            const dataUrl = c.toDataURL("image/png");

            // --- Canvas Pixel Pre-Filter ---
            const imgData = ctx.getImageData(0, 0, c.width, c.height);
            const d = imgData.data;
            const corners = [
                0,
                (c.width - 1) * 4,
                ((c.height - 1) * c.width) * 4,
                ((c.height - 1) * c.width + (c.width - 1)) * 4,
            ];
            let bgR = 0, bgG = 0, bgB = 0;
            for (let i = 0; i < 4; i++) {{
                bgR += d[corners[i]];
                bgG += d[corners[i] + 1];
                bgB += d[corners[i] + 2];
            }}
            bgR /= 4; bgG /= 4; bgB /= 4;

            let bgVariance = 0;
            let textPixels = 0;
            const totalPixels = c.width * c.height;
            for (let i = 0; i < d.length; i += 4) {{
                const diff = Math.abs(d[i] - bgR) + Math.abs(d[i+1] - bgG) + Math.abs(d[i+2] - bgB);
                if (diff > 60) {{
                    textPixels++;
                }} else {{
                    bgVariance += diff;
                }}
            }}

            const textRatio = textPixels / totalPixels;
            const avgBgVariance = bgVariance / (totalPixels - textPixels || 1);

            // Escalate if noisy background or abnormal text stroke density
            if (avgBgVariance >= 30 || textRatio < 0.03 || textRatio > 0.60) {{
                return {{
                    status: "fallback",
                    reason: "high_noise_or_distortion",
                    avgBgVariance,
                    textRatio,
                    image_base64: dataUrl,
                }};
            }}

            // --- Self-contained In-Memory OCR ---
            if (typeof window.OCRAD !== "function") {{
                {ocrad_code}
                if (typeof OCRAD === "function") {{
                    window.OCRAD = OCRAD;
                }}
            }}

            const ocrFunc = typeof window.OCRAD === "function" ? window.OCRAD : (typeof OCRAD === "function" ? OCRAD : null);
            if (!ocrFunc) {{
                return {{ status: "fallback", reason: "ocr_engine_unavailable", image_base64: dataUrl }};
            }}

            const rawOcr = ocrFunc(c);
            const cleaned = (rawOcr || "").trim();

            // --- Math Classifier ---
            const mathMatch = cleaned.match(/^(\\d{{1,4}})\\s*([\\+\\-\\*xX\\/])\\s*(\\d{{1,4}})(?:\\s*=\\s*\\??|\\s*\\??)?$/);
            if (mathMatch) {{
                const a = parseInt(mathMatch[1], 10);
                const op = mathMatch[2].toLowerCase();
                const b = parseInt(mathMatch[3], 10);
                let val = null;
                if (op === "+") val = a + b;
                else if (op === "-") val = a - b;
                else if (op === "*" || op === "x") val = a * b;
                else if (op === "/" && b !== 0) val = Math.floor(a / b);
                if (val !== null) {{
                    return {{ status: "solved", text: String(val), source: "local_math", rawOcr }};
                }}
            }}

            // --- Post-Filter Character Validation ---
            const alphaNum = cleaned.replace(/[^a-zA-Z0-9]/g, "");
            if (alphaNum.length >= 4) {{
                return {{ status: "solved", text: alphaNum, source: "tiny_ocr", rawOcr }};
            }}

            return {{
                status: "fallback",
                reason: "ocr_result_ambiguous",
                rawOcr: cleaned,
                image_base64: dataUrl,
            }};
        }} catch (err) {{
            return {{ status: "fallback", reason: "eval_error: " + err.toString() }};
        }}
    }});

    if (evalResult && evalResult.status === "solved") {{
        return JSON.stringify(evalResult);
    }}

    let b64 = evalResult && evalResult.image_base64 ? evalResult.image_base64 : "";
    if (!b64) {{
        await page.waitForTimeout(200);
        const buf = await target.screenshot({{ type: "png" }});
        b64 = "data:image/png;base64," + buf.toString("base64");
    }}

    return JSON.stringify({{
        status: "fallback",
        reason: evalResult ? evalResult.reason : "unknown",
        image_base64: b64,
    }});
}}"""


def clean_and_decode_base64(b64_candidate: str, selector: str = "element") -> bytes:
    """Strip data URI prefixes and decode base64 screenshot bytes."""
    b64_str = str(b64_candidate or "").strip().strip("\"' \r\n\t")
    if b64_str.startswith("data:") and ";base64," in b64_str:
        b64_str = b64_str.split(";base64,", 1)[1]
    elif b64_str.startswith("data:") and "," in b64_str:
        b64_str = b64_str.split(",", 1)[1]
    b64_str = b64_str.strip("\"' \r\n\t")

    if not b64_str:
        return b""

    try:
        import base64

        return base64.b64decode(b64_str)
    except Exception as exc:
        raise ValueError(f"Failed to decode CAPTCHA screenshot for {selector}: {exc}") from exc


def _extract_raw_eval_payload(snap_result: Any) -> Any:
    """Extract raw evaluate payload from McpToolResult output or stdout."""
    if hasattr(snap_result, "output") and isinstance(snap_result.output, dict):
        if "result" in snap_result.output:
            return snap_result.output["result"]
        if "status" in snap_result.output:
            return snap_result.output

    stdout = getattr(snap_result, "stdout", None) or ""
    if stdout:
        m = re.search(r"^### Result\s*\n(.*?)(?=\n###|\Z)", stdout, re.MULTILINE | re.DOTALL)
        candidate = m.group(1).strip() if m else stdout.strip()
        try:
            parsed = json.loads(candidate)
            return parsed.get("result", parsed) if isinstance(parsed, dict) else parsed
        except (json.JSONDecodeError, ValueError) as exc:
            log.debug("tiny_ocr.parse_stdout_fallback", error=str(exc))
            return candidate
    return None


def _try_parse_nested_json(raw_val: Any) -> Any:
    """Unwrap stringified JSON payloads returned by page.evaluate."""
    if not isinstance(raw_val, str) or not (raw_val.startswith("{") or raw_val.startswith('"{')):
        return raw_val
    try:
        first_pass = json.loads(raw_val)
        if isinstance(first_pass, str) and first_pass.startswith("{"):
            return json.loads(first_pass)
        return first_pass
    except (json.JSONDecodeError, ValueError) as exc:
        log.debug("tiny_ocr.unwrap_nested_json_skip", error=str(exc))
        return raw_val


def parse_browser_eval_result(
    snap_result: Any,
    image_selector: str = "img",
) -> tuple[str | None, bytes | None]:
    """Parse result from browser evaluation of build_tiny_ocr_solve_script.

    Returns:
        (solved_text, None) if solved locally by Tiny OCR / Math evaluator.
        (None, image_bytes) if escalated to Vision LLM fallback.
    """
    raw_val = _extract_raw_eval_payload(snap_result)
    unwrapped = _try_parse_nested_json(raw_val)

    if isinstance(unwrapped, dict):
        if unwrapped.get("status") == "solved":
            text = str(unwrapped.get("text") or "").strip()
            if text:
                return text, None
        b64_candidate = str(unwrapped.get("image_base64") or "")
    else:
        b64_candidate = str(unwrapped or "")

    image_bytes = clean_and_decode_base64(b64_candidate, image_selector)
    return (None, image_bytes) if image_bytes else (None, None)
