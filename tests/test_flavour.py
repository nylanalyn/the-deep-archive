"""Archive descriptions and stable personnel titles."""

from __future__ import annotations

from deeparchive.content import load_content
from deeparchive.flavour import ArchiveFlavourService, personnel_title
from deeparchive.rng import Rng


def test_empty_archive_description_mentions_empty_history(migrated_conn) -> None:
    lines = ArchiveFlavourService(
        migrated_conn, load_content(), Rng(1)
    ).describe()
    assert len(lines) == 4
    assert lines[-1] == (
        "0 closed Files rest in the stacks. 0 relics are shelved. "
        "0 personnel records bear amendments."
    )


def test_room_uses_reliquary_and_unsettled_variants(migrated_conn) -> None:
    migrated_conn.execute(
        "INSERT INTO file_history "
        "(title, location, success_threshold, successes, failures, danger, "
        "clue_count, resolution_tier, seed, opened_at) "
        "VALUES ('Closed', 'Stacks', 3, 3, 4, 4, 3, 'failure', 1, 'then')"
    )
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, description) VALUES ('lamp', 'steady')"
    )
    content = load_content()
    lines = ArchiveFlavourService(migrated_conn, content, Rng(2)).describe()
    assert lines[0] in content.fragments.archive_descriptions["reliquary"]
    assert lines[2] in content.fragments.room_moods["unsettled"]
    assert any("1 closed File rests" in line for line in lines)
    assert any("1 relic is shelved" in line for line in lines)


def test_room_lists_relic_name_description_and_effect(migrated_conn) -> None:
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, description, effects_json) VALUES "
        "('moth_eaten_map', 'Routes through places that no longer exist.', "
        "'[{\"type\":\"stat_bonus\",\"amount\":1,"
        "\"tags\":[\"geometry\",\"flood\"]}]')"
    )
    lines = ArchiveFlavourService(
        migrated_conn, load_content(), Rng(1)
    ).describe()
    assert lines[-1] == (
        "Relic: Moth-Eaten Map — Routes through places that no longer exist. "
        "Effect: +1 to stat checks during geometry or flood Files."
    )


def test_personnel_title_is_stable() -> None:
    content = load_content()
    first = personnel_title(content, "player-id", 2, False)
    second = personnel_title(content, "player-id", 2, False)
    assert first == second
    assert first in content.fragments.personnel_titles["active"]


def test_personnel_title_history_categories() -> None:
    content = load_content()
    assert personnel_title(content, "p", 0, False) in content.fragments.personnel_titles["new"]
    assert personnel_title(content, "p", 5, False) in content.fragments.personnel_titles["veteran"]
    assert personnel_title(content, "p", 0, True) in content.fragments.personnel_titles["marked"]
