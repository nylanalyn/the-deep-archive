"""Short, content-driven descriptions of the persistent Archive."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Protocol

from deeparchive.content.models import ContentPack
from deeparchive.rng import Rng

# `!room` shows the newest few relics rather than the whole reliquary, so the
# reply stays IRC-sized however long the Archive has been accumulating.
MAX_RELIC_LINES = 3

# The Archive reads differently after each Sealed File the room breaks. Eras are
# capped so late-game content stays bounded; era_N maps to N boss victories.
MAX_ERA = 3


class ChoiceSource(Protocol):
    def choice(self, seq): ...


class ArchiveFlavourService:
    """Compose `!room` output from fragments and accumulated history."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        content: ContentPack,
        rng: ChoiceSource,
        day_key: Callable[[], str] | None = None,
    ):
        self._conn = conn
        self._fragments = content.fragments
        self._rng = rng
        # When a day-key provider is given, weather is deterministic per day:
        # everyone who asks sees the same sky until the day turns.
        self._day_key = day_key
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
        description_key = self._description_key(relics)
        mood_key = self._mood_key()
        if mood_key not in self._fragments.room_moods:
            mood_key = "default"
        lines = [
            self._rng.choice(self._fragments.archive_descriptions[description_key]),
            self._weather_rng().choice(self._fragments.room_weather["default"]),
            self._rng.choice(self._fragments.room_moods[mood_key]),
            self._history_line(completed, relics, scars),
        ]
        lines.extend(self._relic_lines(total=relics))
        return lines

    def _description_key(self, relics: int) -> str:
        """Pick the Archive-description bucket, era first.

        After the room breaks a Sealed File the world visibly changes: an
        era_N bucket (N boss victories, capped) takes precedence, then the
        reliquary once relics exist, then the default.
        """
        era = min(self._boss_victories(), MAX_ERA)
        era_key = f"era_{era}"
        if era >= 1 and era_key in self._fragments.archive_descriptions:
            return era_key
        if relics and "reliquary" in self._fragments.archive_descriptions:
            return "reliquary"
        return "default"

    def _boss_victories(self) -> int:
        """Total Sealed Files the room has broken, from the meta-arc blob."""
        row = self._conn.execute(
            "SELECT state_json FROM meta_arc_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return 0
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError):
            return 0
        victories = state.get("victories", {}) if isinstance(state, dict) else {}
        if not isinstance(victories, dict):
            return 0
        return sum(int(count) for count in victories.values())

    def _weather_rng(self) -> ChoiceSource:
        if self._day_key is None:
            return self._rng
        digest = hashlib.sha256(self._day_key().encode("utf-8")).digest()
        return Rng(int.from_bytes(digest[:8], "big"))

    def _relic_lines(self, total: int) -> list[str]:
        lines: list[str] = []
        rows = self._conn.execute(
            "SELECT relic_key, description, effects_json FROM relics "
            "ORDER BY id DESC LIMIT ?",
            (MAX_RELIC_LINES,),
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
        hidden = total - len(lines)
        if hidden > 0:
            noun = "relic rests" if hidden == 1 else "relics rest"
            lines.append(f"{hidden} older {noun} behind glass, catalogued but unshown.")
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
