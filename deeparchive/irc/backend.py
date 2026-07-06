"""The pure backend seam between IRC and the game.

The :class:`BotBackend` owns identity resolution, command routing, and the
player-facing command handlers. It has no dependency on pydle — the
IRC layer calls in with ``(nick, account, message)`` and gets back a list of
reply strings. This keeps the whole interaction loop unit-testable.

Gameplay commands not yet implemented return a short atmospheric placeholder
so the full routing path remains proven end-to-end.
"""

from __future__ import annotations

import logging

from deeparchive.content.models import ContentPack
from deeparchive.content import load_content
from deeparchive.files import FileService
from deeparchive.identity import IdentityResolver, Player
from deeparchive.irc.commands import ParsedCommand, parse_command
from deeparchive.profiles import ProfileRepository, render_profile
from deeparchive.rng import Rng, make_rng

logger = logging.getLogger(__name__)


class BotBackend:
    """Pure-Python game backend. No IRC dependency.

    Constructed with a migrated DB connection and the canonical channel name
    (for context, not for sending — the IRC layer sends). The backend returns
    reply strings; it never writes to the wire itself.
    """

    def __init__(
        self,
        conn,
        channel: str,
        content: ContentPack | None = None,
        rng: Rng | None = None,
    ) -> None:
        self._conn = conn
        self._channel = channel
        self._resolver = IdentityResolver(conn)
        self._profiles = ProfileRepository(conn)
        self._files = FileService(conn, content or load_content(), rng or make_rng())
        # A File always exists, including immediately after a clean startup.
        self._files.ensure_active()
        # ``quiet`` is set by the admin dispatcher to silence all player-facing
        # output (e.g. during maintenance). The backend still resolves
        # identity and records state; it just returns no replies.
        self.quiet: bool = False

    # ------------------------------------------------------------------
    # Inbound entry point
    # ------------------------------------------------------------------

    def handle_message(self, nick: str, account: str | None, message: str) -> list[str]:
        """Process one inbound channel message.

        Returns a list of reply lines (possibly empty). The caller (the IRC
        layer) sends each line to the channel. When ``quiet`` is set, returns
        an empty list regardless of input.

        Policy — identity is resolved for EVERY message, not just commands:
        this is a dedicated game channel, so presence is opting in. "The
        Archivist has seen you" means you exist in the Archive, which fits the
        fiction better than "you don't exist until you speak." If a future
        deployment sits in a large non-game channel, add an ``activated_at``
        column via migration and gate player creation on first command. This
        is a deliberate decision, not an oversight.
        """
        # Always resolve identity — even when quiet, we want the investigator
        # recorded so their presence is known when the bot comes back.
        player = self._resolver.resolve_identity(nick, account)

        if self.quiet:
            return []

        parsed = parse_command(message)
        if parsed is None:
            return []
        return self.route_command(player, parsed)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route_command(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Dispatch a parsed command to its handler.

        Known player commands get their handler stub. Reserved commands get a
        distinct sealed response. Unknown commands get a short atmospheric
        "not understood" line. No path raises — the bot never errors visibly.
        """
        if parsed.reserved:
            return [self._reserved_reply(parsed.name)]

        handler = self._dispatch.get(parsed.name)
        if handler is None:
            return [self._unknown_reply()]

        # Handlers are unbound functions resolved through the dispatch table;
        # pass self explicitly. This keeps the table static and avoids holding
        # bound methods that would pin player instances in memory.
        return handler(self, player, parsed)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def handle_profile(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Show the caller's personnel file, or an existing file by nick."""
        target = player
        if parsed.args:
            target = self._resolver.find_by_nick(parsed.args)
            if target is None:
                return ["No personnel file bears that name."]
        return render_profile(self._profiles.get(target))

    def handle_case(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Describe the current File without exposing hidden mechanics."""
        return self._files.describe_active()

    def handle_stub(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Atmospheric placeholder for gameplay commands not yet built.

        Used for !room, !investigate, !interview, !force, and !ritual until
        their phases ship. The line is deliberately clearly-placeholder so
        it reads as "under construction" in the Archivist's voice, not as a
        real piece of fiction.
        """
        return ["The Archive is still being catalogued. Check back soon."]

    # ------------------------------------------------------------------
    # Identity pass-throughs (used by the IRC layer)
    # ------------------------------------------------------------------

    def resolve_identity(self, nick: str, account: str | None) -> Player:
        return self._resolver.resolve_identity(nick, account)

    def rebind_nick(self, old: str, new: str) -> None:
        self._resolver.rebind_nick(old, new)

    def update_account(self, nick: str, account: str | None) -> None:
        self._resolver.update_account(nick, account)

    # ------------------------------------------------------------------
    # Admin surface
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return a status snapshot for the admin surface."""
        return {
            "channel": self._channel,
            "investigators": self._resolver.count_investigators(),
            "tracked_nicks": self._resolver.count_tracked_nicks(),
            "quiet": self.quiet,
        }

    # ------------------------------------------------------------------
    # Replies
    # ------------------------------------------------------------------

    @staticmethod
    def _unknown_reply() -> str:
        return "The Archivist does not recognise that request."

    @staticmethod
    def _reserved_reply(name: str) -> str:
        return f"The Archive holds no answer for that. Not yet."

    # ------------------------------------------------------------------
    # Dispatch table
    # ------------------------------------------------------------------

    # Maps command name -> unbound handler function. Routing is a dict lookup,
    # not a chain of ifs. Handlers are resolved at call time with explicit
    # ``self`` so the table stays static (no bound methods pinning instances).
    # Gameplay commands not yet implemented point at ``handle_stub``; their
    # phases will repoint the entry to a real handler.
    _dispatch: dict = {
        "profile": handle_profile,
        "case": handle_case,
        "room": handle_stub,
        "investigate": handle_stub,
        "interview": handle_stub,
        "force": handle_stub,
        "ritual": handle_stub,
    }
