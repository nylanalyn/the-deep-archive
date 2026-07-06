"""Investigator identity resolution.

IRC nicks are mutable; investigators are permanent. This module maps the
noisy IRC surface (nicks, NickServ/SASL accounts, nick changes) onto stable
UUID-keyed investigators in the database.

Resolution priority (per SPEC.md "Identity"):

1. Account authoritative. When an account is known, the investigator IS the
   account. We look up or create the player by account.
2. Nick fallback. No account: we look the nick up in ``nick_map``. If the bot
   has seen this nick before, it maps to a known investigator.
3. Fresh investigator. No account, unknown nick: create a new player.

The :class:`IdentityResolver` is pure Python and takes a ``sqlite3.Connection``.
It has no dependency on IRC, so it is fully unit-testable.

Known limitation: if the bot is offline during a nick change, or the change
happens outside the channel, the link is lost and the new nick looks fresh.
Accounts recover this; pure-nick users do not. This is the accepted tradeoff
from the design discussion.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# IRC's account-notify sends ``*`` when a user logs out. We treat it as "no
# account available" rather than a literal account named "*".
NO_ACCOUNT = "*"


@dataclass(frozen=True, slots=True)
class Player:
    """A resolved investigator.

    ``id`` is the stable UUID (string form) stored in ``players.id``.
    ``account`` is the NickServ/SASL account or ``None``.
    ``display_nick`` is the last nick we saw them use.
    """

    id: str
    account: str | None
    display_nick: str


class IdentityResolver:
    """Maps IRC nicks/accounts to stable :class:`Player` investigators.

    The resolver owns the account-first / nick-second / fresh-UUID rules and
    is the only thing that mutates ``players`` and ``nick_map``. Keeping it
    separate from the IRC layer makes the identity contract unit-testable.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_identity(self, nick: str, account: str | None) -> Player:
        """Resolve the investigator for ``nick`` and optional ``account``.

        Always returns a :class:`Player` and leaves the database consistent:
        the player exists, ``display_nick`` is current, and ``nick_map[nick]``
        points at the resolved player. Safe to call repeatedly; idempotent.
        """
        nick = nick.strip()
        if not nick:
            raise ValueError("nick must be non-empty")

        # Treat IRC's "*" logout sentinel and empty strings as "no account".
        account = self._normalize_account(account)

        if account is not None:
            return self._resolve_via_account(nick, account)
        return self._resolve_via_nick(nick)

    def _resolve_via_account(self, nick: str, account: str) -> Player:
        """Account is authoritative: find or create the player by account."""
        row = self._conn.execute(
            "SELECT id, account, display_nick FROM players WHERE account = ?",
            (account,),
        ).fetchone()

        if row is not None:
            player = Player(id=row["id"], account=row["account"], display_nick=row["display_nick"])
            player = self._refresh_nick(player, nick)
            logger.debug("resolved nick %s -> existing account %s", nick, account)
            return player

        # New investigator, identified by account from the start.
        player = self._create_player(nick=nick, account=account)
        logger.info("new investigator %s via account %s", player.id, account)
        return player

    def _resolve_via_nick(self, nick: str) -> Player:
        """No account: fall back to nick_map, else create fresh."""
        row = self._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", (nick,)
        ).fetchone()

        if row is not None:
            player = self._load_player(row["player_id"])
            if player is None:
                # The player row vanished but nick_map still references it.
                # This should not happen under FK ON DELETE CASCADE, but guard
                # against it by treating the nick as fresh.
                logger.warning(
                    "nick_map points at missing player %s; treating %s as fresh",
                    row["player_id"], nick,
                )
                return self._create_player(nick=nick, account=None)
            player = self._refresh_nick(player, nick)
            logger.debug("resolved nick %s -> existing player %s (no account)", nick, player.id)
            return player

        # Fresh investigator: no account, never-seen nick.
        player = self._create_player(nick=nick, account=None)
        logger.info("new investigator %s via nick %s (no account)", player.id, nick)
        return player

    # ------------------------------------------------------------------
    # Nick rebinding
    # ------------------------------------------------------------------

    def rebind_nick(self, old: str, new: str) -> None:
        """Move a ``nick_map`` row from ``old`` to ``new``.

        Called when the bot observes an in-channel nick change. If ``new`` is
        already mapped to a *different* player, the new observation wins: we
        delete the stale mapping and let the most recent claimant take it.
        A warning is logged so identity collisions are visible.
        """
        old = old.strip()
        new = new.strip()
        if not old or not new or old.casefold() == new.casefold():
            return

        old_row = self._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", (old,)
        ).fetchone()
        if old_row is None:
            # We never tracked this nick. Nothing to rebind; the resolver will
            # treat ``new`` as fresh when it next speaks.
            logger.debug("rebind: old nick %s not tracked, ignoring", old)
            return

        player_id = old_row["player_id"]

        # If ``new`` is already claimed by a different player, the new
        # claimant takes it. Delete the old claim first.
        new_row = self._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", (new,)
        ).fetchone()
        if new_row is not None and new_row["player_id"] != player_id:
            logger.warning(
                "nick collision: %s was mapped to player %s, now claimed by %s",
                new, new_row["player_id"], player_id,
            )
            self._conn.execute("DELETE FROM nick_map WHERE nick = ?", (new,))

        # Move old -> new.
        self._conn.execute("DELETE FROM nick_map WHERE nick = ?", (old,))
        self._conn.execute(
            "INSERT INTO nick_map (nick, player_id) VALUES (?, ?)",
            (new, player_id),
        )
        self._conn.execute(
            "UPDATE players SET display_nick = ?, last_seen_at = "
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (new, player_id),
        )
        self._conn.commit()
        logger.debug("rebound nick %s -> %s (player %s)", old, new, player_id)

    # ------------------------------------------------------------------
    # Account updates
    # ------------------------------------------------------------------

    def update_account(self, nick: str, account: str | None) -> None:
        """Record an account association for the investigator using ``nick``.

        Rules (per SPEC): first account wins. We never yank identity away on a
        transient log-out, so an account of ``*`` / None is ignored. We do not
        overwrite an existing stored account, because a logged-out session
        shouldn't erase a known account.
        """
        account = self._normalize_account(account)
        if account is None:
            return

        row = self._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", (nick,)
        ).fetchone()
        if row is None:
            logger.debug("update_account: nick %s not tracked yet", nick)
            return

        player_id = row["player_id"]
        current = self._conn.execute(
            "SELECT account FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if current is None:
            return

        if current["account"] is None:
            self._conn.execute(
                "UPDATE players SET account = ? WHERE id = ?", (account, player_id)
            )
            self._conn.commit()
            logger.info(
                "associated account %s with player %s (nick %s)",
                account, player_id, nick,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_account(account: str | None) -> str | None:
        """Reduce IRC account signalling to ``str | None``.

        ``None``, empty string, and ``*`` (the logout sentinel) all become
        ``None`` — "no account available right now".
        """
        if account is None:
            return None
        account = account.strip()
        if not account or account == NO_ACCOUNT:
            return None
        return account

    def _load_player(self, player_id: str) -> Player | None:
        row = self._conn.execute(
            "SELECT id, account, display_nick FROM players WHERE id = ?",
            (player_id,),
        ).fetchone()
        if row is None:
            return None
        return Player(id=row["id"], account=row["account"], display_nick=row["display_nick"])

    def _refresh_nick(self, player: Player, nick: str) -> Player:
        """Ensure nick_map and display_nick are current for ``player``.

        Returns the (possibly updated) Player. We update display_nick even if
        it differs only in case, so the profile shows what the player is
        wearing right now.
        """
        self._conn.execute(
            "INSERT INTO nick_map (nick, player_id) VALUES (?, ?) "
            "ON CONFLICT(nick) DO UPDATE SET player_id = excluded.player_id",
            (nick, player.id),
        )
        if player.display_nick != nick:
            self._conn.execute(
                "UPDATE players SET display_nick = ?, last_seen_at = "
                "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (nick, player.id),
            )
            player = Player(id=player.id, account=player.account, display_nick=nick)
        self._conn.commit()
        return player

    def _create_player(self, nick: str, account: str | None) -> Player:
        player_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO players (id, account, display_nick) VALUES (?, ?, ?)",
            (player_id, account, nick),
        )
        self._conn.execute(
            "INSERT INTO nick_map (nick, player_id) VALUES (?, ?)",
            (nick, player_id),
        )
        self._conn.commit()
        return Player(id=player_id, account=account, display_nick=nick)

    # ------------------------------------------------------------------
    # Read-only introspection (used by the admin surface)
    # ------------------------------------------------------------------

    def count_investigators(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()
        return int(row["n"])

    def count_tracked_nicks(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM nick_map").fetchone()
        return int(row["n"])

    def find_by_nick(self, nick: str) -> Player | None:
        """Return an existing investigator by known nick without creating one."""
        nick = nick.strip()
        if not nick:
            return None
        row = self._conn.execute(
            "SELECT p.id, p.account, p.display_nick "
            "FROM nick_map AS n JOIN players AS p ON p.id = n.player_id "
            "WHERE n.nick = ?",
            (nick,),
        ).fetchone()
        if row is None:
            return None
        return Player(
            id=row["id"], account=row["account"], display_nick=row["display_nick"]
        )
