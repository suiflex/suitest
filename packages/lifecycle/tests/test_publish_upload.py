"""Artifact scratch is removed only after blob upload AND result commit."""

from __future__ import annotations

from pathlib import Path

from suitest_lifecycle.models import Mode, StepResult
from suitest_lifecycle.models import TestOutcome as Outcome
from suitest_lifecycle.models import TestResult as Result
from suitest_lifecycle.paths import build_paths
from suitest_lifecycle.publish import _artifact, _cleanup_committed_result, _resolve_url


class _OkUploader:
    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        return f"local://{Path(path).name}"


class _FailUploader:
    def upload_file(self, path: str, *, content_type: str | None = None) -> str:
        raise RuntimeError("network down / S3 unreachable")


def test_successful_upload_waits_for_result_commit_before_delete(tmp_path: Path) -> None:
    f = tmp_path / "run.webm"
    f.write_bytes(b"webm")
    url = _resolve_url(_OkUploader(), str(f), "video/webm")
    assert url == "local://run.webm"
    assert f.exists()  # blob alone can still become orphaned; result has not committed


def test_failed_upload_keeps_local_copy(tmp_path: Path) -> None:
    f = tmp_path / "run.webm"
    f.write_bytes(b"webm")
    url = _resolve_url(_FailUploader(), str(f), "video/webm")
    assert f.exists()  # NOT durable — must survive for the file:// ref
    assert url == f.resolve().as_uri()  # valid file:// URI on every OS


def test_artifact_reports_size_without_premature_delete(tmp_path: Path) -> None:
    f = tmp_path / "shot.png"
    f.write_bytes(b"12345")
    art = _artifact(_OkUploader(), str(f), "SCREENSHOT")
    assert art is not None
    assert art["sizeBytes"] == 5
    assert f.exists()


def test_committed_result_deletes_durable_scratch(tmp_path: Path) -> None:
    paths = build_paths(tmp_path / "out", Mode.FRONTEND)
    paths.ensure()
    video = paths.tmp_dir / "videos" / "TC001" / "run.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    shot = paths.tmp_dir / "TC001_step1.png"
    shot.write_bytes(b"png")
    final = paths.tmp_dir / "TC001_final.png"
    final.write_bytes(b"duplicate")
    result = Result(
        test_id="TC001",
        title="case",
        description="",
        status=Outcome.PASSED,
        duration_ms=1,
        video_path=str(video),
        screenshot_path=str(final),
        steps=[StepResult(1, "action", "open", Outcome.PASSED, screenshot_path=str(shot))],
    )
    payload = {
        "artifacts": [{"url": "local://video"}],
        "steps": [{"screenshot": "local://shot"}],
    }
    _cleanup_committed_result(result, payload, paths)
    assert not video.exists()
    assert not shot.exists()
    assert not final.exists()
