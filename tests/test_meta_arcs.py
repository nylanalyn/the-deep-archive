"""Hidden recurring patterns, Sealed Files, and confrontation outcomes."""

from __future__ import annotations

from deeparchive.actions import DailyActionLedger
from deeparchive.confrontation import ConfrontationService
from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.identity import IdentityResolver
from deeparchive.meta import MetaArcService
from deeparchive.modifiers import ModifierService
from deeparchive.resolution import ResolutionService
from deeparchive.rng import Rng


class FixedDie:
    def __init__(self, value: int) -> None:
        self.value = value

    def randint(self, low: int, high: int) -> int:
        assert low <= self.value <= high
        return self.value


def _resolve_darkness(migrated_conn, service: ResolutionService):
    migrated_conn.execute(
        "UPDATE active_file SET theme_key = 'darkness', "
        "theme_tags_json = '[\"darkness\"]', successes = success_threshold "
        "WHERE id = 1"
    )
    migrated_conn.commit()
    migrated_conn.execute("BEGIN IMMEDIATE")
    outcome = service.resolve_if_ready()
    assert outcome is not None
    migrated_conn.execute("COMMIT")
    return outcome


def test_third_recurring_theme_reveals_sealed_file(migrated_conn) -> None:
    content = load_content()
    FileService(migrated_conn, content, Rng(1)).ensure_active()
    resolution = ResolutionService(migrated_conn, content, Rng(2))
    first = _resolve_darkness(migrated_conn, resolution)
    second = _resolve_darkness(migrated_conn, resolution)
    hints = content.meta_arcs["black_index"].hints
    assert hints[0] in first.lines
    assert hints[1] in second.lines
    assert not migrated_conn.execute(
        "SELECT is_sealed FROM active_file"
    ).fetchone()[0]
    _resolve_darkness(migrated_conn, resolution)
    row = migrated_conn.execute(
        "SELECT is_sealed, arc_key, title FROM active_file"
    ).fetchone()
    assert row["is_sealed"] == 1
    assert row["arc_key"] == "black_index"
    assert row["title"] == content.meta_arcs["black_index"].title


def _ready_sealed(migrated_conn, background_assigner):
    content = load_content()
    FileService(migrated_conn, content, Rng(1)).ensure_active()
    arc = content.meta_arcs["black_index"]
    migrated_conn.execute(
        "UPDATE active_file SET is_sealed = 1, arc_key = ?, theme_key = ?, "
        "theme_tags_json = ?, success_threshold = 1, successes = 1 WHERE id = 1",
        (arc.key, arc.theme_key, '["darkness","void","sealed"]'),
    )
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity(
        "alice", None
    )
    migrated_conn.commit()
    return content, player


def test_confrontation_victory_shelves_permanent_reward(
    migrated_conn, background_assigner
) -> None:
    content, player = _ready_sealed(migrated_conn, background_assigner)
    resolution = ResolutionService(migrated_conn, content, Rng(3))
    service = ConfrontationService(
        migrated_conn,
        DailyActionLedger(migrated_conn),
        ModifierService(migrated_conn),
        resolution,
        FixedDie(6),  # type: ignore[arg-type]
    )
    lines = service.confront(player)
    assert any("permanent addition" in line for line in lines)
    reward_key = content.meta_arcs["black_index"].reward_key
    assert migrated_conn.execute(
        "SELECT COUNT(*) FROM relics WHERE relic_key = ?", (reward_key,)
    ).fetchone()[0] == 1
    assert MetaArcService(migrated_conn, content, Rng(1)).state()["victories"]["black_index"] == 1


def test_confrontation_defeat_steals_relic_and_records_defeat(
    migrated_conn, background_assigner
) -> None:
    content, player = _ready_sealed(migrated_conn, background_assigner)
    migrated_conn.execute(
        "UPDATE players SET wit = 0, strength = 0, occultism = 0 WHERE id = ?",
        (player.id,),
    )
    migrated_conn.execute(
        "INSERT INTO relics (relic_key, description) VALUES ('old_lamp', 'old')"
    )
    migrated_conn.commit()
    resolution = ResolutionService(migrated_conn, content, Rng(3))
    service = ConfrontationService(
        migrated_conn,
        DailyActionLedger(migrated_conn),
        ModifierService(migrated_conn),
        resolution,
        FixedDie(1),  # type: ignore[arg-type]
    )
    lines = service.confront(player)
    assert any("takes its due" in line for line in lines)
    assert migrated_conn.execute("SELECT COUNT(*) FROM relics").fetchone()[0] == 0
    assert migrated_conn.execute("SELECT COUNT(*) FROM scars").fetchone()[0] == 1
    assert MetaArcService(migrated_conn, content, Rng(1)).state()["defeats"]["black_index"] == 1


def test_confront_before_evidence_does_not_consume_action(
    migrated_conn, background_assigner
) -> None:
    content, player = _ready_sealed(migrated_conn, background_assigner)
    migrated_conn.execute("UPDATE active_file SET successes = 0 WHERE id = 1")
    migrated_conn.commit()
    ledger = DailyActionLedger(migrated_conn)
    service = ConfrontationService(
        migrated_conn,
        ledger,
        ModifierService(migrated_conn),
        ResolutionService(migrated_conn, content, Rng(3)),
        FixedDie(6),  # type: ignore[arg-type]
    )
    assert "needs more evidence" in service.confront(player)[0]
    assert ledger.allowance(player.id).used == 0
