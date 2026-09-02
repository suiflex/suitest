"""Turn sampled PNG frames into an MP4 a dashboard can play.

Shared by the desktop providers: both `slint-mcp` and `tauri-mcp` record by
screenshotting on a timer, and the encoding step is identical for both. Keeping
one copy means a fix to the ffmpeg invocation — the pixel format, the padding,
the faststart flag — reaches every provider rather than the one whose file
someone happened to open.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

#: Sampling cadence for desktop screen recording, in milliseconds.
VIDEO_INTERVAL_MS = 200
#: Cap on retained frames, so a forgotten `stop_video` cannot exhaust memory.
VIDEO_MAX_FRAMES = 900


def encode_video(frames: list[bytes], interval_ms: int, *, tool: str) -> bytes:
    """PNG frames -> MP4, through ffmpeg on stdin.

    H.264 in an MP4 is what the dashboard's `<video>` element plays. ffmpeg is
    not vendored, so its absence is reported as the missing dependency it is
    rather than as a broken step; `tool` names the step that needs it.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AssertionError(
            f"ffmpeg is not on PATH — `{tool}` needs it to encode the sampled "
            "frames; install it or drop the video steps"
        )
    fps = max(1, round(1000 / interval_ms))
    # Written to a file, not a pipe: the MP4 muxer seeks back to finish its
    # header, so `-f mp4 -` fails with "muxer does not support non seekable
    # output".
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "recording.mp4"
        result = subprocess.run(  # fixed argv, no shell
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "image2pipe",
                "-framerate",
                str(fps),
                "-i",
                "-",
                # yuv420p + even dimensions: what a browser will actually play.
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-movflags",
                "+faststart",
                str(target),
            ],
            input=b"".join(frames),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not target.exists():
            detail = result.stderr.decode(errors="replace").strip()[:400]
            raise AssertionError(f"ffmpeg could not encode the frames: {detail}")
        return target.read_bytes()
