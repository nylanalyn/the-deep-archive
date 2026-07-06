"""Shared pytest fixtures for The Deep Archive tests."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from deeparchive.db.connection import connect
from deeparchive.db.migrations import migrate


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[Path]:
    """Path to a fresh, uncreated database file in a temp directory."""
    yield tmp_path / "test.sqlite3"


@pytest.fixture
def migrated_conn(tmp_db: Path):
    """A migrated, ready-to-use connection. Closed automatically at teardown."""
    conn = connect(tmp_db)
    try:
        migrate(conn)
        yield conn
    finally:
        conn.close()
