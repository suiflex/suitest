from __future__ import annotations

from suitest_lifecycle.tools import _prune_redundant_step_toggles


def test_prune_redundant_step_toggles_removes_immediate_duplicate_clicks():
    steps = [
        {
            "action": "Click Nav",
            "code": {"tool": "browser_click", "arguments": {"target": "#accordion-btn"}},
        },
        {
            "action": "Click Nav Duplicate",
            "code": {"tool": "browser_click", "arguments": {"target": "#accordion-btn"}},
        },
        {
            "action": "Click Sub-Item",
            "code": {"tool": "browser_click", "arguments": {"target": "#sub-item-1"}},
        },
    ]
    cleaned = _prune_redundant_step_toggles(steps)
    assert len(cleaned) == 2
    assert cleaned[0]["code"]["arguments"]["target"] == "#accordion-btn"
    assert cleaned[1]["code"]["arguments"]["target"] == "#sub-item-1"


def test_prune_redundant_step_toggles_handles_selector_argument_and_mixed():
    steps = [
        {
            "action": "Click Nav",
            "code": {"tool": "browser_click", "arguments": {"selector": "#accordion-btn"}},
        },
        {
            "action": "Click Nav Duplicate Target",
            "code": {"tool": "browser.click", "arguments": {"target": "#accordion-btn"}},
        },
        {
            "action": "Click Sub-Item",
            "code": {"tool": "browser_click", "arguments": {"selector": "#sub-item-1"}},
        },
    ]
    cleaned = _prune_redundant_step_toggles(steps)
    assert len(cleaned) == 2
    assert cleaned[0]["action"] == "Click Nav"
    assert cleaned[1]["action"] == "Click Sub-Item"


def test_prune_redundant_step_toggles_safely_handles_non_json_and_non_dict_code():
    steps = [
        {"action": "Raw step 1", "code": ""},
        {"action": "Raw step 2", "code": "page.click('#btn')"},
        {"action": "List step", "code": "[1, 2, 3]"},
        {"action": "None step", "code": None},
    ]
    cleaned = _prune_redundant_step_toggles(steps)
    assert len(cleaned) == 4


def test_prune_redundant_step_toggles_preserves_consecutive_clicks_on_non_toggles():
    steps = [
        {
            "action": "Click Increment 1",
            "code": {"tool": "browser_click", "arguments": {"target": "button#increment"}},
        },
        {
            "action": "Click Increment 2",
            "code": {"tool": "browser_click", "arguments": {"target": "button#increment"}},
        },
        {
            "action": "Click Add to Cart 1",
            "code": {"tool": "browser.click", "arguments": {"target": ".btn-add-item"}},
        },
        {
            "action": "Click Add to Cart 2",
            "code": {"tool": "browser.click", "arguments": {"target": ".btn-add-item"}},
        },
    ]
    cleaned = _prune_redundant_step_toggles(steps)
    # None of these are proven toggles; all 4 clicks must be preserved!
    assert len(cleaned) == 4


def test_prune_redundant_step_toggles_reindexes_order_and_handles_odd_click_counts():
    steps = [
        {
            "order": 1,
            "action": "Open FAQ",
            "code": {"tool": "browser_click", "arguments": {"target": ".accordion-button"}},
        },
        {
            "order": 2,
            "action": "Accidental double-click FAQ",
            "code": {"tool": "browser_click", "arguments": {"target": ".accordion-button"}},
        },
        {
            "order": 3,
            "action": "Intentional re-open FAQ",
            "code": {"tool": "browser_click", "arguments": {"target": ".accordion-button"}},
        },
        {
            "order": 4,
            "action": "Click sub content",
            "code": {"tool": "browser_click", "arguments": {"target": "#faq-content"}},
        },
    ]
    cleaned = _prune_redundant_step_toggles(steps)
    # Step 2 pruned; Step 1, 3, 4 retained and re-indexed to 1, 2, 3
    assert len(cleaned) == 3
    assert cleaned[0]["order"] == 1
    assert cleaned[0]["action"] == "Open FAQ"
    assert cleaned[1]["order"] == 2
    assert cleaned[1]["action"] == "Intentional re-open FAQ"
    assert cleaned[2]["order"] == 3
    assert cleaned[2]["action"] == "Click sub content"


def test_create_test_case_replaces_password_with_secret_reference_in_mirror(tmp_path):
    from unittest.mock import MagicMock, patch

    from suitest_lifecycle.tools import create_test_case

    mock_client = MagicMock()
    mock_client.resolve_project.return_value = {"id": "proj_sec", "slug": "sec"}
    mock_client.list_suites.return_value = [{"id": "suite_sec_1"}]
    mock_client.create_case.return_value = {"id": "case_1", "public_id": "TC-SEC-1"}

    steps = [
        {
            "action": "Type Password",
            "code": {
                "tool": "browser_type",
                "arguments": {"target": "input#password", "text": "SuperSecretPassword123!"},
            },
        }
    ]

    with (
        patch.dict(
            "os.environ", {"SUITEST_API_URL": "http://mock:8000", "SUITEST_API_KEY": "sk_mock"}
        ),
        patch("suitest_lifecycle.http_client.SuitestClient") as mock_cls,
    ):
        mock_cls.return_value.__enter__.return_value = mock_client
        res = create_test_case(
            name="Sensitive Input Test",
            steps=steps,
            output_dir=str(tmp_path),
            target_url="http://sec.app.test",
        )

    assert res["success"] is True
    artifacts = res.get("artifacts") or []
    assert len(artifacts) == 1
    code = (tmp_path / "TC_sensitive_input_test.py").read_text(encoding="utf-8")
    assert "SuperSecretPassword123!" not in code
    assert "{{password}}" in code

    # Check TCM payload also used {{password}}
    tcm_steps = mock_client.create_case.call_args[0][0]["steps"]
    assert "SuperSecretPassword123!" not in tcm_steps[0]["code"]
    assert "{{password}}" in tcm_steps[0]["code"]


def test_create_test_case_extracts_target_url_from_steps(tmp_path):
    from unittest.mock import MagicMock, patch

    from suitest_lifecycle.tools import create_test_case

    mock_client = MagicMock()
    mock_client.resolve_project.return_value = {"id": "proj_extracted", "slug": "my-company-com"}
    mock_client.list_suites.return_value = [{"id": "suite_extracted_1"}]
    mock_client.create_case.return_value = {"id": "case_1", "public_id": "TC-EXT-1"}

    steps = [
        {
            "action": "Open portal",
            "code": {
                "tool": "browser_navigate",
                "arguments": {"url": "https://my-company.com/portal/login"},
            },
        }
    ]

    with (
        patch.dict(
            "os.environ", {"SUITEST_API_URL": "http://mock:8000", "SUITEST_API_KEY": "sk_mock"}
        ),
        patch("suitest_lifecycle.http_client.SuitestClient") as mock_cls,
    ):
        mock_cls.return_value.__enter__.return_value = mock_client
        res = create_test_case(
            name="Extracted Target Case",
            steps=steps,
            output_dir=str(tmp_path),
        )

    assert res["success"] is True
    mock_client.resolve_project.assert_called_once_with(
        project_slug="my-company-com",
        project_name="my-company.com",
    )
