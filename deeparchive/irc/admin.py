"""Admin command dispatcher.

Admin commands are out-of-band: they do not count toward the player command
surface and never appear in SPEC.md. In Phase 1 the dispatcher is in-process
only — the IRC layer and ``__main__`` call it directly. The cross-cutting
admin phase will expose the same commands over the HTTP contract that
``discord_admin.py`` already speaks (``POST /v1/command``, ``GET /v1/events``).

The dispatcher returns ``list[str]`` reply lines (matching
:func:`BotBackend.route_command`'s shape) so the eventual HTTP bridge can
format them identically to the shared router's other bots.
"""

from __future__ import annotations

import asyncio
import logging

from deeparchive.irc.backend import BotBackend

logger = logging.getLogger(__name__)


class ShutdownRequested(Exception):
    """Raised (or signalled) when an admin ``kill`` is issued.

    The IRC layer's main loop catches this (or watches the event) and exits
    cleanly. Modelled as an event rather than a hard raise so a partial
    command sequence can drain before shutdown.
    """


class AdminCommandDispatcher:
    """Routes admin commands to the backend.

    Constructed with the :class:`BotBackend` it controls and the shutdown
    event from the main loop. Commands are terse strings — the same shape
    that will arrive over HTTP later (``"status"``, ``"quiet"``, ``"kill"``).
    """

    def __init__(
        self,
        backend: BotBackend,
        shutdown_event: asyncio.Event,
    ) -> None:
        self._backend = backend
        self._shutdown_event = shutdown_event

    def dispatch(self, command: str, args: str = "") -> list[str]:
        """Run an admin command and return reply lines.

        Unknown commands return a short error rather than raising, so a typo
        from the admin channel doesn't kill the process.
        """
        command = command.strip().lower()
        args = args.strip()

        handler = self._dispatch.get(command)
        if handler is None:
            return [f"unknown admin command: {command!r}"]
        # Handlers are unbound functions in the dispatch table; pass self
        # explicitly, matching the backend's dispatch convention.
        return handler(self, args)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def cmd_status(self, args: str) -> list[str]:
        status = self._backend.status()
        return [
            f"channel: {status['channel']}",
            f"investigators: {status['investigators']}",
            f"tracked nicks: {status['tracked_nicks']}",
            f"quiet: {'on' if status['quiet'] else 'off'}",
        ]

    def cmd_quiet(self, args: str) -> list[str]:
        """Toggle or set the quiet flag.

        ``quiet on`` / ``quiet off`` set it explicitly; bare ``quiet`` toggles.
        """
        if args in ("on", "true", "1"):
            self._backend.quiet = True
        elif args in ("off", "false", "0"):
            self._backend.quiet = False
        else:
            self._backend.quiet = not self._backend.quiet
        state = "on" if self._backend.quiet else "off"
        return [f"quiet is now {state}"]

    def cmd_kill(self, args: str) -> list[str]:
        """Request a clean shutdown.

        Sets the shutdown event; the main loop exits on its next tick. We
        return a line so the admin channel sees confirmation before the
        process goes away.
        """
        self._shutdown_event.set()
        logger.info("shutdown requested via admin command")
        return ["shutting down"]

    # ------------------------------------------------------------------
    # Dispatch table
    # ------------------------------------------------------------------

    _dispatch: dict = {
        "status": cmd_status,
        "quiet": cmd_quiet,
        "kill": cmd_kill,
    }
