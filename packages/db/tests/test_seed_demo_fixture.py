"""Shape-validate the committed Brewly demo suite fixture.

The fixture is a real AI-generation output committed for the ZERO-tier demo
replay (`make demo`). Every step must be executable at ZERO tier, which means
explicit ``code`` envelopes routed to workspace-registered MCP providers.
DB-level idempotency of the seeder is covered by the demo compose smoke, not
here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind

FIXTURE = Path(__file__).parents[3] / "examples" / "demo-app" / "suite.json"

ALLOWED_PROVIDERS = {"api-mcp", "playwright-mcp"}
PROVIDER_FOR_TARGET = {"BE_REST": "api-mcp", "FE_WEB": "playwright-mcp"}


@pytest.fixture(scope="module")
def suite() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text())
    return data


def test_fixture_has_suite_and_cases(suite: dict[str, Any]) -> None:
    assert suite["suite"].startswith("Brewly")
    assert len(suite["cases"]) >= 4


def test_every_case_is_valid(suite: dict[str, Any]) -> None:
    for case in suite["cases"]:
        assert CaseSource(case["source"]) is CaseSource.AI
        assert CaseStatus(case["status"]) is CaseStatus.ACTIVE
        Priority(case["priority"])
        assert TargetKind(case["target_kind"]).value in PROVIDER_FOR_TARGET
        assert case["mcp_provider"] == PROVIDER_FOR_TARGET[case["target_kind"]]
        assert case["steps"], f"case {case['name']!r} has no steps"


def test_every_step_is_zero_tier_executable(suite: dict[str, Any]) -> None:
    for case in suite["cases"]:
        orders = [s["order"] for s in case["steps"]]
        assert orders == list(range(len(orders))), f"non-sequential orders in {case['name']!r}"
        for step in case["steps"]:
            assert step["action"] and step["expected"]
            code = step["code"]
            assert isinstance(code, dict) and code.get("tool"), (
                f"step {step['order']} of {case['name']!r} lacks a code envelope"
            )
            for assertion in code.get("assertions", []):
                assert assertion.get("tool"), f"assertion without tool in {case['name']!r}"


def test_urls_use_demo_app_placeholder(suite: dict[str, Any]) -> None:
    for case in suite["cases"]:
        for step in case["steps"]:
            url = step["code"].get("arguments", {}).get("url")
            if url is not None:
                assert url.startswith("${DEMO_APP_URL}"), f"hardcoded URL in {case['name']!r}"
