"""Unit tests for multimodal Vision CAPTCHA solver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_agent.generators.captcha_solver import clean_captcha_text, solve_captcha_image


def test_clean_captcha_text_raw_alphanumeric() -> None:
    assert clean_captcha_text("PRINGSEWU") == "PRINGSEWU"
    assert clean_captcha_text("  7K9mQ  ") == "7K9mQ"


def test_clean_captcha_text_strips_chat_boilerplate() -> None:
    assert clean_captcha_text("The captcha code is: PRINGSEWU") == "PRINGSEWU"
    assert clean_captcha_text("The code in the image is PRINGSEWU.") == "PRINGSEWU"
    assert clean_captcha_text("Captcha: 4B8X9") == "4B8X9"
    assert clean_captcha_text("**PRINGSEWU**") == "PRINGSEWU"


def test_clean_captcha_text_force_uppercase() -> None:
    assert clean_captcha_text("pringsewu", force_uppercase=True) == "PRINGSEWU"
    assert clean_captcha_text("aB3cD", force_uppercase=False) == "aB3cD"
    assert clean_captcha_text("aB3cD", force_uppercase=True) == "AB3CD"


@pytest.mark.asyncio
async def test_solve_captcha_image_mocked_llm() -> None:
    fake_router = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "PRINGSEWU"
    mock_resp = MagicMock(choices=[mock_choice])
    fake_router.acompletion = AsyncMock(return_value=mock_resp)

    sample_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG header dummy
    result = await solve_captcha_image(
        sample_bytes,
        llm_router=fake_router,
        model="gpt-4o-mini",
        force_uppercase=True,
    )

    assert result == "PRINGSEWU"
    fake_router.acompletion.assert_called_once()
    call_kwargs = fake_router.acompletion.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["temperature"] == 0.0

    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    assert any(
        item.get("type") == "image_url" and "data:image/png;base64," in item["image_url"]["url"]
        for item in user_content
    )


def test_clean_captcha_text_math() -> None:
    assert clean_captcha_text("The answer is 12", captcha_type="math") == "12"
    assert clean_captcha_text("Result: 8", captcha_type="math") == "8"
    assert clean_captcha_text("The math result is -5", captcha_type="math") == "-5"


def test_clean_captcha_text_numeric() -> None:
    assert clean_captcha_text("Code: 981240", captcha_type="numeric") == "981240"
    assert clean_captcha_text("AB 492 X", captcha_type="numeric") == "492"


def test_clean_captcha_text_auto_clear_word() -> None:
    assert clean_captcha_text("PRINGSEWU", captcha_type="auto") == "PRINGSEWU"
    assert clean_captcha_text("The code is: PRINGSEWU", captcha_type="auto") == "PRINGSEWU"


@pytest.mark.asyncio
async def test_solve_captcha_image_with_captcha_type() -> None:
    router = MagicMock()
    choice = MagicMock()
    choice.message.content = "15"
    mock_response = MagicMock(choices=[choice])
    router.acompletion = AsyncMock(return_value=mock_response)

    res = await solve_captcha_image(
        b"dummy_bytes",
        llm_router=router,
        captcha_type="math",
    )
    assert res == "15"
    call_kwargs = router.acompletion.call_args.kwargs
    assert "math" in call_kwargs["messages"][0]["content"].lower()
