"""`python -m suitest_runner` entrypoint."""

from arq.cli import cli


def main() -> None:
    """Delegate to the ARQ CLI."""
    cli.main(["suitest_runner.worker.WorkerSettings"])


if __name__ == "__main__":
    main()
