"""Weighted investigator background assignment."""

from __future__ import annotations

from deeparchive.backgrounds import BackgroundAssigner
from deeparchive.content import load_content
from deeparchive.identity import IdentityResolver
from deeparchive.rng import Rng


def test_shipped_background_weights() -> None:
    backgrounds = load_content().backgrounds
    assert {key: value.weight for key, value in backgrounds.items()} == {
        "archivist": 5,
        "occultist": 5,
        "custodian": 5,
        "skeptic": 4,
        "gambler": 1,
    }
    assert all(sum(background.stats.values()) == 3 for background in backgrounds.values())


def test_seeded_assignment_persists_stats(migrated_conn) -> None:
    content = load_content()
    resolver = IdentityResolver(
        migrated_conn, BackgroundAssigner(content, Rng(42))
    )
    player = resolver.resolve_identity("alice", None)
    row = migrated_conn.execute(
        "SELECT background_key, wit, strength, occultism FROM players WHERE id = ?",
        (player.id,),
    ).fetchone()
    definition = content.backgrounds[row["background_key"]]
    assert (row["wit"], row["strength"], row["occultism"]) == (
        definition.stats["wit"],
        definition.stats["strength"],
        definition.stats["occultism"],
    )


def test_existing_unassigned_player_is_backfilled(migrated_conn) -> None:
    migrated_conn.execute(
        "INSERT INTO players (id, display_nick) VALUES ('old', 'oldnick')"
    )
    migrated_conn.execute(
        "INSERT INTO nick_map (nick, player_id) VALUES ('oldnick', 'old')"
    )
    migrated_conn.commit()
    resolver = IdentityResolver(
        migrated_conn, BackgroundAssigner(load_content(), Rng(42))
    )
    resolver.resolve_identity("oldnick", None)
    row = migrated_conn.execute(
        "SELECT background_key FROM players WHERE id = 'old'"
    ).fetchone()
    assert row["background_key"] != "unassigned"
