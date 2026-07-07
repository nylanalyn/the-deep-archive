"""Scar, relic, and background modifiers applied to checks."""

from __future__ import annotations

import json

import pytest

from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.identity import IdentityResolver
from deeparchive.modifiers import (
    BASE_INVESTIGATE_CHANCE,
    GAMBLER_INVESTIGATE_CHANCE,
    ModifierService,
)
from deeparchive.rng import Rng


def _player_and_modifiers(migrated_conn, background_assigner):
    FileService(migrated_conn, load_content(), Rng(1)).ensure_active()
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", None
    )
    migrated_conn.execute(
        "UPDATE players SET wit = 0, strength = 0, occultism = 0 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.commit()
    return player, ModifierService(migrated_conn)


def test_scar_deltas_stack_by_stat(migrated_conn, background_assigner) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    migrated_conn.executemany(
        "INSERT INTO scars (player_id, scar_key, modifiers_json, description) "
        "VALUES (?, ?, ?, ?)",
        [
            (player.id, "one", '[{"stat":"wit","delta":1}]', "one"),
            (player.id, "two", '[{"stat":"wit","delta":-2}]', "two"),
            (player.id, "three", '[{"stat":"strength","delta":2}]', "three"),
        ],
    )
    assert modifiers.effective_stat(player.id, "wit") == -1
    assert modifiers.effective_stat(player.id, "strength") == 2
    assert modifiers.effective_stat(player.id, "occultism") == 0


def test_matching_relic_adds_bonus_to_every_stat(
    migrated_conn, background_assigner
) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET theme_tags_json = '[\"darkness\"]' WHERE id = 1"
    )
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, effects_json, description) VALUES (?, ?, ?)",
        (
            "lamp",
            json.dumps(
                [{"type": "stat_bonus", "amount": 1, "tags": ["darkness"]}]
            ),
            "steady",
        ),
    )
    assert modifiers.effective_stat(player.id, "wit") == 1
    assert modifiers.effective_stat(player.id, "strength") == 1
    assert modifiers.effective_stat(player.id, "occultism") == 1


def test_nonmatching_relic_does_not_apply(migrated_conn, background_assigner) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET theme_tags_json = '[\"flood\"]' WHERE id = 1"
    )
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, effects_json, description) VALUES (?, ?, ?)",
        (
            "lamp",
            '[{"type":"stat_bonus","amount":1,"tags":["darkness"]}]',
            "steady",
        ),
    )
    assert modifiers.effective_stat(player.id, "wit") == 0


def test_multiple_matching_relics_stack(migrated_conn, background_assigner) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    migrated_conn.execute(
        "UPDATE active_file SET theme_tags_json = '[\"geometry\"]' WHERE id = 1"
    )
    migrated_conn.executemany(
        "INSERT INTO relics (relic_key, effects_json, description) VALUES (?, ?, ?)",
        [
            ("one", '[{"type":"stat_bonus","amount":1,"tags":["geometry"]}]', "d"),
            ("two", '[{"type":"stat_bonus","amount":2,"tags":["geometry"]}]', "d"),
        ],
    )
    assert modifiers.effective_stat(player.id, "wit") == 3


def test_gambler_gets_improved_investigate_chance(
    migrated_conn, background_assigner
) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    assert modifiers.investigate_chance(player.id) == BASE_INVESTIGATE_CHANCE
    migrated_conn.execute(
        "UPDATE players SET background_key = 'gambler' WHERE id = ?", (player.id,)
    )
    assert modifiers.investigate_chance(player.id) == GAMBLER_INVESTIGATE_CHANCE


def test_unknown_stat_is_rejected(migrated_conn, background_assigner) -> None:
    player, modifiers = _player_and_modifiers(migrated_conn, background_assigner)
    with pytest.raises(ValueError, match="unknown stat"):
        modifiers.effective_stat(player.id, "luck")
