"""Multimodal Vision CAPTCHA solver using LiteLLM."""

from __future__ import annotations

import base64
import re
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

CaptchaType = Literal["auto", "alphanumeric", "math", "numeric"]

PROMPTS_BY_TYPE: dict[str, str] = {
    "auto": (
        "You are a dedicated high-precision OCR engine specialized in CAPTCHA transcription. "
        "Examine the provided image. "
        "1. If the image displays a clear dictionary word (e.g. 'PRINGSEWU') or alphanumeric text, output ONLY the exact text. "
        "2. If the image displays a simple arithmetic question (e.g. '7 + 5 = ?'), solve the calculation and output ONLY the single numerical answer. "
        "3. If the image displays numbers, output ONLY the digits. "
        "Do NOT include explanations, greetings, quotation marks, punctuation, or spaces."
    ),
    "alphanumeric": (
        "You are a dedicated high-precision OCR engine specialized in CAPTCHA transcription. "
        "Examine the provided image and output ONLY the exact alphanumeric characters or words visible in the CAPTCHA. "
        "Do NOT include explanations, greetings, quotation marks, punctuation, or spaces."
    ),
    "math": (
        "You are a dedicated high-precision arithmetic CAPTCHA solver. "
        "Examine the math problem displayed in the image (e.g. addition, subtraction, multiplication), calculate the correct answer, and output ONLY the final numeric result. "
        "Do NOT output the equation or any explanation."
    ),
    "numeric": (
        "You are a dedicated high-precision OCR engine specialized in numeric CAPTCHAs. "
        "Examine the provided image and output ONLY the digits (0-9) visible in the CAPTCHA. "
        "Do NOT include letters, punctuation, spaces, or explanations."
    ),
}


def clean_captcha_text(
    raw_text: str,
    force_uppercase: bool = False,
    captcha_type: CaptchaType = "auto",
) -> str:
    """Sanitize model output to pure captcha string according to type."""
    cleaned = raw_text.strip()
    # Strip common AI chat preludes
    cleaned = re.sub(
        r"^(the\s+(captcha\s+)?(code|text|answer|result)\s+(in\s+the\s+image\s+)?is\s*:?\s*|captcha\s*:\s*|code\s*:\s*|result\s*:\s*|answer\s*:\s*)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    if captcha_type in ("math", "numeric"):
        # For math or numeric, keep digits (and optional minus sign if negative)
        digits = re.sub(r"[^\d\-]", "", cleaned).strip()
        return digits if digits else cleaned

    # For alphanumeric / auto
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned).strip()
    if force_uppercase:
        cleaned = cleaned.upper()
    return cleaned


async def solve_captcha_image(
    image_bytes: bytes,
    *,
    llm_router: Any,
    model: str | None = None,
    force_uppercase: bool = False,
    captcha_type: CaptchaType = "auto",
) -> str:
    """Send cropped image buffer to LiteLLM Vision model and return sanitized text."""
    if not image_bytes:
        raise ValueError("Image bytes are empty or missing")

    b64_data = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:image/png;base64,{b64_data}"

    prompt = PROMPTS_BY_TYPE.get(captcha_type, PROMPTS_BY_TYPE["auto"])

    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Solve or transcribe the CAPTCHA code from this image:"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        },
    ]

    log.info(
        "captcha_solver.dispatch",
        model=model,
        force_uppercase=force_uppercase,
        captcha_type=captcha_type,
    )
    if hasattr(llm_router, "acompletion"):
        response = await llm_router.acompletion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=32,
        )
    else:
        import litellm

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=32,
        )

    if hasattr(response, "choices") and response.choices:
        raw_content = response.choices[0].message.content or ""
    elif hasattr(response, "content"):
        raw_content = response.content or ""
    else:
        raw_content = str(response)

    clean_result = clean_captcha_text(
        raw_content,
        force_uppercase=force_uppercase,
        captcha_type=captcha_type,
    )
    log.info("captcha_solver.completed", result=clean_result, captcha_type=captcha_type)
    return clean_result
