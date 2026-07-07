"""Atomic active-File resolution, consequences, and replacement."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from deeparchive.content.models import ContentPack, RelicDefinition, ScarDefinition
from deeparchive.files import ActiveFile, FileGenerator
from deeparchive.meta import MetaArcService
from deeparchive.rng import Rng

REWARD_TIERS = frozenset({"partial_success", "success", "clean_success"})
SCAR_TIERS = frozenset({"disaster", "failure", "mixed_failure"})


def resolution_tier(failures: int, danger: int, threshold: int = 5) -> str:
    """Map consequences to a tier relative to the File's required progress."""
    if threshold < 1:
        raise ValueError("resolution threshold must be positive")
    penalty = max(failures, danger)
    # Normalize to the original five-step consequence scale. Longer Files can
    # absorb proportionally more failed actions without becoming automatic
    # disasters merely because they took longer to investigate.
    scaled_penalty = (penalty * 5 + threshold - 1) // threshold
    return (
        "clean_success",
        "success",
        "partial_success",
        "mixed_failure",
        "failure",
        "disaster",
    )[min(scaled_penalty, 5)]


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    tier: str
    closed_title: str
    next_file: ActiveFile
    lines: tuple[str, ...]


class ResolutionService:
    """Resolve a ready File inside the caller's open transaction."""

    def __init__(self, conn: sqlite3.Connection, content: ContentPack, rng: Rng) -> None:
        self._conn = conn
        self._content = content
        self._rng = rng
        self._generator = FileGenerator(content, rng)
        self._meta = MetaArcService(conn, content, rng)

    def awaiting_confrontation(self) -> bool:
        row = self._conn.execute(
            "SELECT is_sealed, successes, success_threshold FROM active_file WHERE id = 1"
        ).fetchone()
        return bool(
            row is not None
            and row["is_sealed"]
            and int(row["successes"]) >= int(row["success_threshold"])
        )

    def resolve_if_ready(
        self, *, allow_sealed: bool = False, boss_victory: bool | None = None
    ) -> ResolutionOutcome | None:
        row = self._conn.execute("SELECT * FROM active_file WHERE id = 1").fetchone()
        if row is None or int(row["successes"]) < int(row["success_threshold"]):
            return None
        is_sealed = bool(row["is_sealed"])
        if is_sealed and not allow_sealed:
            return None

        tier = resolution_tier(
            int(row["failures"]),
            int(row["danger"]),
            int(row["success_threshold"]),
        )
        cursor = self._conn.execute(
            "INSERT INTO file_history "
            "(title, location, theme_tags_json, success_threshold, successes, "
            "failures, danger, clue_count, resolution_tier, seed, opened_at, "
            "is_sealed, arc_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["title"], row["location"], row["theme_tags_json"],
                row["success_threshold"], row["successes"], row["failures"],
                row["danger"], row["clue_count"], tier, row["seed"], row["opened_at"],
                int(is_sealed), row["arc_key"],
            ),
        )
        history_id = int(cursor.lastrowid)
        participants = [
            str(item["player_id"])
            for item in self._conn.execute(
                "SELECT player_id FROM active_file_participants ORDER BY player_id"
            )
        ]
        if participants:
            placeholders = ",".join("?" for _ in participants)
            self._conn.execute(
                f"UPDATE players SET completed_files = completed_files + 1 "
                f"WHERE id IN ({placeholders})",
                participants,
            )

        observation = None if is_sealed else self._meta.observe_theme(str(row["theme_key"]))
        lines = [self._rng.choice(self._content.fragments.resolution_tiers[tier])]
        if observation is not None and observation.hint is not None:
            lines.append(observation.hint)
        relic = self._award_relic(tier, json.loads(row["theme_tags_json"]), history_id)
        if relic is not None:
            lines.append(f"Relic shelved: {relic.name}. {relic.description}")
        scar = self._assign_scar(tier, participants, history_id)
        if scar is not None:
            nick, definition = scar
            lines.append(f"The personnel file for {nick} is amended: {definition.name}.")

        if is_sealed and row["arc_key"]:
            arc_key = str(row["arc_key"])
            victory = bool(boss_victory)
            if victory:
                reward = self._meta.victory_reward(arc_key, history_id)
                if reward:
                    lines.append(f"The Archive accepts a permanent addition: {reward}.")
            else:
                stolen = self._meta.steal_relic()
                if stolen:
                    lines.append(f"The sealed shelves retain the {stolen}.")
            self._meta.complete(arc_key, victory)

        return_key = self._return_key(tier)
        lines.append(self._rng.choice(self._content.fragments.archive_returns[return_key]))
        self._conn.execute("DELETE FROM active_file_participants")
        self._conn.execute("DELETE FROM active_file WHERE id = 1")
        revealed_arc = observation.revealed if observation is not None else None
        next_file = (
            self._meta.sealed_file(revealed_arc)
            if revealed_arc is not None
            else self._generator.generate()
        )
        self._insert_active(next_file)
        next_label = "New Sealed File" if next_file.is_sealed else "New File"
        lines.extend(
            (
                f"{next_label}: {next_file.title} — {next_file.location}.",
                next_file.opening_text,
            )
        )
        return ResolutionOutcome(
            tier=tier,
            closed_title=str(row["title"]),
            next_file=next_file,
            lines=tuple(lines),
        )

    def _return_key(self, tier: str) -> str:
        if tier in {"clean_success", "success"}:
            key = "success"
        elif tier in {"mixed_failure", "failure"}:
            key = "failure"
        elif tier == "disaster":
            key = "disaster"
        else:
            key = "default"
        if key not in self._content.fragments.archive_returns:
            return "default"
        return key

    def _award_relic(
        self, tier: str, theme_tags: list[str], history_id: int
    ) -> RelicDefinition | None:
        if tier not in REWARD_TIERS:
            return None
        owned = {
            str(row["relic_key"])
            for row in self._conn.execute("SELECT relic_key FROM relics")
        }
        candidates = [
            relic
            for relic in self._content.relics.values()
            if relic.key not in owned and set(relic.tags).intersection(theme_tags)
        ]
        if not candidates:
            return None
        relic = self._rng.choice(candidates)
        effects = [
            {"type": effect.type, "amount": effect.amount, "tags": list(effect.tags)}
            for effect in relic.effects
        ]
        self._conn.execute(
            "INSERT INTO relics "
            "(relic_key, theme_tags_json, effects_json, description, source_file_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                relic.key, json.dumps(list(relic.tags)), json.dumps(effects),
                relic.description, history_id,
            ),
        )
        return relic

    def _assign_scar(
        self, tier: str, participants: list[str], history_id: int
    ) -> tuple[str, ScarDefinition] | None:
        if tier not in SCAR_TIERS or not participants:
            return None
        player_id = self._rng.choice(participants)
        scar = self._rng.choice(tuple(self._content.scars.values()))
        modifiers = [
            {"stat": modifier.stat, "delta": modifier.delta}
            for modifier in scar.modifiers
        ]
        self._conn.execute(
            "INSERT INTO scars "
            "(player_id, scar_key, modifiers_json, description, source_file_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                player_id, scar.key, json.dumps(modifiers), scar.description, history_id,
            ),
        )
        row = self._conn.execute(
            "SELECT display_nick FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        return str(row["display_nick"]), scar

    def _insert_active(self, active: ActiveFile) -> None:
        self._conn.execute(
            "INSERT INTO active_file "
            "(id, seed, title, location, theme_tags_json, success_threshold, "
            "theme_key, opening_text, is_sealed, arc_key) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                active.seed, active.title, active.location,
                json.dumps(list(active.theme_tags)), active.success_threshold,
                active.theme_key, active.opening_text,
                int(active.is_sealed), active.arc_key,
            ),
        )
