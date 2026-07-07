"""The IRC layer — the only module that imports pydle.

``ArchivistBot`` is a thin adapter over :class:`BotBackend`. It translates
pydle's event callbacks into calls on the pure backend seam and sends the
backend's reply strings back to the channel. Everything game-meaningful lives
behind the backend; this file holds no logic that deserves a unit test.

Proven patterns copied from ircbot_core's ``bot/irc_client.py``:

- ``RECONNECT_MAX_ATTEMPTS = None`` for pydle's infinite reconnect backoff.
- SASL via the four constructor kwargs (``sasl_username`` etc.), not a custom
  mechanism.
- ``on_connect`` sets bot mode ``+B`` then joins the configured channel.
- ``on_unknown`` is a no-op (pydle emits it for every IRCv3 extension; logging
  it is noisy).
- ``on_raw`` calls ``super()`` so dispatch keeps working, and drops TAGMSG.
- TLS uses ``tls=`` / ``tls_verify=`` at :meth:`connect` time (pydle 1.x),
  not a constructor ``ssl=`` kwarg.

Identity integration relies on pydle's built-in capability negotiation: the
default ``pydle.Client`` auto-requests ``account-notify``, ``extended-join``,
and ``account-tag``. We read the account from ``self.users[nick]["account"]``,
which pydle keeps live from those capabilities.

Live IRC validation checklist (run on first real deployment — these can't be
unit-tested because they depend on pydle's capability negotiation with a real
server):
  - join while identified -> !profile shows the same player across reconnects
  - log out / log in (account-notify) -> identity persists, account updates
  - nick change in channel (on_nick_change) -> same investigator, nick rebound
  - join unidentified, later identify -> update_account links the account
  - SASL rejection -> bot fails to connect cleanly (no secondary exception)
"""

from __future__ import annotations

import asyncio
import logging

import pydle

from deeparchive.config import Config
from deeparchive.irc.backend import BotBackend

logger = logging.getLogger(__name__)


