"""Short, content-driven descriptions of the persistent Archive."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Protocol

from deeparchive.content.models import ContentPack

class ChoiceSource(Protocol):
    def choice(self, seq): ...


class ArchiveFlavourService:
    """Compose `!room` output from fragments and accumulated history."""

    def __init__(self, conn: sqlite3.Connection, content: ContentPack, rng: ChoiceSource):
        self._conn = conn
        self._fragments = content.fragments
        self._rng = rng
        self._relic_names = {
            key: relic.name for key, relic in content.relics.items()
        }
        self._relic_names.update(
            {arc.reward_key: arc.reward_name for arc in content.meta_arcs.values()}
        )

    def describe(self) -> list[str]:
        relics = self._count("relics")
        completed = self._count("file_history")
        scars = self._count("scars")
        description_key = (
            "reliquary"
            if relics and "reliquary" in self._fragments.archive_descriptions
            else "default"
        )
        mood_key = self._mood_key()
        if mood_key not in self._fragments.room_moods:
            mood_key = "default"
        lines = [
            self._rng.choice(self._fragments.archive_descriptions[description_key]),
            self._rng.choice(self._fragments.room_weather["default"]),
            self._rng.choice(self._fragments.room_moods[mood_key]),
            self._history_line(completed, relics, scars),
        ]
        lines.extend(self._relic_lines())
        return lines

    def _relic_lines(self) -> list[str]:
        lines: list[str] = []
        rows = self._conn.execute(
            "SELECT relic_key, description, effects_json FROM relics ORDER BY id"
        )
        for row in rows:
            key = str(row["relic_key"])
            name = self._relic_names.get(key, key.replace("_", " ").title())
            effects = json.loads(row["effects_json"])
            descriptions: list[str] = []
            for effect in effects:
                if not isinstance(effect, dict) or effect.get("type") != "stat_bonus":
                    continue
                amount = effect.get("amount")
                tags = effect.get("tags", [])
                if isinstance(amount, int) and isinstance(tags, list):
                    tag_text = " or ".join(str(tag) for tag in tags)
                    descriptions.append(
                        f"{amount:+d} to stat checks during {tag_text} Files"
                    )
            effect_text = "; ".join(descriptions) or "no active effect recorded"
            lines.append(
                f"Relic: {name} — {row['description']} Effect: {effect_text}."
            )
        return lines

    def _count(self, table: str) -> int:
        # Table names are internal constants at each call site, never user input.
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _mood_key(self) -> str:
        row = self._conn.execute(
            "SELECT resolution_tier FROM file_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return "default"
        tier = str(row["resolution_tier"])
        if tier in {"clean_success", "success"}:
            return "settled"
        if tier in {"mixed_failure", "failure", "disaster"}:
            return "unsettled"
        return "default"

    @staticmethod
    def _history_line(completed: int, relics: int, scars: int) -> str:
        file_word = "File rests" if completed == 1 else "Files rest"
        relic_word = "relic is" if relics == 1 else "relics are"
        scar_word = "record bears" if scars == 1 else "records bear"
        return (
            f"{completed} closed {file_word} in the stacks. "
            f"{relics} {relic_word} shelved. {scars} personnel {scar_word} amendments."
        )


def personnel_title(
    content: ContentPack,
    player_id: str,
    completed_files: int,
    has_scars: bool,
) -> str:
    """Choose a stable title from the investigator's current history tier."""
    if has_scars:
        category = "marked"
    elif completed_files >= 5:
        category = "veteran"
    elif completed_files >= 1:
        category = "active"
    else:
        category = "new"
    choices = content.fragments.personnel_titles[category]
    digest = hashlib.sha256(player_id.encode("utf-8")).digest()
    return choices[int.from_bytes(digest[:8], "big") % len(choices)]
