"""Personnel-file repository and rendering tests."""

from __future__ import annotations

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.content import load_content
from deeparchive.identity import IdentityResolver, Player
from deeparchive.modifiers import ModifierService
from deeparchive.profiles import ProfileRepository, render_profile


def test_profile_repository_reads_persisted_values(
    migrated_conn, background_assigner
) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", "account"
    )
    migrated_conn.execute(
        "UPDATE players SET wit = 1, strength = 2, occultism = 3 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.commit()

    profile = ProfileRepository(
        migrated_conn,
        DailyActionLedger(migrated_conn),
        load_content(),
        ModifierService(migrated_conn),
    ).get(player)

    assert (profile.wit, profile.strength, profile.occultism) == (1, 2, 3)
    assert profile.scars == ()
    assert render_profile(profile)[2] == "Actions remaining today: 5."
    assert render_profile(profile)[3].startswith("Background:")
    assert render_profile(profile)[4] == "Scars: none recorded."


def test_profile_repository_rejects_missing_player(migrated_conn) -> None:
    missing = Player(id="missing", account=None, display_nick="nobody")
    with pytest.raises(LookupError, match="no longer exists"):
        ProfileRepository(
            migrated_conn,
            DailyActionLedger(migrated_conn),
            load_content(),
            ModifierService(migrated_conn),
        ).get(missing)


def test_profile_shows_effective_scar_modified_stats(
    migrated_conn, background_assigner
) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", None
    )
    migrated_conn.execute(
        "UPDATE players SET wit = 1, strength = 1, occultism = 1 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.execute(
        "INSERT INTO scars (player_id, scar_key, modifiers_json, description) "
        "VALUES (?, 'borrowed_shadow', "
        "'[{\"stat\":\"wit\",\"delta\":1},{\"stat\":\"occultism\",\"delta\":-1}]', "
        "'The shadow moves late.')",
        (player.id,),
    )
    migrated_conn.commit()
    profile = ProfileRepository(
        migrated_conn,
        DailyActionLedger(migrated_conn),
        load_content(),
        ModifierService(migrated_conn),
    ).get(player)
    assert (profile.wit, profile.strength, profile.occultism) == (2, 1, 0)
