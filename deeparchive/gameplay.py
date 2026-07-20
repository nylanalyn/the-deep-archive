"""Phase 6 action checks and hidden active-File state updates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal, Protocol

from deeparchive.actions import DailyActionLedger
from deeparchive.action_flavour import ActionNarrator
from deeparchive.content.models import ContentPack
from deeparchive.identity import Player
from deeparchive.modifiers import ModifierService
from deeparchive.resolution import ResolutionOutcome, ResolutionService

ActionName = Literal["investigate", "interview", "force", "ritual"]
STAT_CHECK_TARGET = 4

# How much danger a failed action feeds the File. Interviewing a witness
# badly is embarrassing; forcing a sealed door badly is provocation.
DANGER_ON_FAILURE: dict[ActionName, int] = {
    "investigate": 1,
    "interview": 1,
    "force": 2,
    "ritual": 2,
}

# A successful !investigate may steady the File: careful reading bleeds off
# accumulated danger. This is investigate's job — the others make progress
# faster but agitate the File when they slip.
STEADY_CHANCE = 0.5

# Rare complication on !investigate (per SPEC): the evidence looks back.
COMPLICATION_CHANCE = 0.05

# Danger levels at which the Archivist lets the room feel it. Crossing the
# last one makes the File bite: the acting investigator is scarred mid-File.
# Tuned down from (4,8,12)/bite-12: under the old gentle stat spreads danger
# rarely passed 7, so scars almost never landed. With the sharper class
# spreads, off-class attempts fail far more and danger climbs — these lower
# thresholds let the File actually bite, making scars the visible receipt the
# game was missing.
OMEN_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (3, "rising"),
    (6, "high"),
    (8, "critical"),
)
BITE_DANGER = 8


class RandomSource(Protocol):
    def randint(self, low: int, high: int) -> int: ...

    def chance(self, probability: float) -> bool: ...

    def choice(self, seq): ...


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action: ActionName
    success: bool | None
    remaining_actions: int
    resolution: ResolutionOutcome | None = None
    blocked_message: str | None = None
    confront_unlocked: bool = False
    attempt_text: str | None = None
    result_text: str | None = None
    extra_lines: tuple[str, ...] = field(default=())


_ACTION_STATS: dict[ActionName, str | None] = {
    "investigate": None,
    "interview": "wit",
    "force": "strength",
    "ritual": "occultism",
}

class GameplayService:
    """Resolve player actions without exposing rolls or File thresholds."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        ledger: DailyActionLedger,
        rng: RandomSource,
        resolution: ResolutionService,
        modifiers: ModifierService,
        narrator: ActionNarrator,
        content: ContentPack,
    ) -> None:
        self._conn = conn
        self._ledger = ledger
        self._rng = rng
        self._resolution = resolution
        self._modifiers = modifiers
        self._narrator = narrator
        self._content = content

    def perform(self, player: Player, action: ActionName) -> ActionOutcome | None:
        if action not in _ACTION_STATS:
            raise ValueError(f"unknown action: {action}")

        try:
            self._conn.execute("BEGIN IMMEDIATE")
            ready = self._resolution.resolve_if_ready()
            if ready is not None:
                remaining = self._ledger.allowance(player.id).remaining
                self._conn.execute("COMMIT")
                return ActionOutcome(action, None, remaining, ready)
            if self._resolution.awaiting_confrontation():
                remaining = self._ledger.allowance(player.id).remaining
                self._conn.execute("ROLLBACK")
                return ActionOutcome(
                    action,
                    None,
                    remaining,
                    blocked_message=(
                        "The Sealed File is ready. The Archivist unlocks the final "
                        "leaf: !confront."
                    ),
                )
            allowance = self._ledger.consume(player.id)
            if allowance is None:
                self._conn.execute("ROLLBACK")
                return None

            disposition = (
                0
                if _ACTION_STATS[action] is None
                else self._modifiers.action_disposition(action)
            )
            success = self._roll(player, action, disposition)
            attempt_text = self._narrator.attempt(action)
            result_text = self._narrator.result(action, success)
            danger_before = self._current_danger()
            if success:
                update = self._conn.execute(
                    "UPDATE active_file SET successes = successes + 1, "
                    "clue_count = clue_count + 1 WHERE id = 1"
                )
            else:
                # A favoured approach agitates the File less when it slips; a
                # resisted one provokes it. Failing is never free.
                danger_gain = max(1, DANGER_ON_FAILURE[action] - disposition)
                update = self._conn.execute(
                    "UPDATE active_file SET failures = failures + 1, "
                    "danger = danger + ? WHERE id = 1",
                    (danger_gain,),
                )
            if update.rowcount != 1:
                raise RuntimeError("no active File to receive action outcome")

            extra_lines: list[str] = []
            if success:
                extra_lines.extend(self._clue_reveals())
            if action == "investigate":
                extra_lines.extend(self._investigate_extras(success, danger_before))
            extra_lines.extend(self._danger_transition(player, danger_before))

            self._conn.execute(
                "INSERT OR IGNORE INTO active_file_participants (player_id) VALUES (?)",
                (player.id,),
            )
            resolution = self._resolution.resolve_if_ready()
            confront_unlocked = self._resolution.awaiting_confrontation()
            self._conn.execute("COMMIT")
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        return ActionOutcome(
            action=action,
            success=success,
            remaining_actions=allowance.remaining,
            resolution=resolution,
            confront_unlocked=confront_unlocked,
            attempt_text=attempt_text,
            result_text=result_text,
            extra_lines=tuple(extra_lines),
        )

    def _roll(self, player: Player, action: ActionName, disposition: int) -> bool:
        stat = _ACTION_STATS[action]
        if stat is None:
            return self._rng.chance(self._modifiers.investigate_chance(player.id))
        effective = self._modifiers.effective_stat(player.id, stat) + disposition
        roll = self._rng.randint(1, 6)
        # A natural 1 always fails and a natural 6 always succeeds: no stack
        # of relics makes an investigator infallible, and no stat spread
        # leaves one hopeless.
        if roll == 1:
            return False
        if roll == 6:
            return True
        return roll + effective >= STAT_CHECK_TARGET

    def _clue_reveals(self) -> list[str]:
        """The clues this success surfaces.

        A File carries an ordered clue track (arc clues for a Sealed File, else
        the theme's). The N clues are spread evenly across the hidden success
        threshold, so the room assembles the little mystery as it works and the
        last clue — written as the answer — lands as the File nears its close.
        A File with no clue track (minimal packs) reveals nothing.
        """
        row = self._conn.execute(
            "SELECT successes, success_threshold, theme_key, arc_key "
            "FROM active_file WHERE id = 1"
        ).fetchone()
        if row is None:
            return []
        clues = self._file_clues(row["arc_key"], str(row["theme_key"]))
        threshold = int(row["success_threshold"])
        if not clues or threshold < 1:
            return []
        successes = int(row["successes"])
        count = len(clues)
        # Reveal any clue whose evenly-spaced boundary this success just crossed.
        # count <= threshold, so at most one clue surfaces per action.
        upto = min(successes * count // threshold, count)
        already = (successes - 1) * count // threshold
        return [clues[index] for index in range(already, upto)]

    def _file_clues(self, arc_key, theme_key: str) -> tuple[str, ...]:
        if arc_key is not None:
            arc = self._content.meta_arcs.get(str(arc_key))
            if arc is not None:
                return arc.clues
        theme = self._content.themes.get(theme_key)
        return theme.clues if theme is not None else ()

    def _current_danger(self) -> int:
        row = self._conn.execute(
            "SELECT danger FROM active_file WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("no active File to receive action outcome")
        return int(row["danger"])

    def _investigate_extras(self, success: bool, danger_before: int) -> list[str]:
        """Apply !investigate's side effects: steadying and complications."""
        lines: list[str] = []
        if success and danger_before > 0 and self._rng.chance(STEADY_CHANCE):
            self._conn.execute(
                "UPDATE active_file SET danger = MAX(danger - 1, 0) WHERE id = 1"
            )
            steadied = self._content.fragments.danger_omens.get("steadied")
            if steadied:
                lines.append(self._rng.choice(steadied))
        if self._rng.chance(COMPLICATION_CHANCE):
            self._conn.execute(
                "UPDATE active_file SET danger = danger + 1 WHERE id = 1"
            )
            complication = self._content.fragments.danger_omens.get("complication")
            if complication:
                lines.append(self._rng.choice(complication))
        return lines

    def _danger_transition(self, player: Player, danger_before: int) -> list[str]:
        """Narrate crossed danger thresholds; at the last one the File bites."""
        danger_after = self._current_danger()
        lines: list[str] = []
        for bound, key in OMEN_THRESHOLDS:
            if danger_before < bound <= danger_after:
                omens = self._content.fragments.danger_omens.get(key)
                if omens:
                    lines.append(self._rng.choice(omens))
        if danger_before < BITE_DANGER <= danger_after:
            bite = self._bite(player)
            if bite is not None:
                lines.append(bite)
        return lines

    def _bite(self, player: Player) -> str | None:
        """Scar the acting investigator mid-File. Returns the amendment line."""
        owned = {
            str(row["scar_key"])
            for row in self._conn.execute(
                "SELECT scar_key FROM scars WHERE player_id = ?", (player.id,)
            )
        }
        candidates = [
            scar
            for scar in self._content.scars.values()
            if scar.key not in owned
        ]
        if not candidates:
            return None
        scar = self._rng.choice(candidates)
        modifiers = [
            {"stat": modifier.stat, "delta": modifier.delta}
            for modifier in scar.modifiers
        ]
        self._conn.execute(
            "INSERT INTO scars "
            "(player_id, scar_key, modifiers_json, description, source_file_id) "
            "VALUES (?, ?, ?, ?, NULL)",
            (player.id, scar.key, json.dumps(modifiers), scar.description),
        )
        return (
            f"The File bites. The personnel file for {player.display_nick} "
            f"is amended: {scar.name}."
        )

    @staticmethod
    def render(outcome: ActionOutcome | None) -> list[str]:
        if outcome is None:
            return ["Your allowance is spent. Return after the day turns."]
        if outcome.blocked_message is not None:
            return [outcome.blocked_message]
        if outcome.success is None:
            if outcome.resolution is None:
                raise RuntimeError("resolution guard produced no resolution")
            return list(outcome.resolution.lines)
        if outcome.attempt_text is None or outcome.result_text is None:
            raise RuntimeError("completed action is missing narration")
        noun = "action" if outcome.remaining_actions == 1 else "actions"
        label = "SUCCESS" if outcome.success else "FAILURE"
        lines = [
            outcome.attempt_text,
            f"{label} — {outcome.result_text} "
            f"{outcome.remaining_actions} {noun} remain today.",
        ]
        lines.extend(outcome.extra_lines)
        if outcome.resolution is not None:
            lines.extend(outcome.resolution.lines)
        elif outcome.confront_unlocked:
            lines.append(
                "The Sealed File's final leaf unlocks. The Archive permits: !confront."
            )
            # State the stake plainly: a lost confrontation costs the Archive a
            # relic and scars a reader. Fear is what brings the room back.
            lines.append(
                "Break the pattern and the Archive gives up a truth; fail it and "
                "the sealed shelves keep what you came for."
            )
        return lines
