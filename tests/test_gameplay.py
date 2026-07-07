"""Deterministic Phase 6 checks and hidden File updates."""

from __future__ import annotations

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.gameplay import GameplayService
from deeparchive.identity import IdentityResolver
from deeparchive.modifiers import ModifierService
from deeparchive.rng import Rng
from deeparchive.resolution import ResolutionService


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


def _setup(migrated_conn, rng: FixedRng, background_assigner):
    content = load_content()
    FileService(migrated_conn, content, Rng(1)).ensure_active()
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    migrated_conn.execute(
        "UPDATE players SET wit = 0, strength = 0, occultism = 0 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.commit()
    ledger = DailyActionLedger(migrated_conn)
    resolution = ResolutionService(migrated_conn, content, Rng(2))
    return player, ledger, GameplayService(
        migrated_conn, ledger, rng, resolution, ModifierService(migrated_conn)
    )


def test_success_updates_successes_and_clues(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    outcome = gameplay.perform(player, "interview")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and outcome.success
    assert tuple(row) == (1, 0, 0, 1)


def test_failure_updates_failures_and_danger(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    outcome = gameplay.perform(player, "force")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and not outcome.success
    assert tuple(row) == (0, 1, 1, 0)


def test_player_stat_changes_check_result(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    migrated_conn.execute("UPDATE players SET wit = 1 WHERE id = ?", (player.id,))
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and outcome.success


def test_investigate_uses_half_chance(migrated_conn, background_assigner) -> None:
    rng = FixedRng(chance=False)
    player, _, gameplay = _setup(migrated_conn, rng, background_assigner)
    outcome = gameplay.perform(player, "investigate")
    assert outcome is not None and not outcome.success
    assert rng.last_probability == 0.5


def test_gambler_investigate_uses_improved_chance(
    migrated_conn, background_assigner
) -> None:
    rng = FixedRng(chance=True)
    player, _, gameplay = _setup(migrated_conn, rng, background_assigner)
    migrated_conn.execute(
        "UPDATE players SET background_key = 'gambler' WHERE id = ?", (player.id,)
    )
    migrated_conn.commit()
    gameplay.perform(player, "investigate")
    assert rng.last_probability == 0.55


def test_scar_and_relic_can_turn_failure_into_success(
    migrated_conn, background_assigner
) -> None:
    player, _, gameplay = _setup(
        migrated_conn, FixedRng(die=1), background_assigner
    )
    migrated_conn.execute(
        "UPDATE active_file SET theme_tags_json = '[\"darkness\"]' WHERE id = 1"
    )
    migrated_conn.execute(
        "INSERT INTO scars (player_id, scar_key, modifiers_json, description) "
        "VALUES (?, 'glass_eye', '[{\"stat\":\"wit\",\"delta\":1}]', 'glass')",
        (player.id,),
    )
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, effects_json, description) VALUES "
        "('lamp', '[{\"type\":\"stat_bonus\",\"amount\":2,"
        "\"tags\":[\"darkness\"]}]', 'steady')"
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and outcome.success


@pytest.mark.parametrize(
    ("action", "stat"),
    [("interview", "wit"), ("force", "strength"), ("ritual", "occultism")],
)
def test_each_command_uses_its_own_stat(migrated_conn, background_assigner, action, stat) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=1), background_assigner)
    migrated_conn.execute(
        f"UPDATE players SET {stat} = 3 WHERE id = ?", (player.id,)
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, action)
    assert outcome is not None and outcome.success


def test_exhausted_action_does_not_change_file(migrated_conn, background_assigner) -> None:
    player, ledger, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    for _ in range(5):
        assert gameplay.perform(player, "interview") is not None
    before = migrated_conn.execute("SELECT * FROM active_file").fetchone()
    assert gameplay.perform(player, "interview") is None
    after = migrated_conn.execute("SELECT * FROM active_file").fetchone()
    assert tuple(after) == tuple(before)
    assert ledger.allowance(player.id).used == 5


def test_file_update_failure_rolls_back_action(migrated_conn, background_assigner) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    ledger = DailyActionLedger(migrated_conn)
    gameplay = GameplayService(
        migrated_conn,
        ledger,
        FixedRng(),
        ResolutionService(migrated_conn, load_content(), Rng(2)),
        ModifierService(migrated_conn),
    )
    with pytest.raises(RuntimeError, match="no active File"):
        gameplay.perform(player, "interview")
    assert ledger.allowance(player.id).used == 0


def test_threshold_crossing_resolves_and_opens_next_file(
    migrated_conn, background_assigner
) -> None:
    player, ledger, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    old_seed = migrated_conn.execute("SELECT seed FROM active_file").fetchone()[0]
    migrated_conn.execute(
        "UPDATE active_file SET success_threshold = 1 WHERE id = 1"
    )
    migrated_conn.commit()

    outcome = gameplay.perform(player, "interview")

    assert outcome is not None and outcome.success
    assert outcome.resolution is not None
    assert ledger.allowance(player.id).used == 1
    assert migrated_conn.execute("SELECT COUNT(*) FROM file_history").fetchone()[0] == 1
    new_seed = migrated_conn.execute("SELECT seed FROM active_file").fetchone()[0]
    assert new_seed != old_seed
