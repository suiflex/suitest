"""The generated frontend test must inline the ffmpeg leading-blank trimmer.

The helper lives inside a template string (generated TCxxx.py files are
standalone — no runtime import of suitest_lifecycle), so it can't be imported
and exercised directly. We assert the rendered template wires it correctly:
graceful ffmpeg guard, and the trim applied to the collected video path.
"""

from __future__ import annotations

from suitest_lifecycle.exporters.frontend import _HEADER, _RUNNER


def test_header_defines_trimmer_with_optional_ffmpeg_guard() -> None:
    assert "def _trim_leading_blank(src):" in _HEADER
    # ffmpeg is optional — absence must be a no-op, not a crash.
    assert 'shutil.which("ffmpeg") is None' in _HEADER
    assert "return src" in _HEADER


def test_runner_trims_the_collected_video() -> None:
    assert "_video = _trim_leading_blank(_video)" in _RUNNER
    assert '"video": _video,' in _RUNNER
