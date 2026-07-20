"""No-duplicate investigator background assignment."""

from __future__ import annotations

from deeparchive.backgrounds import BackgroundAssigner
from deeparchive.content import load_content
from deeparchive.identity import IdentityResolver
from deeparchive.rng import Rng


class FakeRng:
    """Deterministic stand-in: control the rare roll and the pool pick."""

    def __init__(self, *, rare_roll: bool = False, pick: int = 0) -> None:
        self.rare_roll = rare_roll
        self.pick = pick

    def chance(self, _probability: float) -> bool:
        return self.rare_roll

    def choice(self, seq):
        return seq[self.pick]


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


def test_rotation_assigns_distinct_classes_until_pool_cycles() -> None:
    # With the rare roll suppressed, the first four investigators each get a
    # different common class; the fifth begins the next cycle.
    assigner = BackgroundAssigner(load_content(), FakeRng(rare_roll=False, pick=0))
    counts: dict[str, int] = {}
    picks: list[str] = []
    for _ in range(5):
        chosen = assigner.choose(counts)
        picks.append(chosen.key)
        counts[chosen.key] = counts.get(chosen.key, 0) + 1
    assert len(set(picks[:4])) == 4  # four distinct classes, no duplicates
    assert "gambler" not in picks  # rare stays out of the rotation
    assert picks[4] == picks[0]  # the pool cycles once each class is held


def test_gambler_excluded_from_rotation_but_surfaces_on_rare_roll() -> None:
    content = load_content()
    # Rare roll never fires: the Gambler is never handed out, at any count.
    common_only = BackgroundAssigner(content, FakeRng(rare_roll=False, pick=0))
    for _ in range(20):
        assert common_only.choose({}).key != "gambler"
    # Rare roll fires: the Gambler is the only rare class, so it is chosen.
    rare = BackgroundAssigner(content, FakeRng(rare_roll=True, pick=0))
    assert rare.choose({}).key == "gambler"


def test_least_held_class_wins() -> None:
    assigner = BackgroundAssigner(load_content(), FakeRng(rare_roll=False, pick=0))
    # Everyone is an archivist so far; the next hire must not be another.
    chosen = assigner.choose({"archivist": 3})
    assert chosen.key != "archivist"
