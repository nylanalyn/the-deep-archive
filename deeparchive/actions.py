"""Daily action accounting at the Archive's configured day boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_ACTIONS_PER_DAY = 5


@dataclass(frozen=True, slots=True)
class ActionAllowance:
    day_key: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class DailyActionLedger:
    """Count player actions by calendar day in one global timezone."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timezone_name: str = "UTC",
        limit: int = DEFAULT_ACTIONS_PER_DAY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("daily action limit must be positive")
        self._conn = conn
        self._timezone = ZoneInfo(timezone_name)
        self._limit = limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def limit(self) -> int:
        return self._limit

    def day_key(self) -> str:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("action clock must return a timezone-aware datetime")
        return now.astimezone(self._timezone).date().isoformat()

    def seconds_until_day_turn(self) -> float:
        """Seconds until the next day boundary in the configured timezone.

        Never returns less than 1.0, so schedulers sleeping on this value
        cannot spin when called exactly on the boundary.
        """
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("action clock must return a timezone-aware datetime")
        local = now.astimezone(self._timezone)
        next_turn = datetime.combine(
            local.date() + timedelta(days=1), time.min, tzinfo=self._timezone
        )
        return max(1.0, (next_turn - local).total_seconds())

    def allowance(self, player_id: str) -> ActionAllowance:
        key = self.day_key()
        row = self._conn.execute(
            "SELECT actions_used FROM daily_actions "
            "WHERE player_id = ? AND day_key = ?",
            (player_id, key),
        ).fetchone()
        used = int(row["actions_used"]) if row is not None else 0
        return ActionAllowance(day_key=key, used=used, limit=self._limit)

    def consume(self, player_id: str) -> ActionAllowance | None:
        """Consume one action inside the caller's transaction.

        Returns the resulting allowance, or ``None`` when the player is
        already at the limit. This method deliberately does not commit so the
        action and its File-state outcome can be atomic.
        """
        key = self.day_key()
        self._conn.execute(
            "INSERT OR IGNORE INTO daily_actions (player_id, day_key, actions_used) "
            "VALUES (?, ?, 0)",
            (player_id, key),
        )
        cursor = self._conn.execute(
            "UPDATE daily_actions SET actions_used = actions_used + 1 "
            "WHERE player_id = ? AND day_key = ? AND actions_used < ?",
            (player_id, key, self._limit),
        )
        if cursor.rowcount != 1:
            return None
        return self.allowance(player_id)
