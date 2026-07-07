"""Generation and persistence for the Archive's single active File."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from deeparchive.content.models import ContentPack, ThemeDefinition
from deeparchive.rng import Rng

MIN_SUCCESS_THRESHOLD = 14
MAX_SUCCESS_THRESHOLD = 20


@dataclass(frozen=True, slots=True)
class ActiveFile:
    seed: int
    title: str
    location: str
    theme_key: str
    theme_tags: tuple[str, ...]
    opening_text: str
    success_threshold: int
    successes: int
    failures: int
    danger: int
    clue_count: int
    is_sealed: bool = False
    arc_key: str | None = None


class FileGenerator:
    """Generate reproducible File content from one isolated seed."""

    def __init__(self, content: ContentPack, rng: Rng) -> None:
        self._content = content
        self._rng = rng

    def generate(self) -> ActiveFile:
        # SQLite INTEGER is signed 64-bit. Keeping seeds in that range makes
        # every generated File directly replayable with Rng(file.seed).
        seed = self._rng.randint(0, (1 << 63) - 1)
        file_rng = Rng(seed)
        theme = file_rng.choice(tuple(self._content.themes.values()))
        title = self._generate_title(theme, file_rng)
        location = file_rng.choice(theme.locations)
        openings = self._content.fragments.file_openings.get(
            theme.key, self._content.fragments.file_openings["default"]
        )
        return ActiveFile(
            seed=seed,
            title=title,
            location=location,
            theme_key=theme.key,
            theme_tags=theme.tags,
            opening_text=file_rng.choice(openings),
            success_threshold=file_rng.randint(
                MIN_SUCCESS_THRESHOLD, MAX_SUCCESS_THRESHOLD
            ),
            successes=0,
            failures=0,
            danger=0,
            clue_count=0,
            is_sealed=False,
            arc_key=None,
        )

    @staticmethod
    def _generate_title(theme: ThemeDefinition, rng: Rng) -> str:
        parts: list[str] = []
        for part_name in ("prefix", "noun", "suffix"):
            choices = theme.title_parts.get(part_name)
            if choices:
                parts.append(rng.choice(choices))
        return " ".join(parts)


class FileRepository:
    """Store and retrieve the singleton active File."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_active(self) -> ActiveFile | None:
        row = self._conn.execute("SELECT * FROM active_file WHERE id = 1").fetchone()
        if row is None:
            return None
        raw_tags = json.loads(row["theme_tags_json"])
        if not isinstance(raw_tags, list) or not all(
            isinstance(tag, str) for tag in raw_tags
        ):
            raise ValueError("active_file.theme_tags_json must be a list of strings")
        return ActiveFile(
            seed=int(row["seed"]),
            title=str(row["title"]),
            location=str(row["location"]),
            theme_key=str(row["theme_key"]),
            theme_tags=tuple(raw_tags),
            opening_text=str(row["opening_text"]),
            success_threshold=int(row["success_threshold"]),
            successes=int(row["successes"]),
            failures=int(row["failures"]),
            danger=int(row["danger"]),
            clue_count=int(row["clue_count"]),
            is_sealed=bool(row["is_sealed"]),
            arc_key=str(row["arc_key"]) if row["arc_key"] is not None else None,
        )

    def create_if_absent(self, generated: ActiveFile) -> ActiveFile:
        """Insert ``generated`` only when no active File exists."""
        self._conn.execute(
            "INSERT OR IGNORE INTO active_file "
            "(id, seed, title, location, theme_tags_json, success_threshold, "
            "theme_key, opening_text, is_sealed, arc_key) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                generated.seed,
                generated.title,
                generated.location,
                json.dumps(list(generated.theme_tags)),
                generated.success_threshold,
                generated.theme_key,
                generated.opening_text,
                int(generated.is_sealed),
                generated.arc_key,
            ),
        )
        self._conn.commit()
        active = self.get_active()
        if active is None:  # defensive: the singleton insert should guarantee this
            raise RuntimeError("failed to create the active File")
        return active


class FileService:
    """Ensure the Archive always has exactly one active File."""

    def __init__(self, conn: sqlite3.Connection, content: ContentPack, rng: Rng) -> None:
        self._repository = FileRepository(conn)
        self._generator = FileGenerator(content, rng)

    def ensure_active(self) -> ActiveFile:
        active = self._repository.get_active()
        if active is not None:
            return active
        return self._repository.create_if_absent(self._generator.generate())

    def describe_active(self) -> list[str]:
        active = self.ensure_active()
        return [
            f"{'Sealed File' if active.is_sealed else 'File'}: "
            f"{active.title} — {active.location}.",
            active.opening_text,
        ]
