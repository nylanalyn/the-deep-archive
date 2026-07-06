"""Tests for the SQLite connection factory."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from deeparchive.db.connection import connect


class TestConnect:
    def test_creates_missing_directory(self, tmp_path: Path):
        # Parent dir does not exist yet.
        nested = tmp_path / "nested" / "dirs" / "archive.sqlite3"
        conn = connect(nested)
        try:
            assert nested.exists()
        finally:
            conn.close()

    def test_default_pragmas_applied(self, tmp_db: Path):
        conn = connect(tmp_db)
        try:
            # journal_mode returns 'wal' (lowercased by SQLite).
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"

            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1

            busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert busy == 5000
        finally:
            conn.close()

    def test_row_factory_is_row(self, tmp_db: Path):
        conn = connect(tmp_db)
        try:
            conn.execute("CREATE TABLE t (a, b)")
            conn.execute("INSERT INTO t VALUES (1, 2)")
            row = conn.execute("SELECT a, b FROM t").fetchone()
            # sqlite3.Row supports both index and column-name access.
            assert row["a"] == 1
            assert row["b"] == 2
        finally:
            conn.close()

    def test_readonly_cannot_write(self, tmp_db: Path):
        # First create the file with a normal connection.
        conn = connect(tmp_db)
        conn.execute("CREATE TABLE t (x)")
        conn.close()

        ro = connect(tmp_db, readonly=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                ro.execute("INSERT INTO t VALUES (1)")
        finally:
            ro.close()

    def test_foreign_keys_enforced(self, tmp_db: Path):
        conn = connect(tmp_db)
        try:
            conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE child (pid INTEGER REFERENCES parent(id) "
                "ON DELETE CASCADE)"
            )
            conn.execute("INSERT INTO parent VALUES (1)")
            # Valid FK works.
            conn.execute("INSERT INTO child VALUES (1)")
            # Invalid FK should raise. SQLite raises IntegrityError for FK
            # violations, not OperationalError.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO child VALUES (999)")
        finally:
            conn.close()
