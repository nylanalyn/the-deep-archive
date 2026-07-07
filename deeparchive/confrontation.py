"""The communal checks that close a ready Sealed File.

A Sealed File is not decided by one die. Each investigator may face it once
per day (spending an action); the arc resolves when either side reaches
:data:`CONFRONT_WINS_NEEDED` results. A solo investigator can still finish an
arc — it just takes them more than one day of standing in front of it.
"""

from __future__ import annotations

import sqlite3

from deeparchive.actions import DailyActionLedger
from deeparchive.content.models import ContentPack
from deeparchive.identity import Player
from deeparchive.modifiers import ModifierService
from deeparchive.resolution import ResolutionService
from deeparchive.rng import Rng

CONFRONT_TARGET = 5
CONFRONT_WINS_NEEDED = 2

# Fallbacks when a content pack ships without a confrontations section.
_DEFAULT_BEATS = {
    "success": ("Your reading holds. The pattern recoils.",),
    "failure": ("The pattern turns your page against you.",),
    "pending": (
        "The Sealed File is not yet decided. The Archive waits for another reader.",
    ),
}


class ConfrontationService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        ledger: DailyActionLedger,
        modifiers: ModifierService,
        resolution: ResolutionService,
        rng: Rng,
        content: ContentPack,
    ) -> None:
        self._conn = conn
        self._ledger = ledger
        self._modifiers = modifiers
        self._resolution = resolution
        self._rng = rng
        self._content = content

    def confront(self, player: Player) -> list[str]:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT is_sealed, successes, success_threshold, "
                "confront_successes, confront_failures FROM active_file "
                "WHERE id = 1"
            ).fetchone()
            if row is None or not row["is_sealed"]:
                self._conn.execute("ROLLBACK")
                return ["The Archive holds no Sealed File for confrontation."]
            if int(row["successes"]) < int(row["success_threshold"]):
                self._conn.execute("ROLLBACK")
                return ["The final leaf remains locked. The Sealed File needs more evidence."]
            day_key = self._ledger.day_key()
            already = self._conn.execute(
                "SELECT 1 FROM active_file_confronts "
                "WHERE player_id = ? AND day_key = ?",
                (player.id, day_key),
            ).fetchone()
            if already is not None:
                self._conn.execute("ROLLBACK")
                return [
                    "You have already faced it today. The pattern remembers "
                    "your handwriting."
                ]
            allowance = self._ledger.consume(player.id)
            if allowance is None:
                self._conn.execute("ROLLBACK")
                return ["Your allowance is spent. Return after the day turns."]

            threshold = int(row["success_threshold"])
            best = max(
                self._modifiers.effective_stat(player.id, stat)
                for stat in ("wit", "strength", "occultism")
            )
            roll = self._rng.randint(1, 6)
            check = roll != 1 and (roll == 6 or roll + best >= CONFRONT_TARGET)
            self._conn.execute(
                "INSERT INTO active_file_confronts (player_id, day_key) "
                "VALUES (?, ?)",
                (player.id, day_key),
            )
            column = "confront_successes" if check else "confront_failures"
            self._conn.execute(
                f"UPDATE active_file SET {column} = {column} + 1 WHERE id = 1"
            )
            wins = int(row["confront_successes"]) + (1 if check else 0)
            losses = int(row["confront_failures"]) + (0 if check else 1)
            self._conn.execute(
                "INSERT OR IGNORE INTO active_file_participants (player_id) VALUES (?)",
                (player.id,),
            )

            beat = self._beat("success" if check else "failure")
            resolved = None
            victory: bool | None = None
            if wins >= CONFRONT_WINS_NEEDED:
                victory = True
                self._conn.execute(
                    "UPDATE active_file SET failures = MIN(failures, 2), "
                    "danger = MIN(danger, 2) WHERE id = 1"
                )
            elif losses >= CONFRONT_WINS_NEEDED:
                victory = False
                # Force the disaster tier: a lost confrontation is the worst
                # thing that can happen to the Archive, and it must read
                # that way (and scar someone) at resolution.
                self._conn.execute(
                    "UPDATE active_file SET failures = ?, danger = ? WHERE id = 1",
                    (threshold, threshold),
                )
            if victory is not None:
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

        noun = "action" if allowance.remaining == 1 else "actions"
        first = f"{beat} {allowance.remaining} {noun} remain today."
        if resolved is None:
            return [first, self._beat("pending")]
        opening = (
            "The final leaf yields. The pattern breaks."
            if victory
            else "The final leaf closes on your hand. The pattern takes its due."
        )
        return [first, opening, *resolved.lines]

    def _beat(self, key: str) -> str:
        lines = self._content.fragments.confrontations.get(key) or _DEFAULT_BEATS[key]
        return self._rng.choice(lines)
