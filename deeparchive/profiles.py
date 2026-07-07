"""Personnel-file queries and rendering for investigator profiles."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from deeparchive.actions import DailyActionLedger
from deeparchive.content.models import ContentPack
from deeparchive.identity import Player
from deeparchive.modifiers import ModifierService


@dataclass(frozen=True, slots=True)
class Profile:
    """The profile fields currently persisted for one investigator."""

    player: Player
    wit: int
    strength: int
    occultism: int
    scars: tuple[str, ...]
    actions_remaining: int
    background: str
    completed_files: int

    @property
    def personnel_status(self) -> str:
        """A restrained display title derived from the available record."""
        return "Marked Investigator" if self.scars else "Newly Catalogued"


class ProfileRepository:
    """Read personnel files from a migrated Archive database."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        action_ledger: DailyActionLedger,
        content: ContentPack,
        modifiers: ModifierService,
    ) -> None:
        self._conn = conn
        self._action_ledger = action_ledger
        self._content = content
        self._modifiers = modifiers

    def get(self, player: Player) -> Profile:
        row = self._conn.execute(
            "SELECT wit, strength, occultism, background_key, completed_files "
            "FROM players WHERE id = ?",
            (player.id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"investigator {player.id!r} no longer exists")

        scar_rows = self._conn.execute(
            "SELECT description FROM scars WHERE player_id = ? "
            "ORDER BY acquired_at, id",
            (player.id,),
        ).fetchall()
        background = self._content.backgrounds.get(str(row["background_key"]))
        background_name = background.name if background is not None else "Unassigned"
        return Profile(
            player=player,
            wit=self._modifiers.effective_stat(player.id, "wit"),
            strength=self._modifiers.effective_stat(player.id, "strength"),
            occultism=self._modifiers.effective_stat(player.id, "occultism"),
            scars=tuple(str(scar["description"]) for scar in scar_rows),
            actions_remaining=self._action_ledger.allowance(player.id).remaining,
            background=background_name,
            completed_files=int(row["completed_files"]),
        )


def render_profile(profile: Profile) -> list[str]:
    """Render a short personnel file suitable for IRC lines."""
    lines = [
        f"Personnel file: {profile.player.display_nick} — {profile.personnel_status}.",
        (
            f"Effective: Wit {profile.wit} · Strength {profile.strength} · "
            f"Occultism {profile.occultism}."
        ),
        f"Actions remaining today: {profile.actions_remaining}.",
        f"Background: {profile.background} · Completed Files: {profile.completed_files}.",
    ]
    if profile.scars:
        lines.append(f"Scars: {'; '.join(profile.scars)}")
    else:
        lines.append("Scars: none recorded.")
    return lines
