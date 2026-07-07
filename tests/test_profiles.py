"""Personnel-file repository and rendering tests."""

from __future__ import annotations

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.content import load_content
from deeparchive.identity import IdentityResolver, Player
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
        migrated_conn, DailyActionLedger(migrated_conn), load_content()
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
            migrated_conn, DailyActionLedger(migrated_conn), load_content()
        ).get(missing)