class ArchivistBot(pydle.Client):
    """IRC adapter for the-archivist.

    Constructed from a loaded :class:`Config` and a :class:`BotBackend`.
    Reconnects indefinitely; joins the single configured Archive channel.
    """

    # Retry forever on unexpected disconnect. The Archive is always open.
    RECONNECT_MAX_ATTEMPTS = None

    def __init__(self, config: Config, backend: BotBackend) -> None:
        irc = config.irc
        # SASL: only configure when credentials are present, matching
        # ircbot_core's idiom. sasl_mechanism PLAIN is the universal default.
        sasl_username = irc.sasl.username if irc.sasl else None
        sasl_password = irc.sasl.password if irc.sasl else None
        sasl_identity = sasl_username if sasl_username else None
        sasl_mechanism = "PLAIN" if (sasl_username and sasl_password) else None

        super().__init__(
            nickname=irc.nickname,
            username=irc.username,
            realname=irc.realname,
            sasl_identity=sasl_identity,
            sasl_username=sasl_username,
            sasl_password=sasl_password,
            sasl_mechanism=sasl_mechanism,
        )
        self._config = config
        self._backend = backend
        self._channel = irc.channel
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self, **kwargs) -> None:  # type: ignore[override]
        """Connect with TLS settings from config.

        pydle 1.x takes ``tls`` / ``tls_verify`` at connect time (not in the
        constructor), so we inject them here and let callers override.
        """
        irc = self._config.irc
        kwargs.setdefault("hostname", irc.server)
        kwargs.setdefault("port", irc.port)
        kwargs.setdefault("tls", irc.ssl)
        kwargs.setdefault("tls_verify", irc.tls_verify)
        await super().connect(**kwargs)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def on_connect(self) -> None:
        """Called once IRC registration (incl. SASL) completes."""
        logger.info("connected to %s as %s", self._config.irc.server, self.nickname)
        # Set user mode +B so the server identifies us as a bot. Non-fatal if
        # the server rejects it.
        try:
            await self.rawmsg("MODE", self.nickname, "+B")
        except Exception:
            logger.debug("could not set +B", exc_info=True)
        await self.join(self._channel)
        logger.info("joined %s", self._channel)
        # One unprompted line when the day turns (allowances reset). The task
        # survives reconnects; sends while disconnected fail quietly and the
        # loop re-arms for the next boundary.
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            # Pad past the boundary so the line lands in the new day.
            await asyncio.sleep(self._backend.seconds_until_heartbeat() + 1.0)
            line = self._backend.heartbeat_line()
            if line is None:
                continue
            try:
                await self.message(self._channel, line)
            except Exception:
                logger.debug("heartbeat send failed", exc_info=True)

    async def on_disconnect(self, expected: bool) -> None:  # type: ignore[override]
        if expected:
            logger.info("disconnected (expected)")
        else:
            logger.warning("disconnected (unexpected; pydle will reconnect)")
        await super().on_disconnect(expected)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def on_channel_message(self, target: str, by: str, message: str) -> None:
        """A channel PRIVMSG. Route to the backend and relay replies."""
        # Ignore our own messages (echo-message may or may not be negotiated).
        if by == self.nickname:
            return

        # pydle keeps the account live in self.users under the nick. The key
        # may be absent right after connect if we haven't seen the user join;
        # fall back to None (nick-only identity) in that case.
        account = self._account_for(by)
        replies = self._backend.handle_message(by, account, message)
        for index, line in enumerate(replies):
            delay = self._backend.reply_delay(message, index, line)
            if delay:
                await asyncio.sleep(delay)
            await self.message(target, line)

    # ------------------------------------------------------------------
    # Identity events
    # ------------------------------------------------------------------

    async def on_join(self, channel: str, user: str) -> None:
        """A user joined. Resolve their identity so they're known on sight.

        We do NOT greet — the SPEC says the bot speaks mostly when spoken to.
        Resolution here just ensures the investigator exists and their account
        is recorded before their first command. This is deliberate: in this
        game presence is opting in (see backend.handle_message's policy note).
        """
        if user == self.nickname:
            return
        account = self._account_for(user)
        self._backend.resolve_identity(user, account)

    async def on_nick_change(self, old: str, new: str) -> None:  # type: ignore[override]
        """An observed nick change. Rebind identity.

        pydle (with account-notify negotiated) preserves the account across
        the rename in its own user tracking, so we only need to mirror the
        nick change into our nick_map.
        """
        self._backend.rebind_nick(old, new)

    async def on_raw_account(self, message) -> None:  # type: ignore[override]
        """An ACCOUNT message (account-notify). Mirror to our DB.

        pydle updates self.users first via super(), then we record the new
        account association (first-account-wins) in our own state.
        """
        await super().on_raw_account(message)
        nick = self._parse_user(message.source)[0]
        # params[0] is the account, or "*" for a logout.
        account = message.params[0] if message.params else None
        self._backend.update_account(nick, account)

    # ------------------------------------------------------------------
    # pydle bookkeeping (silence the noisy bits)
    # ------------------------------------------------------------------

    async def on_raw(self, message) -> None:  # type: ignore[override]
        # Drop TAGMSG (IRCv3 typing indicators etc.) to avoid log noise, then
        # hand to super() so normal dispatch keeps working.
        if message.command == "TAGMSG":
            return
        await super().on_raw(message)

    async def on_unknown(self, command: str, *params) -> None:  # type: ignore[override]
        # pydle fires this for every IRCv3 extension it doesn't model. Logging
        # it is pure noise; ircbot_core makes it a no-op and so do we.
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _account_for(self, nick: str) -> str | None:
        """Read the current account for ``nick`` from pydle's user tracking.

        Returns the account string, or ``None`` if the nick isn't tracked yet
        or has no account. The ``account`` field is kept live by pydle from
        account-notify, extended-join, and account-tag capabilities.
        """
        user = self.users.get(nick)
        if user is None:
            return None
        # pydle stores account as a string or None; "*" has already been
        # mapped to None by on_raw_account internally, but be defensive.
        account = user.get("account")
        if account in (None, "", "*"):
            return None
        return account

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def request_shutdown(self) -> None:
        """Disconnect cleanly. Called when the admin ``kill`` fires."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        await self.disconnect(expected=True)
