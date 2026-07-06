"""Phase 6 action checks and hidden active-File state updates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from deeparchive.actions import DailyActionLedger
from deeparchive.identity import Player

ActionName = Literal["investigate", "interview", "force", "ritual"]
STAT_CHECK_TARGET = 4


class RandomSource(Protocol):
    def randint(self, low: int, high: int) -> int: ...

    def chance(self, probability: float) -> bool: ...


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action: ActionName
    success: bool
    remaining_actions: int


_ACTION_STATS: dict[ActionName, str | None] = {
    "investigate": None,
    "interview": "wit",
    "force": "strength",
    "ritual": "occultism",
}

_SUCCESS_TEXT: dict[ActionName, str] = {
    "investigate": "A useful notation emerges from the catalogue's margins.",
    "interview": "The witness corrects the record. Something useful remains.",
    "force": "The sealed way yields, reluctantly.",
    "ritual": "The pattern settles into a shape the Archive can record.",
}

_FAILURE_TEXT: dict[ActionName, str] = {
    "investigate": "The trail ends at a shelf with no call number.",
    "interview": "The account contradicts itself, then falls silent.",
    "force": "Something beyond the door pushes back.",
    "ritual": "The circle holds, but not in the way you intended.",
}


class GameplayService:
    """Resolve player actions without exposing rolls or File thresholds."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        ledger: DailyActionLedger,
        rng: RandomSource,
    ) -> None:
        self._conn = conn
        self._ledger = ledger
        self._rng = rng

    def perform(self, player: Player, action: ActionName) -> ActionOutcome | None:
        if action not in _ACTION_STATS:
            raise ValueError(f"unknown action: {action}")

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            allowance = self._ledger.consume(player.id)
            if allowance is None:
                self._conn.execute("ROLLBACK")
                return None

            success = self._roll(player, action)
            if success:
                update = self._conn.execute(
                    "UPDATE active_file SET successes = successes + 1, "
                    "clue_count = clue_count + 1 WHERE id = 1"
                )
            else:
                update = self._conn.execute(
                    "UPDATE active_file SET failures = failures + 1, "
                    "danger = danger + 1 WHERE id = 1"
                )
            if update.rowcount != 1:
                raise RuntimeError("no active File to receive action outcome")
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        return ActionOutcome(
            action=action,
            success=success,
            remaining_actions=allowance.remaining,
        )

    def _roll(self, player: Player, action: ActionName) -> bool:
        stat = _ACTION_STATS[action]
        if stat is None:
            return self._rng.chance(0.5)
        row = self._conn.execute(
            f"SELECT {stat} AS value FROM players WHERE id = ?", (player.id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"investigator {player.id!r} no longer exists")
        return self._rng.randint(1, 6) + int(row["value"]) >= STAT_CHECK_TARGET

    @staticmethod
    def render(outcome: ActionOutcome | None) -> list[str]:
        if outcome is None:
            return ["Your allowance is spent. Return after the day turns."]
        text = (
            _SUCCESS_TEXT[outcome.action]
            if outcome.success
            else _FAILURE_TEXT[outcome.action]
        )
        noun = "action" if outcome.remaining_actions == 1 else "actions"
        return [f"{text} {outcome.remaining_actions} {noun} remain today."]
