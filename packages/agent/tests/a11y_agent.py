"""A11yAgent — example plugin for WCAG 2.2 accessibility checks (M8-2).

Registers under name ``a11y-agent``.  Requires LOCAL tier (runs fine on a local
model).  Focuses on ARIA labels, contrast ratios, keyboard navigation, and
WCAG 2.2 compliance.

To activate, ship the class in an installed package and declare the entry point::

    [project.entry-points."suitest.plugins"]
    a11y-agent = "my_package.a11y_agent:A11yAgent"
"""

from __future__ import annotations

from suitest_agent.plugin_sdk.base import AgentPluginBase, AgentPluginSpec


class A11yAgent(AgentPluginBase):
    """Accessibility-focused agent — WCAG 2.2 compliance checks."""

    spec = AgentPluginSpec(
        name="a11y-agent",
        version="1.0.0",
        display_name="Accessibility Agent",
        description=(
            "Automated accessibility agent that checks pages against WCAG 2.2 "
            "criteria including ARIA labels, colour contrast, keyboard navigation, "
            "focus management, and screen-reader compatibility."
        ),
        system_prompt=(
            "You are an accessibility (a11y) testing agent specialising in WCAG 2.2 "
            "compliance. For each page or component under test, evaluate:\n"
            "1. ARIA labels and roles — every interactive element must have an accessible "
            "   name; landmark roles (main, nav, aside) must be present and unique.\n"
            "2. Colour contrast — text contrast ratio must be ≥4.5:1 (normal text) or "
            "   ≥3:1 (large text / UI components) per WCAG 2.2 SC 1.4.3 / 1.4.11.\n"
            "3. Keyboard navigation — all functionality must be reachable via keyboard; "
            "   visible focus indicators must meet SC 2.4.11 (Enhanced Focus Appearance).\n"
            "4. Images and media — non-decorative images need descriptive alt text; "
            "   videos need captions.\n"
            "5. Forms — labels, error suggestions, and status messages must be "
            "   programmatically associated.\n"
            "Report each issue with: WCAG criterion, severity (CRITICAL/MAJOR/MINOR), "
            "affected element (CSS selector or description), and remediation guidance."
        ),
        tool_whitelist=[
            "playwright_mcp.navigate",
            "playwright_mcp.screenshot",
        ],
        model_preference="claude-haiku-4-5-20251001",
        target_kind_filter=["FE_WEB", "FE_MOBILE"],
        requires_tier="LOCAL",
        author="Suitest OSS contributors",
        homepage="https://github.com/suiflex/suitest",
    )

    async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
        """Return accessibility-specific context for the given test step."""
        return {
            "agent_role": "a11y-tester",
            "test_case_id": test_case_id,
            "step_index": step_index,
            "wcag_version": "2.2",
            "conformance_level": "AA",
            "instructions": (
                "Screenshot the current state and analyse it for accessibility issues "
                "at this step. Note any ARIA, contrast, or keyboard concerns."
            ),
        }
