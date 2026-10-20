from suitest_runner.executors.captcha_detector import (
    build_detect_captcha_script,
    has_captcha_hint,
    is_submit_action,
)


def test_has_captcha_hint_matches_selectors_and_actions():
    # Hints in selectors
    assert has_captcha_hint("#captcha")
    assert has_captcha_hint("input[name='captcha']")
    assert has_captcha_hint("#img-captcha")
    assert has_captcha_hint(".g-recaptcha")
    assert has_captcha_hint("#turnstile-widget")
    assert has_captcha_hint("input[name='security_code']")
    assert has_captcha_hint("input[name='verification_code']")
    assert has_captcha_hint("input[placeholder='Kode Keamanan']")

    # Hints in action descriptions
    assert has_captcha_hint("#input-1", "Fill in captcha code")
    assert has_captcha_hint("#btn-submit", "Submit form with recaptcha")

    # Non-captcha selectors
    assert not has_captcha_hint("#email")
    assert not has_captcha_hint("#password")
    assert not has_captcha_hint("input[name='username']")
    assert not has_captcha_hint("#btn-login", "Click login button")
    assert not has_captcha_hint(None, None)


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
