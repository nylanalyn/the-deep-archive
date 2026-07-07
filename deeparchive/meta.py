"""Persistent hidden meta-arc progression and Sealed File generation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from deeparchive.content.models import ContentPack, MetaArcDefinition
from deeparchive.files import ActiveFile
from deeparchive.rng import Rng


@dataclass(frozen=True, slots=True)
class MetaArcObservation:
    revealed: MetaArcDefinition | None = None
    hint: str | None = None


class MetaArcService:
    def __init__(self, conn: sqlite3.Connection, content: ContentPack, rng: Rng) -> None:
        self._conn = conn
        self._content = content
        self._rng = rng

    def observe_theme(self, theme_key: str) -> MetaArcObservation:
        state = self._load()
        if state.get("active_arc"):
            return MetaArcObservation()
        counts = state.setdefault("counts", {})
        revealed = None
        hint = None
        for arc in self._content.meta_arcs.values():
            if arc.theme_key != theme_key:
                continue
            counts[arc.key] = int(counts.get(arc.key, 0)) + 1
            if counts[arc.key] >= arc.trigger_count:
                state["active_arc"] = arc.key
                counts[arc.key] = 0
                revealed = arc
                break
            hint_index = min(int(counts[arc.key]) - 1, len(arc.hints) - 1)
            hint = arc.hints[hint_index]
        self._save(state)
        return MetaArcObservation(revealed=revealed, hint=hint)

    def sealed_file(self, arc: MetaArcDefinition) -> ActiveFile:
        seed = self._rng.randint(0, (1 << 63) - 1)
        return ActiveFile(
            seed=seed,
            title=arc.title,
            location=arc.location,
            theme_key=arc.theme_key,
            theme_tags=arc.tags,
            opening_text=arc.opening,
            success_threshold=arc.threshold,
            successes=0,
            failures=0,
            danger=0,
            clue_count=0,
            is_sealed=True,
            arc_key=arc.key,
        )

    def complete(self, arc_key: str, victory: bool) -> None:
        state = self._load()
        bucket = "victories" if victory else "defeats"
        values = state.setdefault(bucket, {})
        values[arc_key] = int(values.get(arc_key, 0)) + 1
        state["active_arc"] = None
        self._save(state)

    def victory_reward(self, arc_key: str, history_id: int) -> str | None:
        arc = self._content.meta_arcs.get(arc_key)
        if arc is None:
            return None
        effect = [{"type": "stat_bonus", "amount": 1, "tags": list(arc.tags)}]
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO relics "
            "(relic_key, theme_tags_json, effects_json, description, source_file_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                arc.reward_key, json.dumps(list(arc.tags)), json.dumps(effect),
                arc.reward_description, history_id,
            ),
        )
        return arc.reward_name if cursor.rowcount == 1 else None

    def steal_relic(self) -> str | None:
        rows = list(self._conn.execute("SELECT id, relic_key FROM relics ORDER BY id"))
        if not rows:
            return None
        row = self._rng.choice(rows)
        self._conn.execute("DELETE FROM relics WHERE id = ?", (row["id"],))
        return self._relic_name(str(row["relic_key"]))

    def _relic_name(self, key: str) -> str:
        """The display name for a shelved relic, from content when known."""
        relic = self._content.relics.get(key)
        if relic is not None:
            return relic.name
        for arc in self._content.meta_arcs.values():
            if arc.reward_key == key:
                return arc.reward_name
        return key.replace("_", " ").title()

    def state(self) -> dict:
        return self._load()

    def _load(self) -> dict:
        row = self._conn.execute(
            "SELECT state_json FROM meta_arc_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return {"counts": {}, "active_arc": None, "victories": {}, "defeats": {}}
        value = json.loads(row["state_json"])
        if not isinstance(value, dict):
            raise ValueError("meta_arc_state.state_json must be an object")
        return value

    def _save(self, state: dict) -> None:
        self._conn.execute(
            "INSERT INTO meta_arc_state (id, state_json) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (json.dumps(state, sort_keys=True),),
        )
