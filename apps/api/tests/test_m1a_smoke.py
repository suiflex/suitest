"""M1a DoD smoke E2E (plan §Task 13).

Single happy-path test proving an authenticated user can browse the seeded
Nusantara Retail workspace end to end via every M1a read endpoint. Bound to the
``v0.2.0-m1a`` milestone tag.

Auth flow note
--------------
The plan offers two routes for "login as Maya":

* **Real FastAPI-Users cookie login.** ``POST /auth/cookie/login`` with the
  seeded password works in principle, but it requires the test client to
  share a session pool with the auth backend so the issued ``suitest_session``
  cookie can be replayed on subsequent requests. The Task 7 pattern (used by
  every other endpoint test) sidesteps that plumbing by overriding
  ``current_active_user`` directly via ``api_db.client(user)``. That same
  override is what ``test_seed_e2e`` uses, and it is the documented fallback
  in the plan.

* **Dependency override** — what we use here. Loads Maya from the seed by
  email and passes her into ``api_db.client(maya)``, which wires the override
  exactly like the production auth dep would after a successful cookie login.
  All membership / scope / capability code paths still execute end-to-end.

Twenty sequential assertions follow, each blocking the next: capability tier,
workspace listing, project listing, suites, cases + steps, runs + steps,
defects + timeline, requirements + matrix, integrations, documents, and the
three analytics endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import select
from suitest_db.models.user import User
from suitest_db.models.workspace import Workspace
from suitest_db.seed import PROJECT_SLUG, WORKSPACE_SLUG, Seeder

if TYPE_CHECKING:
    from api_harness import ApiDb

# Email actually written by the seeder (Task 9). Plan-spec said ``maya@suitest.io``
# but the implemented seed uses the Nusantara local domain.
_MAYA_EMAIL = "maya@nusantararetail.local"


@pytest.mark.asyncio
async def test_m1a_dod_smoke_e2e(api_db: ApiDb) -> None:
    """Drive every M1a GET endpoint as Maya against the seeded workspace."""
    # --- bootstrap: seed the testcontainer DB + look up Maya + the workspace ---
    async with api_db.maker() as session:
        await Seeder(session).run_all()
        await session.commit()

    async with api_db.maker() as session:
        email_col = User.__table__.c.email
        maya = await session.scalar(select(User).where(email_col == _MAYA_EMAIL))
        assert maya is not None, "seed must produce Maya"
        ws_row = await session.scalar(select(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
        assert ws_row is not None, "seed must produce the Nusantara Retail workspace"
        # Detach: the override opens its own session and would re-attach a closed row.
        maya_user = maya
        seeded_ws_id = ws_row.id

    async with api_db.client(maya_user) as c:
        # --- (1) GET /capabilities — base tier is ZERO, default autonomy MANUAL --
        resp = await c.get("/capabilities")
        assert resp.status_code == 200, resp.text
        caps = resp.json()
        assert caps["tier"] == "ZERO"
        assert caps["autonomy"]["default"] == "manual"

        # --- (2) GET /auth/me — email matches Maya, membership in Nusantara w/ OWNER
        resp = await c.get("/api/v1/auth/me")
        assert resp.status_code == 200, resp.text
        me = resp.json()
        assert me["email"] == _MAYA_EMAIL
        nusantara = next(
            (m for m in me["memberships"] if m["workspace"]["slug"] == WORKSPACE_SLUG),
            None,
        )
        assert nusantara is not None, "Maya must be a member of Nusantara Retail"
        assert nusantara["role"] == "OWNER"

        # --- (3) GET /workspaces — exactly 1, slug nusantara-retail. Capture id. ---
        resp = await c.get("/api/v1/workspaces")
        assert resp.status_code == 200, resp.text
        workspaces = resp.json()
        assert isinstance(workspaces, list)
        assert len(workspaces) == 1
        assert workspaces[0]["slug"] == WORKSPACE_SLUG
        workspace_id = cast("str", workspaces[0]["id"])
        assert workspace_id == seeded_ws_id

        # --- (4) X-Workspace-Id header used for the rest of the trace --------
        headers = {"X-Workspace-Id": workspace_id}

        # --- (5) GET /projects — exactly 1 (E-commerce Web). Capture project.id.
        resp = await c.get("/api/v1/projects", headers=headers)
        assert resp.status_code == 200, resp.text
        projects_page = resp.json()
        assert len(projects_page["items"]) == 1
        assert projects_page["items"][0]["slug"] == PROJECT_SLUG
        project_id = cast("str", projects_page["items"][0]["id"])

        # --- (6) GET /suites?projectId=... → 4 suites -----------------------
        resp = await c.get(f"/api/v1/suites?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        suites = resp.json()
        assert isinstance(suites, list)
        assert len(suites) == 4
        first_suite_id = cast("str", suites[0]["id"])

        # --- (7) GET /test-cases?suiteId=... → ≥1 case. Capture case.id. ---
        resp = await c.get(f"/api/v1/test-cases?suiteId={first_suite_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        cases_page = resp.json()
        assert len(cases_page["items"]) >= 1
        case_id = cast("str", cases_page["items"][0]["id"])

        # --- (8) GET /test-cases/<case_id> → includes ≥1 step --------------
        resp = await c.get(f"/api/v1/test-cases/{case_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        case_detail = resp.json()
        assert len(case_detail["steps"]) >= 1

        # --- (9) GET /runs?projectId=... → 5 runs --------------------------
        resp = await c.get(f"/api/v1/runs?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        runs_page = resp.json()
        assert len(runs_page["items"]) == 5
        first_run_id = cast("str", runs_page["items"][0]["id"])

        # --- (10) GET /runs/<id> → summary fields present ------------------
        resp = await c.get(f"/api/v1/runs/{first_run_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        run_detail = resp.json()
        summary = run_detail["summary"]
        for key in ("total_steps", "passed_steps", "failed_steps"):
            assert key in summary, f"run summary missing {key}"

        # --- (11) GET /runs/<id>/steps → ≥1 RunStep ------------------------
        resp = await c.get(f"/api/v1/runs/{first_run_id}/steps", headers=headers)
        assert resp.status_code == 200, resp.text
        run_steps = resp.json()
        assert isinstance(run_steps, list)
        assert len(run_steps) >= 1

        # --- (12) GET /defects → 3 defects ---------------------------------
        resp = await c.get("/api/v1/defects", headers=headers)
        assert resp.status_code == 200, resp.text
        defects_page = resp.json()
        assert len(defects_page["items"]) == 3
        first_defect_id = cast("str", defects_page["items"][0]["id"])

        # --- (13) GET /defects/<id>/timeline → ≥1 entry --------------------
        resp = await c.get(f"/api/v1/defects/{first_defect_id}/timeline", headers=headers)
        assert resp.status_code == 200, resp.text
        timeline = resp.json()
        assert isinstance(timeline, list)
        assert len(timeline) >= 1

        # --- (14) GET /requirements?projectId=... → 6 ----------------------
        resp = await c.get(f"/api/v1/requirements?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        requirements_page = resp.json()
        assert len(requirements_page["items"]) == 6

        # --- (15) GET /traceability/matrix?projectId=... → 3 top-level keys -
        resp = await c.get(f"/api/v1/traceability/matrix?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        matrix = resp.json()
        assert set(matrix.keys()) == {"requirements", "cases", "defects"}

        # --- (16) GET /integrations → 9 ------------------------------------
        resp = await c.get("/api/v1/integrations", headers=headers)
        assert resp.status_code == 200, resp.text
        integrations = resp.json()
        assert isinstance(integrations, list)
        assert len(integrations) == 9

        # --- (17) GET /documents → 0 (seed has no documents) ---------------
        resp = await c.get("/api/v1/documents", headers=headers)
        assert resp.status_code == 200, resp.text
        documents_page = resp.json()
        assert len(documents_page["items"]) == 0

        # --- (18) GET /analytics/kpis → numeric passRate -------------------
        resp = await c.get(
            f"/api/v1/analytics/kpis?projectId={project_id}&period=7d",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        kpis = resp.json()
        assert isinstance(kpis["passRate"], int | float)

        # --- (19) GET /analytics/flaky → list (may be empty) ---------------
        resp = await c.get(f"/api/v1/analytics/flaky?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        flaky = resp.json()
        assert isinstance(flaky, list)

        # --- (20) GET /analytics/readiness → score 0..100 -----------------
        resp = await c.get(f"/api/v1/analytics/readiness?projectId={project_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        readiness = resp.json()
        score = readiness["score"]
        assert isinstance(score, int)
        assert 0 <= score <= 100
