"""Universal variable resolver for step execution and DDT runs.

Hierarchy resolution:
1. Case dataset row values (current iteration row: e.g. row["values"][key])
2. Suite variables (override workspace variables for a specific test suite)
3. Workspace variables (workspace-level defaults)
4. Environment variables (os.environ fallback)

Syntax supported:
- {{variable_name}}
- ${variable_name} (optional compatibility)
"""

from __future__ import annotations

import os
import re
from typing import Any

_VAR_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_.-]+)\}\}|\$\{([a-zA-Z0-9_.-]+)\}")


class VariableResolver:
    """Resolves template variables across datasets, suites, workspaces, and environment."""

    def __init__(
        self,
        *,
        dataset_row: dict[str, Any] | None = None,
        suite_variables: dict[str, str] | None = None,
        workspace_variables: dict[str, str] | None = None,
        env_fallback: bool = True,
    ) -> None:
        self.dataset_row = dataset_row or {}
        self.suite_variables = suite_variables or {}
        self.workspace_variables = workspace_variables or {}
        self.env_fallback = env_fallback

    def get(self, key: str) -> str | None:
        """Resolve a variable by key across the hierarchy."""
        # 1. Dataset row
        if isinstance(self.dataset_row, dict):
            # Check values nested dict (standard dataset row structure: {"name": "Admin", "values": {...}})
            values = self.dataset_row.get("values")
            if isinstance(values, dict) and key in values:
                val = values[key]
                return str(val) if val is not None else ""
            if key in self.dataset_row and key not in (
                "values",
                "id",
                "name",
                "description",
                "enabled",
            ):
                val = self.dataset_row[key]
                return str(val) if val is not None else ""

        # 2. Suite variables
        if key in self.suite_variables:
            val = self.suite_variables[key]
            return str(val) if val is not None else ""

        # 3. Workspace variables
        if key in self.workspace_variables:
            val = self.workspace_variables[key]
            return str(val) if val is not None else ""

        # 4. Env fallback
        if self.env_fallback and key in os.environ:
            return os.environ[key]

        return None

    def interpolate_string(self, text: str) -> str:
        """Replace {{key}} or ${key} with resolved values.

        Unresolved placeholders remain unchanged.
        """
        if not text or not isinstance(text, str):
            return text

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1) or match.group(2)
            resolved = self.get(key)
            if resolved is not None:
                return resolved
            return match.group(0)

        return _VAR_PATTERN.sub(_replace, text)

    def interpolate_data(self, data: Any) -> Any:
        """Recursively interpolate dicts, lists, and strings."""
        if isinstance(data, str):
            return self.interpolate_string(data)
        if isinstance(data, dict):
            return {k: self.interpolate_data(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.interpolate_data(item) for item in data]
        return data
