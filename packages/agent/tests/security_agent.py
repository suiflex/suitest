"""SecurityAgent — example plugin for penetration-testing flows (M8-2).

Registers under name ``security-agent``.  Requires CLOUD tier because it uses
a capable reasoning model.  Focuses on injection, auth bypass, and sensitive
data exposure.

To activate, ship the class in an installed package and declare the entry point::

    [project.entry-points."suitest.plugins"]
    security-agent = "my_package.security_agent:SecurityAgent"
"""

from __future__ import annotations

from suitest_agent.plugin_sdk.base import AgentPluginBase, AgentPluginSpec


class SecurityAgent(AgentPluginBase):
    """Pentesting-focused agent — injection, auth bypass, sensitive data exposure."""

    spec = AgentPluginSpec(
        name="security-agent",
        version="1.0.0",
        display_name="Security Agent",
        description=(
            "Automated pentesting agent that probes endpoints for injection "
            "vulnerabilities (SQLi, XSS, command injection), authentication "
            "bypass patterns, and unintended sensitive data exposure."
        ),
        system_prompt=(
            "You are a security-focused testing agent with expertise in web application "
            "penetration testing. Your goal is to identify vulnerabilities in the target "
            "system by probing for:\n"
            "1. Injection flaws — SQL injection, XSS, command injection, LDAP injection.\n"
            "2. Authentication and session bypass — brute force, token prediction, "
            "   missing auth checks, insecure direct object references (IDOR).\n"
            "3. Sensitive data exposure — PII in error messages, unprotected endpoints, "
            "   verbose server headers, debug information leakage.\n"
            "For each finding, report: (a) the vulnerability class (OWASP Top 10), "
            "(b) the payload or technique used, (c) severity (CRITICAL/HIGH/MEDIUM/LOW), "
            "and (d) a remediation recommendation. Use only the allowed tools."
        ),
        tool_whitelist=[
            "api_http_mcp.call",
            "playwright_mcp.navigate",
            "playwright_mcp.fill",
        ],
        model_preference="claude-sonnet-4-6",
        target_kind_filter=["BE_REST", "BE_GRAPHQL", "FE_WEB"],
        requires_tier="CLOUD",
        author="Suitest OSS contributors",
        homepage="https://github.com/suiflex/suitest",
    )

    async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
        """Return security-specific context for the given test step."""
        return {
            "agent_role": "security-tester",
            "test_case_id": test_case_id,
            "step_index": step_index,
            "instructions": (
                "Focus on security boundaries at this step. "
                "Attempt common payloads appropriate to the target type."
            ),
        }
