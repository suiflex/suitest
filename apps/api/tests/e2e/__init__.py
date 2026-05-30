"""End-to-end test suite for the api package (M1d-29).

The single test module here (:mod:`test_auto_defect_e2e`) drives the full
runner → categorizer → DefectAutoFiler → external-issue + Slack jobs chain
against a testcontainer Postgres + Alembic head. Marked ``@pytest.mark.e2e``
so it stays out of the default ``pytest -m "not e2e"`` selector; CI opts in
explicitly via the ``m1d-e2e`` job (see ``.github/workflows/ci.yml``).

Not a barrel — no re-exports. Tests import directly from
:mod:`test_auto_defect_e2e`.
"""
