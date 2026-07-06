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

    A tiny character scanner: splits on ``;`` while ignoring ``;`` inside
    single- or double-quoted string literals (which may span lines) and
    inside ``--`` line comments. ``/* */`` block comments are not supported
    — the shipped schema is plain DDL and doesn't use them.

    Every statement must be terminated by ``;``. Stray non-whitespace text
    after the final semicolon raises :class:`MigrationError`, because that
    almost always means a forgotten terminator — silently dropping it was a
    real bug in an earlier version of this function.

    Multiple statements may share a line; blank/whitespace-only statements
    are dropped.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    string_char = ""

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        # Inside a string literal: copy verbatim until the matching quote.
        # Doubling the quote ('' or "") is the SQL escape, so two in a row
        # close-and-stay-out rather than ending the string.
        if in_string:
            current.append(ch)
            if ch == string_char:
                if i + 1 < n and sql[i + 1] == string_char:
                    current.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
                string_char = ""
            i += 1
            continue

        # Not in a string. Detect a line comment: ``--`` runs to end of line.
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i)
            if end == -1:
                i = n
            else:
                i = end
            continue

        # Not in a string. A quote opens one.
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            current.append(ch)
            i += 1
            continue

        # Statement terminator outside any string/comment.
        if ch == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    trailing = "".join(current).strip()
    # Anything left over is text after the last ``;`` (or the only text, if
    # there were no semicolons at all). For migrations that's a mistake.
    if trailing:
        raise MigrationError(
            "migration has trailing text with no terminating ';': "
            f"{trailing[:80]!r}..."
        )
    return statements


def _default_migration_dir() -> Path:
    """Resolve the shipped schema directory via :mod:`importlib.resources`.

    Using the resource API (rather than ``__file__``) keeps things correct
    when the package is installed in an egg/wheel.
    """
    files = resources.files("deeparchive.db")
    # The SQL files live in the ``schema`` subpackage alongside this module.
    return Path(str(files.joinpath("schema")))
