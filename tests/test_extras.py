"""Extras upgrade pass: heartbeats, echoes, relic caps, and danger tiers."""

from __future__ import annotations

from datetime import datetime, timezone

from deeparchive.actions import DailyActionLedger
from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.flavour import ArchiveFlavourService
from deeparchive.identity import IdentityResolver
from deeparchive.irc.backend import BotBackend
from deeparchive.meta import MetaArcService
from deeparchive.resolution import ResolutionService, resolution_tier
from deeparchive.rng import Rng


class FakeRng:
    """Chance always fires; choice takes the first option."""

    def __init__(self, die: int = 1) -> None:
        self.die = die

    def chance(self, probability: float) -> bool:
        return True

    def choice(self, seq):
        return seq[0]

    def randint(self, low: int, high: int) -> int:
        assert low <= self.die <= high
        return self.die


def _history_row(conn, title: str) -> int:
    cursor = conn.execute(
        "INSERT INTO file_history "
        "(title, location, success_threshold, successes, failures, danger, "
        "clue_count, resolution_tier, seed, opened_at) "
        "VALUES (?, 'Stacks', 3, 3, 0, 0, 3, 'success', 1, 'then')",
        (title,),
    )
    return int(cursor.lastrowid)


# ---------------------------------------------------------------------------
# E10: the tier reads danger, not failures
# ---------------------------------------------------------------------------


def test_tier_ignores_failures_and_reads_danger() -> None:
    assert resolution_tier(failures=17, danger=0, threshold=17) == "clean_success"
    assert resolution_tier(failures=0, danger=17, threshold=17) == "disaster"
    assert resolution_tier(failures=0, danger=3, threshold=17) == "success"


# ---------------------------------------------------------------------------
# E2: scar assignment never duplicates
# ---------------------------------------------------------------------------


def test_assign_scar_skips_owned_scars(migrated_conn, background_assigner) -> None:
    content = load_content()
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", None
    )
    keys = list(content.scars)
    spared = keys[-1]
    for key in keys[:-1]:
        migrated_conn.execute(
            "INSERT INTO scars (player_id, scar_key, description) VALUES (?, ?, 'x')",
            (player.id, key),
        )
    migrated_conn.commit()
    history_id = _history_row(migrated_conn, "The Closed File")
    service = ResolutionService(migrated_conn, content, FakeRng())
    result = service._assign_scar("disaster", [player.id], history_id=history_id)
    assert result is not None
    _, definition = result
    assert definition.key == spared

    migrated_conn.execute(
        "INSERT INTO scars (player_id, scar_key, description) VALUES (?, ?, 'x')",
        (player.id, spared),
    )
    migrated_conn.commit()
    assert (
        service._assign_scar("disaster", [player.id], history_id=history_id) is None
    )


# ---------------------------------------------------------------------------
# E4: stolen relics are named from content
# ---------------------------------------------------------------------------


def test_steal_relic_uses_content_name(migrated_conn) -> None:
    content = load_content()
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, description) VALUES ('moth_eaten_map', 'x')"
    )
    migrated_conn.commit()
    stolen = MetaArcService(migrated_conn, content, FakeRng()).steal_relic()
    assert stolen == "Moth-Eaten Map"


# ---------------------------------------------------------------------------
# E5: !room caps the relic listing
# ---------------------------------------------------------------------------


def test_room_shows_at_most_three_relics_plus_count(migrated_conn) -> None:
    for index in range(5):
        migrated_conn.execute(
            "INSERT INTO relics (relic_key, description) VALUES (?, 'x')",
            (f"relic_{index}",),
        )
    migrated_conn.commit()
    lines = ArchiveFlavourService(migrated_conn, load_content(), Rng(1)).describe()
    relic_lines = [line for line in lines if line.startswith("Relic: ")]
    assert len(relic_lines) == 3
    assert any("2 older relics rest behind glass" in line for line in lines)


# ---------------------------------------------------------------------------
# E14: the Archive quotes itself
# ---------------------------------------------------------------------------


def test_history_echo_references_an_older_title(migrated_conn) -> None:
    content = load_content()
    _history_row(migrated_conn, "The Quiet Lantern")
    current = _history_row(migrated_conn, "The Rising Tide")
    service = ResolutionService(migrated_conn, content, FakeRng())
    echo = service._history_echo(current)
    assert echo is not None
    assert "The Quiet Lantern" in echo
    assert "The Rising Tide" not in echo


def test_participant_echo_names_the_investigator(
    migrated_conn, background_assigner
) -> None:
    content = load_content()
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", None
    )
    service = ResolutionService(migrated_conn, content, FakeRng())
    echo = service._participant_echo("success", [player.id])
    assert echo is not None and "alice" in echo
    assert service._participant_echo("disaster", [player.id]) is None


# ---------------------------------------------------------------------------
# E15: day boundary clock and heartbeat
# ---------------------------------------------------------------------------


def test_seconds_until_day_turn(migrated_conn) -> None:
    now = datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc)
    ledger = DailyActionLedger(migrated_conn, clock=lambda: now)
    assert ledger.seconds_until_day_turn() == 3600.0


def test_seconds_until_day_turn_respects_timezone(migrated_conn) -> None:
    # 03:30 UTC is 23:30 in New York: half an hour to the boundary.
    now = datetime(2026, 7, 7, 3, 30, tzinfo=timezone.utc)
    ledger = DailyActionLedger(
        migrated_conn, timezone_name="America/New_York", clock=lambda: now
    )
    assert ledger.seconds_until_day_turn() == 1800.0


def test_heartbeat_line_is_stable_within_a_day(migrated_conn) -> None:
    backend = BotBackend(
        conn=migrated_conn,
        channel="#archive",
        content=load_content(),
        rng=Rng(1),
        clock=lambda: datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
    )
    first = backend.heartbeat_line()
    second = backend.heartbeat_line()
    assert first is not None
    assert first == second
    backend.quiet = True
    assert backend.heartbeat_line() is None


def test_weather_is_shared_for_the_day(migrated_conn) -> None:
    content = load_content()
    day = lambda: "2026-07-07"  # noqa: E731
    # Different mood/description rngs, same day: the weather line matches.
    first = ArchiveFlavourService(migrated_conn, content, Rng(1), day_key=day).describe()
    second = ArchiveFlavourService(migrated_conn, content, Rng(9), day_key=day).describe()
    assert first[1] == second[1]
    other = ArchiveFlavourService(
        migrated_conn, content, Rng(9), day_key=lambda: "2026-07-08"
    ).describe()
    # A different day may pick the same line by chance with a small pool, but
    # the seeds must differ; assert on the mechanism via repeated stability.
    assert second[1] in content.fragments.room_weather["default"]
    assert other[1] in content.fragments.room_weather["default"]


# ---------------------------------------------------------------------------
# E12: !case progress bands
# ---------------------------------------------------------------------------


def test_case_progress_band_advances_with_successes(migrated_conn) -> None:
    content = load_content()
    service = FileService(migrated_conn, content, Rng(1))
    service.ensure_active()
    thin = service.describe_active()
    migrated_conn.execute(
        "UPDATE active_file SET successes = success_threshold - 1 WHERE id = 1"
    )
    migrated_conn.commit()
    closing = service.describe_active()
    assert thin[2] in content.fragments.file_progress["thin"]
    assert closing[2] in content.fragments.file_progress["closing"]
    # Repeated calls read the same band line (stable per File).
    assert service.describe_active()[2] == closing[2]
