"""Numbered SQL migration runner.

Migrations live as ``NNNN_description.sql`` files in a directory (default
``deeparchive/db/schema``), applied in lexical order. Each migration runs
inside a transaction; on failure the transaction rolls back and the error
surfaces. The version is tracked with SQLite's built-in ``PRAGMA user_version``
so no bookkeeping table is needed.

Design notes:

- Migrations are append-only. Never edit a shipped migration; write a new one.
  Editing breaks any database that already applied the original.
- The runner is idempotent: running it twice applies only the missing
  migrations.
- Forward-only. There is no down/rollback path. This is deliberate for a
  persistent game where rolling back the schema would corrupt world state.
"""

from __future__ import annotations

import re
import sqlite3
import tomllib
from importlib import resources
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d+)[-_].*\.sql$")


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied or the directory is malformed."""


def discover_migrations(directory: str | Path) -> list[tuple[int, Path]]:
    """Return ``[(version, path), ...]`` for a migration directory, sorted.

    Raises :class:`MigrationError` if two files claim the same version number
    or if a filename doesn't match the ``NNNN_name.sql`` pattern.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise MigrationError(f"migration directory not found: {directory}")

    found: list[tuple[int, Path]] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix != ".sql":
            continue
        match = _MIGRATION_RE.match(entry.name)
        if not match:
            raise MigrationError(
                f"migration filename {entry.name!r} must match NNNN_description.sql"
            )
        version = int(match.group(1))
        found.append((version, entry))

    # Detect duplicate version numbers (e.g. 0001_foo.sql and 0001_bar.sql).
    versions = [v for v, _ in found]
    duplicates = {v for v in versions if versions.count(v) > 1}
    if duplicates:
        raise MigrationError(
            f"duplicate migration version(s): {sorted(duplicates)}"
        )

    found.sort(key=lambda pair: pair[0])
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """The schema version currently recorded in the database."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(
    conn: sqlite3.Connection,
    directory: str | Path | None = None,
) -> int:
    """Apply all pending migrations from ``directory``.

    Returns the new ``user_version`` after applying.

    ``directory`` defaults to the ``schema`` package directory shipped
    alongside this module (``deeparchive/db/schema``). Tests pass an
    explicit temp directory to exercise the runner in isolation.
    """
    if directory is None:
        directory = _default_migration_dir()

    migrations = discover_migrations(directory)
    current = current_version(conn)

    applied = 0
    for version, path in migrations:
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        statements = _split_sql_statements(sql)
        # Run each statement inside an explicit transaction. We cannot use
        # executescript() here: it issues an implicit COMMIT before running,
        # which destroys any outer transaction and makes rollback impossible.
        # Per-statement execute() keeps the whole migration atomic.
        try:
            conn.execute("BEGIN")
            for statement in statements:
                conn.execute(statement)
            # user_version is set via PRAGMA, which does not accept a
            # parameter placeholder, so we interpolate the int directly.
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except Exception as e:
            # ROLLBACK is only valid while a transaction is open; if the BEGIN
            # itself failed (extremely unlikely) guard against that.
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise MigrationError(
                f"migration {path.name} (version {version}) failed: {e}"
            ) from e
        applied += 1

    return current_version(conn)


def _split_sql_statements(sql: str) -> list[str]:
    """Split a migration script into executable statements.

    Splits on ``;`` at the end of statements, ignoring ``;`` inside string
    literals and ``--`` line comments. Empty/whitespace-only statements are
    dropped. We deliberately do not support ``/* */`` block comments or
    semicolons inside string literals in migrations — the shipped schema is
    plain DDL, and keeping this parser tiny avoids the complexity of a full
    SQL tokenizer for a job that doesn't need one.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    string_char = ""

    for line in sql.splitlines():
        # Strip ``--`` comments, but only when not inside a string literal.
        if not in_string:
            # Find an unquoted ``--``. A naive split is safe here because
            # string literals in our migrations never span lines.
            stripped = line.split("--", 1)[0]
        else:
            stripped = line

        # Track single-line string-literal state so a ``;`` inside a string is
        # not mistaken for a statement terminator. Strings in the shipped DDL
        # are single-line, so we don't need cross-line tracking.
        i = 0
        while i < len(stripped):
            ch = stripped[i]
            if ch in ("'", '"'):
                if in_string and ch == string_char:
                    in_string = False
                    string_char = ""
                elif not in_string:
                    in_string = True
                    string_char = ch
            i += 1

        current.append(stripped)

        if ";" in stripped and not in_string:
            # Everything up to and including the first ``;`` ends a statement.
            before, _, _ = stripped.partition(";")
            stmt_lines = current[:-1] + ([before] if before.strip() else [])
            stmt = "\n".join(stmt_lines).strip()
            if stmt:
                statements.append(stmt)
            current = []

    # Trailing text without a semicolon (e.g. the last statement) — include
    # it only if non-empty after stripping.
    trailing = "\n".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _default_migration_dir() -> Path:
    """Resolve the shipped schema directory via :mod:`importlib.resources`.

    Using the resource API (rather than ``__file__``) keeps things correct
    when the package is installed in an egg/wheel.
    """
    files = resources.files("deeparchive.db")
    # The SQL files live in the ``schema`` subpackage alongside this module.
    return Path(str(files.joinpath("schema")))
