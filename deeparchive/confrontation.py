"""The final check that closes a ready Sealed File."""

from __future__ import annotations

import sqlite3

from deeparchive.actions import DailyActionLedger
from deeparchive.identity import Player
from deeparchive.modifiers import ModifierService
from deeparchive.resolution import ResolutionService
from deeparchive.rng import Rng

CONFRONT_TARGET = 5


class ConfrontationService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        ledger: DailyActionLedger,
        modifiers: ModifierService,
        resolution: ResolutionService,
        rng: Rng,
    ) -> None:
        self._conn = conn
        self._ledger = ledger
        self._modifiers = modifiers
        self._resolution = resolution
        self._rng = rng

    def confront(self, player: Player) -> list[str]:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT is_sealed, successes, success_threshold FROM active_file "
                "WHERE id = 1"
            ).fetchone()
            if row is None or not row["is_sealed"]:
                self._conn.execute("ROLLBACK")
                return ["The Archive holds no Sealed File for confrontation."]
            if int(row["successes"]) < int(row["success_threshold"]):
                self._conn.execute("ROLLBACK")
                return ["The final leaf remains locked. The Sealed File needs more evidence."]
            allowance = self._ledger.consume(player.id)
            if allowance is None:
                self._conn.execute("ROLLBACK")
                return ["Your allowance is spent. Return after the day turns."]

            best = max(
                self._modifiers.effective_stat(player.id, stat)
                for stat in ("wit", "strength", "occultism")
            )
            victory = self._rng.randint(1, 6) + best >= CONFRONT_TARGET
            if victory:
                self._conn.execute(
                    "UPDATE active_file SET failures = MIN(failures, 2), "
                    "danger = MIN(danger, 2) WHERE id = 1"
                )
            else:
                self._conn.execute(
                    "UPDATE active_file SET failures = 5, danger = 5 WHERE id = 1"
                )
            self._conn.execute(
                "INSERT OR IGNORE INTO active_file_participants (player_id) VALUES (?)",
                (player.id,),
            )
            resolved = self._resolution.resolve_if_ready(
                allow_sealed=True, boss_victory=victory
            )
            if resolved is None:
                raise RuntimeError("ready Sealed File did not resolve")
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        opening = (
            "The final leaf yields. The pattern breaks."
            if victory
            else "The final leaf closes on your hand. The pattern takes its due."
        )
        noun = "action" if allowance.remaining == 1 else "actions"
        return [
            f"{opening} {allowance.remaining} {noun} remain today.",
            *resolved.lines,
        ]
