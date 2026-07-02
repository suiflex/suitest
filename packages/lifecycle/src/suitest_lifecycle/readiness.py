"""Readiness detection — never run tests against a server that isn't up.

Strategies, tried in order until one succeeds within the timeout:
  1. HTTP probe of the ready URL (any < 500 response counts as "alive").
  2. TCP port-open check (fallback when there's no health route).
  3. Ready-log pattern match (when the process emits a known "listening" line).

Returns a :class:`Readiness` verdict with the strategy that succeeded, or
``ready=False`` with the elapsed time so the caller can mark the run failed and
attach the startup log.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Readiness:
    ready: bool
    strategy: str
    detail: str
    waited_ms: int


def _http_ok(url: str, timeout: float) -> bool:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status) < 500
    except urllib.error.HTTPError as exc:
        return int(exc.code) < 500  # 401/404 still means the server is alive
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError):
        return False


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until_ready(
    ready_url: str,
    host: str,
    port: int,
    timeout_sec: int,
    *,
    log_reader: Callable[[], str] | None = None,
    ready_log_pattern: str = "",
    poll_interval: float = 0.5,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Readiness:
    """Block until the target is ready or the timeout elapses."""
    start = monotonic()
    deadline = start + timeout_sec
    while monotonic() < deadline:
        if _http_ok(ready_url, timeout=min(5.0, poll_interval * 4)):
            return Readiness(True, "http", f"GET {ready_url} alive", _ms(start, monotonic))
        if _port_open(host, port, timeout=min(2.0, poll_interval * 2)):
            return Readiness(True, "port", f"tcp {host}:{port} open", _ms(start, monotonic))
        if ready_log_pattern and log_reader is not None:
            if ready_log_pattern in log_reader():
                return Readiness(True, "log", f"matched '{ready_log_pattern}'", _ms(start, monotonic))
        sleep(poll_interval)
    return Readiness(False, "timeout", f"not ready after {timeout_sec}s", _ms(start, monotonic))


def _ms(start: float, monotonic: Callable[[], float]) -> int:
    return int((monotonic() - start) * 1000)


__all__ = ["Readiness", "wait_until_ready"]
