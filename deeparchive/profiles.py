"""Personnel-file queries and rendering for investigator profiles."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from deeparchive.identity import Player


@dataclass(frozen=True, slots=True)
class Profile:
    """The profile fields currently persisted for one investigator."""

    player: Player
    wit: int
    strength: int
    occultism: int
    scars: tuple[str, ...]

    @property
    def personnel_status(self) -> str:
        """A restrained display title derived from the available record."""
        return "Marked Investigator" if self.scars else "Newly Catalogued"


class ProfileRepository:
    """Read personnel files from a migrated Archive database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, player: Player) -> Profile:
        row = self._conn.execute(
            "SELECT wit, strength, occultism FROM players WHERE id = ?",
            (player.id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"investigator {player.id!r} no longer exists")

        scar_rows = self._conn.execute(
            "SELECT description FROM scars WHERE player_id = ? "
            "ORDER BY acquired_at, id",
            (player.id,),
        ).fetchall()
        return Profile(
            player=player,
            wit=int(row["wit"]),
            strength=int(row["strength"]),
            occultism=int(row["occultism"]),
            scars=tuple(str(scar["description"]) for scar in scar_rows),
        )


def render_profile(profile: Profile) -> list[str]:
    """Render a short personnel file suitable for IRC lines."""
    lines = [
        f"Personnel file: {profile.player.display_nick} — {profile.personnel_status}.",
        (
            f"Wit {profile.wit} · Strength {profile.strength} · "
            f"Occultism {profile.occultism}."
        ),
    ]
    if profile.scars:
        lines.append(f"Scars: {'; '.join(profile.scars)}")
    else:
        lines.append("Scars: none recorded.")
    return lines
