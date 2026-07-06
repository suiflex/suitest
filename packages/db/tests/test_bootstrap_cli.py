"""``python -m suitest_db.bootstrap`` creates the local schema from env."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_module_cli_creates_sqlite_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "suitest.db"
    env = {
        **os.environ,
        "SUITEST_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
    }
    result = subprocess.run(
        [sys.executable, "-m", "suitest_db.bootstrap"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "runs" in tables
    assert len(tables) > 30


def test_module_cli_fails_cleanly_without_env() -> None:
    env = {k: v for k, v in os.environ.items() if k != "SUITEST_DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "suitest_db.bootstrap"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "SUITEST_DATABASE_URL" in result.stderr


def test_module_cli_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "suitest.db"
    env = {**os.environ, "SUITEST_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "suitest_db.bootstrap"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
