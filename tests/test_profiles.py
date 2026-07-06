"""Personnel-file repository and rendering tests."""

from __future__ import annotations

import pytest

from deeparchive.identity import IdentityResolver, Player
from deeparchive.profiles import ProfileRepository, render_profile


def test_profile_repository_reads_persisted_values(migrated_conn) -> None:
    player = IdentityResolver(migrated_conn).resolve_identity("alice", "account")
    migrated_conn.execute(
        "UPDATE players SET wit = 1, strength = 2, occultism = 3 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.commit()

    profile = ProfileRepository(migrated_conn).get(player)

    assert (profile.wit, profile.strength, profile.occultism) == (1, 2, 3)
    assert profile.scars == ()
    assert render_profile(profile)[2] == "Scars: none recorded."


def test_profile_repository_rejects_missing_player(migrated_conn) -> None:
    missing = Player(id="missing", account=None, display_nick="nobody")
    with pytest.raises(LookupError, match="no longer exists"):
        ProfileRepository(migrated_conn).get(missing)
