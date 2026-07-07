"""Automatic File resolution, consequences, and replacement."""

from __future__ import annotations

import pytest

from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.identity import IdentityResolver
from deeparchive.resolution import ResolutionService, resolution_tier
from deeparchive.rng import Rng


@pytest.mark.parametrize(
    ("penalty", "tier"),
    [
        (0, "clean_success"),
        (1, "success"),
        (2, "partial_success"),
        (3, "mixed_failure"),
        (4, "failure"),
        (5, "disaster"),
        (20, "disaster"),
    ],
)
def test_resolution_tiers(penalty, tier) -> None:
    assert resolution_tier(penalty, penalty) == tier


def _ready_file(migrated_conn, *, failures: int = 0):
    content = load_content()
    active = FileService(migrated_conn, content, Rng(1)).ensure_active()
    migrated_conn.execute(
        "UPDATE active_file SET successes = success_threshold, failures = ?, "
        "danger = ?, theme_tags_json = '[\"darkness\"]' WHERE id = 1",
        (failures, failures),
    )
    migrated_conn.commit()
    return content, active


def test_clean_resolution_shelves_relic_and_opens_next_file(
    migrated_conn, background_assigner
) -> None:
    content, old = _ready_file(migrated_conn)
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    migrated_conn.execute(
        "INSERT INTO active_file_participants (player_id) VALUES (?)", (player.id,)
    )
    migrated_conn.commit()
    migrated_conn.execute("BEGIN IMMEDIATE")
    outcome = ResolutionService(migrated_conn, content, Rng(4)).resolve_if_ready()
    migrated_conn.execute("COMMIT")

    assert outcome is not None and outcome.tier == "clean_success"
    assert outcome.next_file.title != old.title or outcome.next_file.seed != old.seed
    assert migrated_conn.execute("SELECT COUNT(*) FROM file_history").fetchone()[0] == 1
    assert migrated_conn.execute("SELECT COUNT(*) FROM relics").fetchone()[0] == 1
    assert migrated_conn.execute("SELECT COUNT(*) FROM active_file").fetchone()[0] == 1
    completed = migrated_conn.execute(
        "SELECT completed_files FROM players WHERE id = ?", (player.id,)
    ).fetchone()[0]
    assert completed == 1


def test_failure_scars_one_participant(migrated_conn, background_assigner) -> None:
    content, _ = _ready_file(migrated_conn, failures=4)
    resolver = IdentityResolver(migrated_conn, background_assigner)
    players = [resolver.resolve_identity(name, None) for name in ("alice", "bob")]
    migrated_conn.executemany(
        "INSERT INTO active_file_participants (player_id) VALUES (?)",
        [(player.id,) for player in players],
    )
    migrated_conn.commit()
    migrated_conn.execute("BEGIN IMMEDIATE")
    outcome = ResolutionService(migrated_conn, content, Rng(8)).resolve_if_ready()
    migrated_conn.execute("COMMIT")

    assert outcome is not None and outcome.tier == "failure"
    assert migrated_conn.execute("SELECT COUNT(*) FROM scars").fetchone()[0] == 1
    completed = migrated_conn.execute(
        "SELECT SUM(completed_files) FROM players"
    ).fetchone()[0]
    assert completed == 2


def test_not_ready_is_noop(migrated_conn) -> None:
    content = load_content()
    FileService(migrated_conn, content, Rng(1)).ensure_active()
    migrated_conn.execute("BEGIN IMMEDIATE")
    assert ResolutionService(migrated_conn, content, Rng(2)).resolve_if_ready() is None
    migrated_conn.execute("ROLLBACK")
