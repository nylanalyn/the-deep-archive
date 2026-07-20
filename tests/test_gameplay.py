"""Deterministic Phase 6 checks and hidden File updates."""

from __future__ import annotations

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.action_flavour import ActionNarrator
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
        self.probabilities: list[float] = []

    def randint(self, low: int, high: int) -> int:
        assert low <= self.die <= high
        return self.die

    def chance(self, probability: float) -> bool:
        self.probabilities.append(probability)
        return self.chance_result

    def choice(self, seq):
        return seq[0]


def _setup(migrated_conn, rng: FixedRng, background_assigner):
    content = load_content()
    FileService(migrated_conn, content, Rng(1)).ensure_active()
    # Detach the File from any real theme so dispositions stay out of tests
    # that aren't about them.
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'neutral' WHERE id = 1"
    )
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    migrated_conn.execute(
        "UPDATE players SET wit = 0, strength = 0, occultism = 0 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.commit()
    ledger = DailyActionLedger(migrated_conn)
    resolution = ResolutionService(migrated_conn, content, Rng(2))
    return player, ledger, GameplayService(
        migrated_conn,
        ledger,
        rng,
        resolution,
        ModifierService(migrated_conn, content),
        ActionNarrator(content, Rng(99)),
        content,
    )


def test_success_updates_successes_and_clues(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    outcome = gameplay.perform(player, "interview")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and outcome.success
    assert tuple(row) == (1, 0, 0, 1)


def test_failed_interview_adds_one_danger(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    outcome = gameplay.perform(player, "interview")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and not outcome.success
    assert tuple(row) == (0, 1, 1, 0)


def test_failed_force_adds_double_danger(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    outcome = gameplay.perform(player, "force")
    row = migrated_conn.execute(
        "SELECT successes, failures, danger, clue_count FROM active_file"
    ).fetchone()
    assert outcome is not None and not outcome.success
    assert tuple(row) == (0, 1, 2, 0)


def test_player_stat_changes_check_result(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    migrated_conn.execute("UPDATE players SET wit = 1 WHERE id = ?", (player.id,))
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and outcome.success


def test_natural_one_always_fails(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=1), background_assigner)
    migrated_conn.execute("UPDATE players SET wit = 10 WHERE id = ?", (player.id,))
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and not outcome.success


def test_natural_six_always_succeeds(migrated_conn, background_assigner) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=6), background_assigner)
    migrated_conn.execute("UPDATE players SET wit = -5 WHERE id = ?", (player.id,))
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and outcome.success


def test_theme_disposition_resists_action(migrated_conn, background_assigner) -> None:
    # Darkness resists interview (-1): an otherwise-passing 4 now misses.
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness' WHERE id = 1"
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, "interview")
    assert outcome is not None and not outcome.success


def test_theme_disposition_favours_action(migrated_conn, background_assigner) -> None:
    # Darkness favours ritual (+1): an otherwise-failing 3 now passes.
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=3), background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness' WHERE id = 1"
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, "ritual")
    assert outcome is not None and outcome.success


def test_investigate_uses_half_chance(migrated_conn, background_assigner) -> None:
    rng = FixedRng(chance=False)
    player, _, gameplay = _setup(migrated_conn, rng, background_assigner)
    outcome = gameplay.perform(player, "investigate")
    assert outcome is not None and not outcome.success
    assert rng.probabilities[0] == 0.5


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
    assert rng.probabilities[0] == 0.55


def test_successful_investigate_can_steady_the_file(
    migrated_conn, background_assigner
) -> None:
    rng = FixedRng(chance=True)  # succeeds, steadies, and complicates
    player, _, gameplay = _setup(migrated_conn, rng, background_assigner)
    migrated_conn.execute("UPDATE active_file SET danger = 2 WHERE id = 1")
    migrated_conn.commit()
    outcome = gameplay.perform(player, "investigate")
    row = migrated_conn.execute(
        "SELECT successes, danger FROM active_file"
    ).fetchone()
    assert outcome is not None and outcome.success
    # danger 2 - 1 (steadied) + 1 (complication) = 2
    assert tuple(row) == (1, 2)
    assert len(outcome.extra_lines) == 2


def test_failed_investigate_never_steadies(migrated_conn, background_assigner) -> None:
    rng = FixedRng(chance=False)
    player, _, gameplay = _setup(migrated_conn, rng, background_assigner)
    migrated_conn.execute("UPDATE active_file SET danger = 2 WHERE id = 1")
    migrated_conn.commit()
    outcome = gameplay.perform(player, "investigate")
    row = migrated_conn.execute("SELECT danger FROM active_file").fetchone()
    assert outcome is not None and not outcome.success
    assert int(row["danger"]) == 3  # +1 failure danger, no steady, no complication


def test_crossing_danger_threshold_emits_omen(
    migrated_conn, background_assigner
) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=2), background_assigner)
    migrated_conn.execute("UPDATE active_file SET danger = 2 WHERE id = 1")
    migrated_conn.commit()
    outcome = gameplay.perform(player, "force")  # fail: danger 2 -> 4, crosses 3
    assert outcome is not None and not outcome.success
    assert len(outcome.extra_lines) == 1


