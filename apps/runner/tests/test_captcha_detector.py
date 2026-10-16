from suitest_runner.executors.captcha_detector import (
    build_detect_captcha_script,
    is_submit_action,
)


def test_is_submit_action_matches_standard_triggers():
    # Submit buttons
    assert is_submit_action("button[type='submit']", "browser_click")
    assert is_submit_action("#btn-submit", "browser_click")
    assert is_submit_action("//button[contains(text(), 'Login')]", "browser_click")
    assert is_submit_action("button:has-text('Masuk')", "browser_click")
    assert is_submit_action("button:has-text('Sign In')", "browser_click")
    assert is_submit_action("input[value='Submit']", "browser_click")

    # Non-submit actions
    assert not is_submit_action("#custom-dropdown-trigger", "browser_click")
    assert not is_submit_action("#tag-corrosive", "browser_click")
    assert not is_submit_action("#input-username", "browser_type")


def test_build_detect_captcha_script_contains_recorder_heuristics():
    script = build_detect_captcha_script(target_input_selector="#captcha")
    assert "isCaptchaField" in script
    assert "findNearestCaptchaImage" in script
    assert "getBoundingClientRect" in script
    assert "#captcha" in script
