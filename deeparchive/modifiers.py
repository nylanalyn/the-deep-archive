"""Effective check values from backgrounds, scars, and communal relics."""

from __future__ import annotations

import json
import sqlite3

from deeparchive.content.models import VALID_STATS

BASE_INVESTIGATE_CHANCE = 0.50
GAMBLER_INVESTIGATE_CHANCE = 0.55


class ModifierService:
    """Calculate the effective values used by checks and profiles."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def effective_stat(self, player_id: str, stat: str) -> int:
        if stat not in VALID_STATS:
            raise ValueError(f"unknown stat: {stat}")
        row = self._conn.execute(
            f"SELECT {stat} AS value FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"investigator {player_id!r} no longer exists")
        return int(row["value"]) + self._scar_delta(player_id, stat) + self._relic_bonus()

    def investigate_chance(self, player_id: str) -> float:
        row = self._conn.execute(
            "SELECT background_key FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"investigator {player_id!r} no longer exists")
        if row["background_key"] == "gambler":
            return GAMBLER_INVESTIGATE_CHANCE
        return BASE_INVESTIGATE_CHANCE

    def _scar_delta(self, player_id: str, stat: str) -> int:
        total = 0
        rows = self._conn.execute(
            "SELECT modifiers_json FROM scars WHERE player_id = ?", (player_id,)
        )
        for row in rows:
            modifiers = json.loads(row["modifiers_json"])
            if not isinstance(modifiers, list):
                raise ValueError("scars.modifiers_json must be a list")
            for modifier in modifiers:
                if not isinstance(modifier, dict):
                    raise ValueError("scar modifier must be an object")
                if modifier.get("stat") == stat:
                    delta = modifier.get("delta")
                    if not isinstance(delta, int) or isinstance(delta, bool):
                        raise ValueError("scar modifier delta must be an integer")
                    total += delta
        return total

    def _relic_bonus(self) -> int:
        active = self._conn.execute(
            "SELECT theme_tags_json FROM active_file WHERE id = 1"
        ).fetchone()
        if active is None:
            return 0
        active_tags = set(json.loads(active["theme_tags_json"]))
        total = 0
        for row in self._conn.execute("SELECT effects_json FROM relics"):
            effects = json.loads(row["effects_json"])
            if not isinstance(effects, list):
                raise ValueError("relics.effects_json must be a list")
            for effect in effects:
                if not isinstance(effect, dict):
                    raise ValueError("relic effect must be an object")
                if effect.get("type") != "stat_bonus":
                    continue
                tags = effect.get("tags", [])
                amount = effect.get("amount")
                if (
                    isinstance(tags, list)
                    and active_tags.intersection(tags)
                    and isinstance(amount, int)
                    and not isinstance(amount, bool)
                ):
                    total += amount
        return total
