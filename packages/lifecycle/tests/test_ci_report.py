from suitest_lifecycle.ci_report import COMMENT_MARKER, render_pr_comment


def _cases():
    return [
        {"title": "login-flow", "status": "PASS", "evidence_url": "https://app/runs/R-1004"},
        {
            "title": "checkout",
            "status": "FAIL",
            "evidence_url": "",
            "failure_excerpt": "TimeoutError step 4: #submit-btn",
        },
    ]


def test_comment_contains_marker_summary_and_table() -> None:
    md = render_pr_comment(
        cases=_cases(),
        passed=1,
        failed=1,
        duration_ms=42_000,
        dashboard_url="https://app/runs/R-1004",
    )
    assert COMMENT_MARKER in md  # kunci upsert lintas forge
    assert "1/2 passed" in md
    assert "| login-flow | ✅" in md
    assert "| checkout | ❌" in md
    assert "TimeoutError step 4" in md  # failure excerpt ikut
    assert "https://app/runs/R-1004" in md


def test_comment_all_green() -> None:
    md = render_pr_comment(
        cases=[{"title": "a", "status": "PASS", "evidence_url": ""}],
        passed=1,
        failed=0,
        duration_ms=1000,
        dashboard_url="",
    )
    assert "1/1 passed" in md and "❌" not in md


def test_comment_without_dashboard_still_renders() -> None:
    # CI murni tanpa server: tidak ada link — comment tetap utuh
    md = render_pr_comment(cases=_cases(), passed=1, failed=1, duration_ms=None, dashboard_url="")
    assert COMMENT_MARKER in md
