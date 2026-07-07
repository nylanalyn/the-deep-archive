"""Daily action limits and configured day-boundary behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deeparchive.actions import DailyActionLedger
from deeparchive.identity import IdentityResolver


def test_allowance_defaults_to_five(migrated_conn, background_assigner) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    allowance = DailyActionLedger(migrated_conn).allowance(player.id)
    assert allowance.used == 0
    assert allowance.remaining == 5


def test_sixth_action_is_rejected(migrated_conn, background_assigner) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    ledger = DailyActionLedger(migrated_conn)
    for remaining in (4, 3, 2, 1, 0):
        allowance = ledger.consume(player.id)
        assert allowance is not None
        assert allowance.remaining == remaining
    assert ledger.consume(player.id) is None


def test_configured_timezone_controls_day_rollover(
    migrated_conn, background_assigner
) -> None:
    player = IdentityResolver(migrated_conn, background_assigner).resolve_identity("alice", None)
    now = [datetime(2026, 7, 7, 3, 30, tzinfo=timezone.utc)]
    ledger = DailyActionLedger(
        migrated_conn,
        timezone_name="America/New_York",
        clock=lambda: now[0],
    )
    assert ledger.day_key() == "2026-07-06"
    allowance = ledger.consume(player.id)
    assert allowance is not None and allowance.remaining == 4

    now[0] = datetime(2026, 7, 7, 4, 30, tzinfo=timezone.utc)
    assert ledger.day_key() == "2026-07-07"
    assert ledger.allowance(player.id).remaining == 5


def test_naive_clock_is_rejected(migrated_conn) -> None:
    ledger = DailyActionLedger(
        migrated_conn, clock=lambda: datetime(2026, 1, 1)
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.day_key()
