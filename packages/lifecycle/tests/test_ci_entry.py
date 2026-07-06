from suitest_lifecycle.ci import build_comment_from_run, exit_code_for


def test_exit_codes() -> None:
    assert exit_code_for(failed=0, infra_error=False) == 0
    assert exit_code_for(failed=2, infra_error=False) == 1  # test gagal -> merge gate
    assert exit_code_for(failed=0, infra_error=True) == 2  # infra != test failure


def test_build_comment_from_run_summary() -> None:
    summary = {"total_steps": 10, "passed_steps": 8, "failed_steps": 2, "duration_ms": 30_000}
    cases = [
        {"title": "a", "status": "PASS", "evidence_url": ""},
        {"title": "b", "status": "FAIL", "evidence_url": "", "failure_excerpt": "boom"},
    ]
    md = build_comment_from_run(summary, cases, dashboard_url="")
    assert "8/10 passed" in md and "boom" in md
