"""Loader for the curated model catalog in ``model_catalog.json``.

The table is data, not logic, so it lives beside this module as JSON: the
service that reads it and the router that serves it stay about behaviour, and
the table changes on a vendor's release schedule rather than on ours.

Not exhaustive and not authoritative. A Code Assist account is entitled to a
list of its own, which ``GET /workspaces/:id/llm-config/models`` reads in
preference to this one; the table is what answers when there is no sign-in to
ask, or the ask fails. A provider with no entry is served an empty list and the
UI falls back to a free-text field.

Two entries carry a caveat the JSON cannot:

* ``google-vertex`` ids keep the ``google/`` publisher prefix, because Vertex's
  OpenAI-compatible surface namespaces the model that way.
* ``antigravity`` fronts several vendors and moves between releases, so its rows
  are the fallback the picker shows before an account's own list is read.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Final

from suitest_core.code_assist import ANTIGRAVITY_PROVIDER, CODE_ASSIST_PROVIDER
from suitest_core.llm_credentials import CHATGPT_PROVIDER

_CATALOG_FILE: Final = "model_catalog.json"


def _load() -> dict[str, list[dict[str, object]]]:
    raw = (files(__package__) / _CATALOG_FILE).read_text(encoding="utf-8")
    parsed: dict[str, list[dict[str, object]]] = json.loads(raw)
    # The JSON spells the sign-in provider keys out. Renaming a constant without
    # the file would leave those rows unreachable and the picker silently empty,
    # so the two are checked against each other at import.
    for provider in (CHATGPT_PROVIDER, CODE_ASSIST_PROVIDER, ANTIGRAVITY_PROVIDER):
        if provider not in parsed:
            raise RuntimeError(f"{_CATALOG_FILE} has no entry for provider {provider!r}")
    return parsed


#: Provider key -> the models offered for it, in the order the picker shows them.
MODEL_CATALOG: Final[dict[str, list[dict[str, object]]]] = _load()
