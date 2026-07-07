"""Deterministic Phase 6 checks and hidden File updates."""

from __future__ import annotations

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.gameplay import GameplayService
from deeparchive.identity import IdentityResolver
from deeparchive.rng import Rng


class FixedRng:
    def __init__(self, *, die: int = 4, chance: bool = True) -> None:
        self.die = die
        self.chance_result = chance
        self.last_probability: float | None = None

    def randint(self, low: int, high: int) -> int:
        assert low <= self.die <= high
        return self.die

    def chance(self, probability: float) -> bool:
        self.last_probability = probability
        return self.chance_result


def _setup(migrated_conn, rng: FixedRng):
    FileService(migrated_conn, load_content(), Rng(1)).ensure_active()
    player = IdentityResolver(migrated_conn).resolve_identity("alice", None)
    ledger = DailyActionLedger(migrated_conn)
    return player, ledger, GameplayService(migrated_conn, ledger, rng)


def test_success_updates_successes_and_clues(migrated_conn) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4))
    outcome = gameplay.perform(player, "interview")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and outcome.success
    assert tuple(row) == (1, 0, 0, 1)


def test_failure_updates_failures_and_danger(migrated_conn) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3))
    outcome = gameplay.perform(player, "force")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and not outcome.success
    assert tuple(row) == (0, 1, 1, 0)


def test_player_stat_changes_check_result(migrated_conn) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3))
    migrated_conn.execute("UPDATE players SET wit = 1 WHERE id = ?", (player.id,))
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and outcome.success


def test_investigate_uses_half_chance(migrated_conn) -> None:
    rng = FixedRng(chance=False)
    player, _, gameplay = _setup(migrated_conn, rng)
    outcome = gameplay.perform(player, "investigate")
    assert outcome is not None and not outcome.success
    assert rng.last_probability == 0.5


@pytest.mark.parametrize(
    ("action", "stat"),
    [("interview", "wit"), ("force", "strength"), ("ritual", "occultism")],
)
def test_each_command_uses_its_own_stat(migrated_conn, action, stat) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=1))
    migrated_conn.execute(
        f"UPDATE players SET {stat} = 3 WHERE id = ?", (player.id,)
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, action)
    assert outcome is not None and outcome.success


def test_exhausted_action_does_not_change_file(migrated_conn) -> None:
    player, ledger, gameplay = _setup(migrated_conn, FixedRng(die=4))
    for _ in range(5):
        assert gameplay.perform(player, "interview") is not None
    before = migrated_conn.execute("SELECT * FROM active_file").fetchone()
    assert gameplay.perform(player, "interview") is None
    after = migrated_conn.execute("SELECT * FROM active_file").fetchone()
    assert tuple(after) == tuple(before)
    assert ledger.allowance(player.id).used == 5


def test_file_update_failure_rolls_back_action(migrated_conn) -> None:
    player = IdentityResolver(migrated_conn).resolve_identity("alice", None)
    ledger = DailyActionLedger(migrated_conn)
    gameplay = GameplayService(migrated_conn, ledger, FixedRng())
    with pytest.raises(RuntimeError, match="no active File"):
        gameplay.perform(player, "interview")
    assert ledger.allowance(player.id).used == 0
