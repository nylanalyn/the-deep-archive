"""SQLite connection factory.

All database access goes through :func:`connect`, which centralizes the
pragmas the game relies on:

- WAL journaling so a single writer and many readers coexist cleanly
- foreign keys enforced (the schema leans on FKs for scars/relics)
- a busy timeout so the rare contended write waits instead of erroring

WAL mode is persistent in the database file once set, but we set it on every
connection anyway: it's cheap and protects against an older DB that predates
WAL being enabled (e.g. one created by an earlier test run).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_PRAGMAS = (
    # Write-Ahead Logging: readers never block, and the common case of
    # "one bot process writing" stays fast.
    "PRAGMA journal_mode=WAL",
    # The schema's scar/relic/player relationships assume FK enforcement.
    "PRAGMA foreign_keys=ON",
    # Give a contended writer up to 5s before failing. The bot is the only
    # writer in normal operation; this covers migration/admin concurrency.
    "PRAGMA busy_timeout=5000",
    # Optimise for the access pattern: lots of point lookups by player/file id.
    "PRAGMA synchronous=NORMAL",
)


def connect(
    path: str | Path,
    *,
    readonly: bool = False,
    init_pragmas: bool = True,
) -> sqlite3.Connection:
    """Open a :class:`sqlite3.Connection` to the Archive database.

    Parameters
    ----------
    path:
        Filesystem path. The parent directory is created if missing.
    readonly:
        If ``True``, open with ``mode=ro``. Useful for inspection tools that
        must not mutate state. Pragmas that write (journal_mode) are skipped.
    init_pragmas:
        Apply the standard pragma set. Tests occasionally turn this off to
        inspect behaviour without WAL interference.
    """
    db_path = Path(path)
    # WAL needs a real directory to live in; create it eagerly.
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if readonly:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))

    if init_pragmas:
        for pragma in DEFAULT_PRAGMAS:
            conn.execute(pragma)

    # Row access by column name everywhere; much less error-prone than indexes.
    conn.row_factory = sqlite3.Row
    return conn
