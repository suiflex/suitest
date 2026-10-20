import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_db.models.case import TestStep
from suitest_runner.jobs.run_test_case import (
    _inject_pre_submit_captcha_step,
    _persist_captcha_self_heal,
)


@pytest.mark.asyncio
async def test_persist_captcha_self_heal_upgrades_type_to_solve_captcha():
    mock_session = AsyncMock()
    mock_step = TestStep(
        id="step-1",
        case_id="case-1",
        order=2,
        action="Type into captcha",
        expected="Entered",
        code=json.dumps(
            {"tool": "browser_type", "arguments": {"target": "#captcha", "text": "123"}}
        ),
    )
    mock_session.get.return_value = mock_step

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    upgraded = await _persist_captcha_self_heal(
        factory=mock_factory,
        case_id="case-1",
        step_id="step-1",
        image_selector="#img-captcha",
        input_selector="#captcha",
        refresh_target="#img-captcha",
    )

    assert upgraded is True
    parsed = json.loads(mock_step.code)
    assert parsed["tool"] == "browser_solve_captcha"
    assert parsed["arguments"]["image_selector"] == "#img-captcha"
    assert parsed["arguments"]["input_selector"] == "#captcha"
    assert parsed["arguments"]["max_retries"] == 3
    assert parsed["arguments"]["refresh_target"] == "#img-captcha"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_inject_pre_submit_captcha_step_inserts_and_reindexes():
    mock_session = AsyncMock()
    step_nav = TestStep(id="s1", case_id="c1", order=1, action="Nav", expected="ok", code="{}")
    step_submit = TestStep(
        id="s2", case_id="c1", order=2, action="Submit", expected="ok", code="{}"
    )
    step_assert = TestStep(
        id="s3", case_id="c1", order=3, action="Assert", expected="ok", code="{}"
    )

    # Mock execute/scalars for selecting all steps
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [step_nav, step_submit, step_assert]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    injected = await _inject_pre_submit_captcha_step(
        factory=mock_factory,
        case_id="c1",
        submit_step_order=2,
        image_selector="#img-captcha",
        input_selector="#captcha",
        refresh_target="#img-captcha",
    )

    assert injected is True
    # The submit step should now be shifted to order 3
    assert step_submit.order == 3
    # The assert step should now be shifted to order 4
    assert step_assert.order == 4
    # session.add should have been called for the new step
    assert mock_session.add.call_count == 1
    new_step = mock_session.add.call_args[0][0]
    assert new_step.order == 2
    assert "browser_solve_captcha" in new_step.code
    mock_session.commit.assert_awaited_once()
