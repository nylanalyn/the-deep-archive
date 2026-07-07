"""The pure backend seam between IRC and the game.

The :class:`BotBackend` owns identity resolution, command routing, and the
player-facing command handlers. It has no dependency on pydle — the
IRC layer calls in with ``(nick, account, message)`` and gets back a list of
reply strings. This keeps the whole interaction loop unit-testable.

Gameplay commands not yet implemented return a short atmospheric placeholder
so the full routing path remains proven end-to-end.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime
from typing import cast

from deeparchive.actions import DailyActionLedger
from deeparchive.action_flavour import ActionNarrator
from deeparchive.backgrounds import BackgroundAssigner
from deeparchive.content.models import ContentPack
from deeparchive.content import load_content
from deeparchive.confrontation import ConfrontationService
from deeparchive.files import FileService
from deeparchive.gameplay import ActionName, GameplayService
from deeparchive.flavour import ArchiveFlavourService
from deeparchive.identity import IdentityResolver, Player
from deeparchive.irc.commands import ParsedCommand, parse_command
from deeparchive.profiles import ProfileRepository, render_profile
from deeparchive.modifiers import ModifierService
from deeparchive.resolution import ResolutionService
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
        day_boundary_timezone: str = "UTC",
        actions_per_day: int = 5,
        clock: Callable[[], datetime] | None = None,
        background_rng: Rng | None = None,
        flavour_rng: Rng | None = None,
        action_flavour_rng: Rng | None = None,
    ) -> None:
        self._conn = conn
        self._channel = channel
        content_pack = content or load_content()
        self._content = content_pack
        self._resolver = IdentityResolver(
            conn,
            BackgroundAssigner(content_pack, background_rng or make_rng()),
        )
        action_rng = rng or make_rng()
        self._actions = DailyActionLedger(
            conn,
            timezone_name=day_boundary_timezone,
            limit=actions_per_day,
            clock=clock,
        )
        self._modifiers = ModifierService(conn, content_pack)
        self._profiles = ProfileRepository(
            conn, self._actions, content_pack, self._modifiers
        )
        self._files = FileService(conn, content_pack, action_rng)
        self._resolution = ResolutionService(conn, content_pack, action_rng)
        self._flavour = ArchiveFlavourService(
            conn,
            content_pack,
            flavour_rng or make_rng(),
            day_key=self._actions.day_key,
        )
        self._gameplay = GameplayService(
            conn,
            self._actions,
            action_rng,
            self._resolution,
            self._modifiers,
            ActionNarrator(content_pack, action_flavour_rng or make_rng()),
            content_pack,
        )
        self._confrontation = ConfrontationService(
            conn,
            self._actions,
            self._modifiers,
            self._resolution,
            action_rng,
            content_pack,
        )
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
        if parsed.reserved and parsed.name != "confront":
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

    def handle_help(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Summarize the game loop and the complete player command surface."""
        return [
            f"The Archive opens one File at a time. You have {self._actions.limit} "
            "actions each day. Each File favours some approaches and resents "
            "others — read !case, coordinate, and close it before it turns.",
            "Commands: !case current File · !profile [nick] personnel file · "
            "!room Archive · !investigate luck, steadies the File · "
            "!interview Wit · !force Strength · !ritual Occultism · "
            "!confront Sealed Files",
        ]

    def handle_case(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Describe the current File without exposing hidden mechanics."""
        return self._files.describe_active()

    def handle_action(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Resolve one of the four Phase 6 File actions."""
        action = cast(ActionName, parsed.name)
        return self._gameplay.render(self._gameplay.perform(player, action))

    def handle_room(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Describe the Archive and the history it has accumulated."""
        return self._flavour.describe()

    def handle_confront(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Attempt the final check on a ready Sealed File."""
        return self._confrontation.confront(player)

    @staticmethod
    def reply_delay(message: str, reply_index: int, line: str) -> float:
        """Pause between an action's attempt and explicit outcome lines.

        The pause lands only before a genuine SUCCESS/FAILURE beat — a
        resolution or blocked reply triggered by the same command flows
        without the dramatic gap.
        """
        if reply_index != 1 or not line.startswith(("SUCCESS —", "FAILURE —")):
            return 0.0
        parsed = parse_command(message)
        if parsed is not None and parsed.name in {
            "investigate",
            "interview",
            "force",
            "ritual",
        }:
            return 1.5
        return 0.0

    def handle_stub(self, player: Player, parsed: ParsedCommand) -> list[str]:
        """Atmospheric placeholder for gameplay commands not yet built.

        Retained as the routing seam for future commands.
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
    # Daily heartbeat
    # ------------------------------------------------------------------

    def seconds_until_heartbeat(self) -> float:
        """Seconds until the day turns in the configured timezone."""
        return self._actions.seconds_until_day_turn()

    def heartbeat_line(self) -> str | None:
        """The single unprompted line spoken when the day turns.

        Seeded by the day key so restarts within the same day repeat the
        same line rather than rolling a new one. Returns ``None`` when quiet
        or when the content pack ships no heartbeats.
        """
        if self.quiet:
            return None
        lines = self._content.fragments.day_heartbeats.get("default")
        if not lines:
            return None
        digest = hashlib.sha256(self._actions.day_key().encode("utf-8")).digest()
        return Rng(int.from_bytes(digest[:8], "big")).choice(lines)

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
        del name  # all sealed requests receive the same quiet refusal
        return "The Archive holds no answer for that. Not yet."

    # ------------------------------------------------------------------
    # Dispatch table
    # ------------------------------------------------------------------

    # Maps command name -> unbound handler function. Routing is a dict lookup,
    # not a chain of ifs. Handlers are resolved at call time with explicit
    # ``self`` so the table stays static (no bound methods pinning instances).
    # Gameplay commands not yet implemented point at ``handle_stub``; their
    # phases will repoint the entry to a real handler.
    _dispatch: dict = {
        "help": handle_help,
        "profile": handle_profile,
        "case": handle_case,
        "room": handle_room,
        "investigate": handle_action,
        "interview": handle_action,
        "force": handle_action,
        "ritual": handle_action,
        "confront": handle_confront,
    }
