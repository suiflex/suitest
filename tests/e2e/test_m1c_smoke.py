"""M1c DoD smoke E2E (plan §Task 22).

Closes the loop on the M1c runner + MCP runtime by driving a full create →
run → stream → assert artifacts cycle against the live docker-compose stack:

1. Seed a workspace + project + suite + case with five ``playwright-mcp``
   steps that drive the bundled ``e2e-nginx`` test page (see
   ``tests/e2e/fixtures/test-page/index.html``).
2. ``POST /api/v1/runs`` to enqueue the run.
3. Connect to ``GET /ws?token=...`` and subscribe to ``run:<id>``.
4. Collect server events until ``run.completed`` (timeout 120s).
5. Assert the event sequence — 1 ``run.started`` + 5x ``run.step.started``
   + 5x ``run.step.completed`` + 1 ``run.completed`` — with a final PASS
   verdict + ``totalSteps`` / ``passedSteps`` == 5.
6. List run artifacts via ``GET /api/v1/runs/:id/artifacts``, confirm at
   least one ``SCREENSHOT`` row was uploaded, and resolve a signed URL via
   ``GET /api/v1/runs/:id/artifacts/:artifact_id``.

The whole suite is marked ``@pytest.mark.e2e`` so it is **skipped** by the
default ``pytest -m "not e2e"`` selector. The ``.github/workflows/m1c-e2e.yml``
job opts in explicitly after bringing up the compose stack.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


# Hard cap on total wait — generous because the runner cold-boots Playwright
# the first time it touches the page.
_RUN_TIMEOUT_SECONDS = 120.0

# Expected event distribution. ``run.step.log`` frames are not asserted (they
# arrive interleaved + their count depends on Playwright verbosity); we only
# pin the lifecycle events that bracket the run.
_EXPECTED_STEPS = 5


async def test_full_run_lifecycle(
    api_client: AsyncClient,
    ws_base_url: str,
    auth_token: str,
    seeded_case: dict[str, str],
) -> None:
    """Create-run → WS subscribe → assert events → assert artifacts cycle."""
    # Late import: httpx-ws is an E2E-only dep and may be missing during a
    # plain ``pytest -m "not e2e"`` collection. Importing inside the test
    # body keeps that collection clean.
    from httpx_ws import aconnect_ws

    case_id = seeded_case["case_id"]
    project_id = seeded_case["project_id"]

    # --- 1. Enqueue the run -------------------------------------------------
    resp = await api_client.post(
        "/api/v1/runs",
        json={
            "projectId": project_id,
            "name": "E2E smoke",
            "selection": [{"caseId": case_id}],
        },
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    # --- 2. Subscribe to the run room over WS + drain until completed ------
    events: list[dict[str, object]] = []
    ws_url = f"{ws_base_url}/ws?token={auth_token}"

    async def _collect() -> None:
        async with aconnect_ws(ws_url) as ws:
            await ws.send_text(json.dumps({"action": "subscribe", "topic": f"run:{run_id}"}))
            while True:
                raw = await ws.receive_text()
                frame = json.loads(raw)
                # Drop heartbeats / acks / pongs — only run events are asserted.
                if frame.get("type") != "event":
                    continue
                events.append(frame)
                if frame.get("event") == "run.completed":
                    return

    await asyncio.wait_for(_collect(), timeout=_RUN_TIMEOUT_SECONDS)

    # --- 3. Assert the event sequence + final verdict ----------------------
    kinds = [e.get("event") for e in events]
    assert "run.started" in kinds, kinds
    assert kinds.count("run.step.started") == _EXPECTED_STEPS, kinds
    assert kinds.count("run.step.completed") == _EXPECTED_STEPS, kinds
    assert kinds[-1] == "run.completed", kinds

    final = events[-1].get("payload")
    assert isinstance(final, dict), final
    assert final.get("status") == "PASS", final
    assert final.get("totalSteps") == _EXPECTED_STEPS, final
    assert final.get("passedSteps") == _EXPECTED_STEPS, final

    # --- 4. Artifacts uploaded + signed URL resolves -----------------------
    arts_resp = await api_client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert arts_resp.status_code == 200, arts_resp.text
    artifacts = arts_resp.json()
    screenshots = [a for a in artifacts if a.get("kind") == "SCREENSHOT"]
    assert screenshots, f"expected at least one SCREENSHOT artifact, got {artifacts}"

    signed_resp = await api_client.get(f"/api/v1/runs/{run_id}/artifacts/{screenshots[0]['id']}")
    assert signed_resp.status_code == 200, signed_resp.text
    signed_url = signed_resp.json().get("url")
    assert isinstance(signed_url, str), signed_url
    assert signed_url.startswith(("http://", "https://")), signed_url
