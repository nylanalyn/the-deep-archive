"""Tests for the shipped schema (migration 0001).

Uses the ``migrated_conn`` fixture so every test starts from the full,
production schema. These guard the structural invariants the engine will
lean on: the single-row active_file, the nick_map lookup, FK cascades, and
the JSON columns the game serializes into.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def conn(migrated_conn):
    return migrated_conn


class TestSchemaPresent:
    def test_all_tables_exist(self, conn):
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        expected = {
            "players",
            "nick_map",
            "active_file",
            "file_history",
            "daily_actions",
            "scars",
            "relics",
            "meta_arc_state",
            "active_file_participants",
        }
        assert expected.issubset(tables)

    def test_no_rooms_table(self, conn):
        # Per the settled design: the channel is one canonical Archive.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "rooms" not in tables


class TestPlayerAndNickMap:
    def test_phase_seven_player_columns(self, conn):
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)")}
        assert {"background_key", "completed_files"}.issubset(columns)

    def test_insert_player_and_map_nick(self, conn):
        conn.execute(
            "INSERT INTO players (id, account, display_nick) VALUES (?, ?, ?)",
            ("uuid-1", "alice", "alice"),
        )
        conn.execute(
            "INSERT INTO nick_map (nick, player_id) VALUES (?, ?)",
            ("alice", "uuid-1"),
        )
        row = conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", ("ALICE",)
        ).fetchone()
        # NOCASE collation: case-insensitive lookup.
        assert row["player_id"] == "uuid-1"

    def test_nick_map_cascades_on_player_delete(self, conn):
        conn.execute(
            "INSERT INTO players (id, display_nick) VALUES (?, ?)",
            ("uuid-2", "bob"),
        )
        conn.execute(
            "INSERT INTO nick_map (nick, player_id) VALUES (?, ?)",
            ("bob", "uuid-2"),
        )
        conn.execute("DELETE FROM players WHERE id = ?", ("uuid-2",))
        remaining = conn.execute(
            "SELECT COUNT(*) FROM nick_map WHERE player_id = ?", ("uuid-2",)
        ).fetchone()[0]
        assert remaining == 0

    def test_account_unique(self, conn):
        conn.execute(
            "INSERT INTO players (id, account, display_nick) VALUES (?, ?, ?)",
            ("u1", "acct", "a"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO players (id, account, display_nick) VALUES (?, ?, ?)",
                ("u2", "acct", "b"),
            )


class TestActiveFile:
    def test_single_active_file_constraint(self, conn):
        # The CHECK(id = 1) + PRIMARY KEY pins active_file to a single row.
        conn.execute(
            "INSERT INTO active_file (id, seed, title, location, "
            "success_threshold) VALUES (1, 42, 'Test', 'Stacks', 10)"
        )
        # A second row with a different id is rejected by CHECK.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO active_file (id, seed, title, location, "
                "success_threshold) VALUES (2, 99, 'Other', 'Hall', 10)"
            )

    def test_threshold_persists(self, conn):
        conn.execute(
            "INSERT INTO active_file (id, seed, title, location, "
            "success_threshold) VALUES (1, 7, 'T', 'L', 13)"
        )
        row = conn.execute(
            "SELECT success_threshold FROM active_file WHERE id = 1"
        ).fetchone()
        assert row["success_threshold"] == 13

    def test_generated_content_fields_exist(self, conn):
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(active_file)")
        }
        assert {"theme_key", "opening_text", "is_sealed", "arc_key"}.issubset(columns)

    @pytest.mark.parametrize(
        ("sealed", "starting_threshold", "expected"),
        [(0, 3, 17), (1, 5, 18), (0, 16, 16)],
    )
    def test_live_pacing_migration_preserves_or_extends_active_file(
        self, conn, sealed, starting_threshold, expected
    ):
        conn.execute(
            "INSERT INTO active_file "
            "(id, seed, title, location, success_threshold, is_sealed) "
            "VALUES (1, 1, 'T', 'L', ?, ?)",
            (starting_threshold, sealed),
        )
        migration = (
            Path(__file__).resolve().parents[1]
            / "deeparchive"
            / "db"
            / "schema"
            / "0005_rebalance_file_thresholds.sql"
        )
        conn.executescript(migration.read_text(encoding="utf-8"))
        threshold = conn.execute(
            "SELECT success_threshold FROM active_file WHERE id = 1"
        ).fetchone()[0]
        assert threshold == expected


class TestForeignKeys:
    def test_scars_cascade_on_player_delete(self, conn):
        conn.execute(
            "INSERT INTO players (id, display_nick) VALUES (?, ?)", ("u1", "a")
        )
        conn.execute(
            "INSERT INTO scars (player_id, scar_key, description) "
            "VALUES (?, ?, ?)",
            ("u1", "paper_bones", "brittle"),
        )
        conn.execute("DELETE FROM players WHERE id = ?", ("u1",))
        count = conn.execute(
            "SELECT COUNT(*) FROM scars WHERE player_id = ?", ("u1",)
        ).fetchone()[0]
        assert count == 0

    def test_daily_actions_cascade_on_player_delete(self, conn):
        conn.execute(
            "INSERT INTO players (id, display_nick) VALUES (?, ?)", ("u1", "a")
        )
        conn.execute(
            "INSERT INTO daily_actions (player_id, day_key, actions_used) "
            "VALUES (?, ?, ?)",
            ("u1", "2026-07-06", 3),
        )
        conn.execute("DELETE FROM players WHERE id = ?", ("u1",))
        count = conn.execute(
            "SELECT COUNT(*) FROM daily_actions WHERE player_id = ?", ("u1",)
        ).fetchone()[0]
        assert count == 0

    def test_relic_unique_key(self, conn):
        conn.execute(
            "INSERT INTO relics (relic_key, description) VALUES (?, ?)",
            ("brass_lantern", "steady flame"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO relics (relic_key, description) VALUES (?, ?)",
                ("brass_lantern", "dupe"),
            )

    def test_meta_arc_singleton(self, conn):
        conn.execute("INSERT INTO meta_arc_state (id) VALUES (1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO meta_arc_state (id) VALUES (2)")