def test_critical_danger_bites_the_acting_investigator(
    migrated_conn, background_assigner
) -> None:
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=2), background_assigner)
    migrated_conn.execute("UPDATE active_file SET danger = 7 WHERE id = 1")
    migrated_conn.commit()
    outcome = gameplay.perform(player, "force")  # fail: danger 7 -> 9, bites at 8
    assert outcome is not None and not outcome.success
    assert any("The File bites" in line for line in outcome.extra_lines)
    scar_count = migrated_conn.execute(
        "SELECT COUNT(*) FROM scars WHERE player_id = ?", (player.id,)
    ).fetchone()[0]
    assert scar_count == 1


def test_scar_and_relic_can_turn_failure_into_success(
    migrated_conn, background_assigner
) -> None:
    player, _, gameplay = _setup(
        migrated_conn, FixedRng(die=2), background_assigner
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
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=2), background_assigner)
    migrated_conn.execute(
        f"UPDATE players SET {stat} = 2 WHERE id = ?", (player.id,)
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
    content = load_content()
    gameplay = GameplayService(
        migrated_conn,
        ledger,
        FixedRng(),
        ResolutionService(migrated_conn, content, Rng(2)),
        ModifierService(migrated_conn, content),
        ActionNarrator(content, Rng(99)),
        content,
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


def test_disposition_softens_and_sharpens_danger(
    migrated_conn, background_assigner
) -> None:
    # Dust favours force: a failed force only adds 1 danger instead of 2.
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=2), background_assigner)
    migrated_conn.execute("UPDATE active_file SET theme_key = 'dust' WHERE id = 1")
    migrated_conn.commit()
    outcome = gameplay.perform(player, "force")
    danger = migrated_conn.execute("SELECT danger FROM active_file").fetchone()[0]
    assert outcome is not None and not outcome.success
    assert danger == 1

    # Flood resists force: a failed force adds 3.
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'flood', danger = 0 WHERE id = 1"
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, "force")
    danger = migrated_conn.execute("SELECT danger FROM active_file").fetchone()[0]
    assert outcome is not None and not outcome.success
    assert danger == 3


def test_clues_reveal_in_order_across_threshold(
    migrated_conn, background_assigner
) -> None:
    # A theme's ordered clue track surfaces one clue at a time, evenly spread
    # across the hidden threshold, ending on the completing success.
    _, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    darkness = load_content().themes["darkness"]
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness', success_threshold = 12 "
        "WHERE id = 1"
    )
    revealed: list[str] = []
    for successes in range(1, 13):
        migrated_conn.execute(
            "UPDATE active_file SET successes = ? WHERE id = 1", (successes,)
        )
        revealed.extend(gameplay._clue_reveals())
    assert revealed == list(darkness.clues)
    # The last clue (the "aha") lands on the final, completing success.
    migrated_conn.execute("UPDATE active_file SET successes = 12 WHERE id = 1")
    assert gameplay._clue_reveals() == [darkness.clues[-1]]


def test_sealed_file_prefers_arc_clues(migrated_conn, background_assigner) -> None:
    # A Sealed File reveals its arc's clues, not the underlying theme's.
    _, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    content = load_content()
    arc = content.meta_arcs["black_index"]
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness', arc_key = 'black_index', "
        "success_threshold = 6, successes = 1 WHERE id = 1"
    )
    assert gameplay._clue_reveals() == [arc.clues[0]]
    assert arc.clues[0] not in content.themes["darkness"].clues


def test_clueless_theme_reveals_nothing(migrated_conn, background_assigner) -> None:
    # The test harness detaches the File onto a themeless 'neutral' key; a File
    # with no clue track simply reveals nothing.
    _, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    migrated_conn.execute("UPDATE active_file SET successes = 3 WHERE id = 1")
    assert gameplay._clue_reveals() == []


def test_success_emits_clue_in_action_output(
    migrated_conn, background_assigner
) -> None:
    # A real successful action surfaces the clue in the outcome's extra lines.
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    darkness = load_content().themes["darkness"]
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness', success_threshold = 6 "
        "WHERE id = 1"
    )
    migrated_conn.commit()
    # Darkness favours ritual (+1), so a 4 clears the target and reveals clue 1.
    outcome = gameplay.perform(player, "ritual")
    assert outcome is not None and outcome.success
    assert darkness.clues[0] in outcome.extra_lines


def test_unlocking_action_states_the_confront_stake(
    migrated_conn, background_assigner
) -> None:
    # The action that carries a Sealed File's evidence to the threshold unlocks
    # !confront and states the stake once, at that moment.
    player, _, gameplay = _setup(migrated_conn, FixedRng(die=4), background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET is_sealed = 1, theme_key = 'darkness', "
        "success_threshold = 1, successes = 0 WHERE id = 1"
    )
    migrated_conn.commit()
    outcome = gameplay.perform(player, "ritual")  # darkness favours ritual (+1)
    assert outcome is not None and outcome.confront_unlocked
    rendered = gameplay.render(outcome)
    assert any("!confront" in line for line in rendered)
    assert any("sealed shelves keep what you came for" in line for line in rendered)
