"""``python -m suitest_runner`` entrypoint — boots ARQ against ``WorkerSettings``.

ARQ types ``run_worker`` against :class:`arq.typing.WorkerSettingsBase`, a
Protocol whose ``on_startup`` / ``on_shutdown`` slots accept the
``StartupShutdown`` Protocol (``dict[Any, Any]``). Our hooks tighten the ctx
type to ``dict[str, object]`` per CLAUDE.md's "no Any" rule, so mypy strict
flags the assignment. ARQ accepts any class with the right attributes at
runtime — the dict argument is built by ARQ itself and passed through — so we
cast through ``type[WorkerSettingsBase]`` for the type checker only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from arq.worker import run_worker

from suitest_runner.worker import WorkerSettings

if TYPE_CHECKING:
    from arq.typing import WorkerSettingsBase


def main() -> None:
    """Run the ARQ worker until SIGINT / SIGTERM."""
    run_worker(cast("type[WorkerSettingsBase]", WorkerSettings))


if __name__ == "__main__":
    main()
