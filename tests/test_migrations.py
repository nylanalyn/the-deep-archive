"""Tests for the migration runner.

These exercise the runner mechanics. The actual shipped 0001 migration is
covered separately in test_schema.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from deeparchive.db.connection import connect
from deeparchive.db.migrations import (
    MigrationError,
    current_version,
    discover_migrations,
    migrate,
)


def _write_migration(directory: Path, version: int, name: str, sql: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version:04d}_{name}.sql"
    path.write_text(sql, encoding="utf-8")
    return path


class TestDiscover:
    def test_empty_directory_returns_empty(self, tmp_path):
        assert discover_migrations(tmp_path) == []

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(MigrationError, match="not found"):
            discover_migrations(tmp_path / "nope")

    def test_finds_and_sorts(self, tmp_path):
        _write_migration(tmp_path, 3, "third", "SELECT 1;")
        _write_migration(tmp_path, 1, "first", "SELECT 1;")
        _write_migration(tmp_path, 2, "second", "SELECT 1;")
        found = discover_migrations(tmp_path)
        versions = [v for v, _ in found]
        assert versions == [1, 2, 3]

    def test_duplicate_version_raises(self, tmp_path):
        _write_migration(tmp_path, 1, "one", "SELECT 1;")
        _write_migration(tmp_path, 1, "also_one", "SELECT 1;")
        with pytest.raises(MigrationError, match="duplicate"):
            discover_migrations(tmp_path)

    def test_bad_filename_ignored_unless_sql(self, tmp_path):
        # Non-.sql files should be ignored, not raise.
        (tmp_path / "README.md").write_text("hi")
        _write_migration(tmp_path, 1, "first", "SELECT 1;")
        found = discover_migrations(tmp_path)
        assert [v for v, _ in found] == [1]

    def test_misnamed_sql_raises(self, tmp_path):
        (tmp_path / "migration.sql").write_text("SELECT 1;")
        with pytest.raises(MigrationError, match="must match"):
            discover_migrations(tmp_path)


class TestMigrate:
    def test_applies_migrations_in_order(self, tmp_path):
        conn = connect(":memory:")
        try:
            assert current_version(conn) == 0
            _write_migration(tmp_path, 1, "a", "CREATE TABLE a (x);")
            _write_migration(
                tmp_path, 2, "b", "CREATE TABLE b (x); INSERT INTO a VALUES (1);"
            )
            version = migrate(conn, directory=tmp_path)
            assert version == 2
            assert current_version(conn) == 2
            # Both tables created.
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {"a", "b"}.issubset(tables)
        finally:
            conn.close()

    def test_idempotent(self, tmp_path):
        conn = connect(":memory:")
        try:
            _write_migration(tmp_path, 1, "a", "CREATE TABLE a (x);")
            migrate(conn, directory=tmp_path)
            # Running again applies nothing.
            version = migrate(conn, directory=tmp_path)
            assert version == 1
        finally:
            conn.close()

    def test_failure_rolls_back(self, tmp_path):
        conn = connect(":memory:")
        try:
            _write_migration(tmp_path, 1, "good", "CREATE TABLE good (x);")
            # Bad migration: references a table that doesn't exist.
            _write_migration(
                tmp_path, 2, "bad", "INSERT INTO nope VALUES (1);"
            )
            with pytest.raises(MigrationError, match="failed"):
                migrate(conn, directory=tmp_path)
            # Version 1 should have committed; version 2 rolled back.
            assert current_version(conn) == 1
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "good" in tables
        finally:
            conn.close()

    def test_no_migrations_is_noop(self, tmp_path):
        conn = connect(":memory:")
        try:
            version = migrate(conn, directory=tmp_path)
            assert version == 0
        finally:
            conn.close()
