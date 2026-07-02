"""Target server process manager.

Spawns the app-under-test (``server.startCommand``) in its own process group so
the *whole* tree (npm → tsx → node) can be torn down, streams its output to an
in-memory ring buffer for ready-log detection + failure diagnostics, and stops
it gracefully (SIGTERM → SIGKILL). POSIX-focused (the dev target is darwin/linux).
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ManagedProcess:
    popen: subprocess.Popen[bytes]
    _buffer: deque[str]
    _lock: threading.Lock

    def log_text(self) -> str:
        with self._lock:
            return "".join(self._buffer)

    def tail(self, lines: int = 40) -> str:
        text = self.log_text()
        return "\n".join(text.splitlines()[-lines:])

    @property
    def alive(self) -> bool:
        return self.popen.poll() is None

    @property
    def returncode(self) -> int | None:
        return self.popen.poll()


class ProcessManager:
    """Start/stop a single target server."""

    def __init__(self, *, buffer_chars: int = 200_000) -> None:
        self._proc: ManagedProcess | None = None
        self._buffer_chars = buffer_chars
        self._reader: threading.Thread | None = None

    def start(self, command: str, cwd: Path, env: dict[str, str]) -> ManagedProcess:
        full_env = {**os.environ, **env}
        buffer: deque[str] = deque()
        lock = threading.Lock()
        char_count = {"n": 0}

        popen = subprocess.Popen(
            shlex.split(command),
            cwd=str(cwd),
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group for clean teardown
        )
        managed = ManagedProcess(popen=popen, _buffer=buffer, _lock=lock)

        def _drain() -> None:
            stream = popen.stdout
            if stream is None:
                return
            for raw in iter(stream.readline, b""):
                chunk = raw.decode("utf-8", errors="replace")
                with lock:
                    buffer.append(chunk)
                    char_count["n"] += len(chunk)
                    while char_count["n"] > self._buffer_chars and buffer:
                        char_count["n"] -= len(buffer.popleft())

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()
        self._proc = managed
        self._reader = reader
        return managed

    def stop(self, grace_sec: int = 5) -> None:
        if self._proc is None:
            return
        popen = self._proc.popen
        if popen.poll() is None:
            try:
                os.killpg(os.getpgid(popen.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            deadline = time.monotonic() + grace_sec
            while time.monotonic() < deadline and popen.poll() is None:
                time.sleep(0.1)
            if popen.poll() is None:
                try:
                    os.killpg(os.getpgid(popen.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        self._proc = None

    @property
    def current(self) -> ManagedProcess | None:
        return self._proc


__all__ = ["ManagedProcess", "ProcessManager"]
