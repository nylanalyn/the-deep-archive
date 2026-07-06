"""Entry point: ``python -m deeparchive``.

Two modes:

- ``--check``: validate config, connect, migrate, report status, exit. Does
  not connect to IRC. Useful for deployment smoke tests.
- (default): connect to IRC and run the bot until shutdown.

The run loop mirrors ircbot_core's async pattern: connect the pydle client,
then await a shutdown event that the admin ``kill`` command (or Ctrl-C) sets.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from deeparchive import __version__
from deeparchive.config import ConfigError, load_config
from deeparchive.content import ContentError, ContentLoader
from deeparchive.db.connection import connect
from deeparchive.db.migrations import migrate
from deeparchive.irc.admin import AdminCommandDispatcher
from deeparchive.irc.backend import BotBackend
from deeparchive.irc.bot import ArchivistBot
from deeparchive.logging_setup import setup_logging

logger = logging.getLogger("deeparchive.main")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deeparchive",
        description="The Deep Archive - persistent IRC anomaly-investigation game.",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to config.toml (default: config.toml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config, connect, migrate, report status, and exit. "
        "Does not connect to IRC. Useful for deployment smoke tests.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"the-deep-archive {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        # Logging isn't configured yet; go straight to stderr.
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2

    setup_logging(config)
    logger.info("the-deep-archive %s starting up", __version__)
    logger.info("config loaded from %s", config.config_path)

    try:
        # Phase 3 validates content at startup. The game layer begins consuming
        # this loader in Phase 5, when File generation is implemented.
        content = ContentLoader()
        logger.info(
            "content loaded: %d themes, %d scars, %d relics",
            len(content.current.themes),
            len(content.current.scars),
            len(content.current.relics),
        )
    except ContentError:
        logger.exception("content validation failed")
        return 4

    # Resolve the DB path relative to the config directory for predictable
    # behaviour regardless of the current working directory.
    db_path = Path(config.db.path)
    if not db_path.is_absolute():
        db_path = config.config_dir / db_path

    conn = connect(db_path)
    try:
        version = migrate(conn)
        logger.info("database migrated to version %d", version)
    except Exception:
        logger.exception("database migration failed")
        conn.close()
        return 3

    if args.check:
        logger.info("--check: database version %d, ready", version)
        conn.close()
        return 0

    try:
        asyncio.run(_run(config, conn))
    except KeyboardInterrupt:
        logger.info("interrupted by user")
    finally:
        conn.close()
    return 0


async def _run(config, conn) -> None:
    """Build the backend, connect the bot, and wait for shutdown.

    The shutdown event is shared with the :class:`AdminCommandDispatcher` so
    ``kill`` from the admin surface exits the loop cleanly. pydle handles its
    own reconnection; we only exit on explicit shutdown or fatal error.
    """
    backend = BotBackend(conn=conn, channel=config.irc.channel)
    shutdown_event = asyncio.Event()
    # The admin dispatcher is constructed now but not yet reachable from
    # outside the process: the HTTP bridge that discord_admin.py speaks
    # (/v1/command, /v1/events) arrives in the cross-cutting admin phase.
    # Until then it exists as an internal seam so Phase 1 has a clean
    # shutdown path (kill sets shutdown_event above).
    _admin = AdminCommandDispatcher(backend=backend, shutdown_event=shutdown_event)

    bot = ArchivistBot(config=config, backend=backend)
    connected = False
    try:
        await bot.connect()
        connected = True
        logger.info("bot connected; entering main loop")
        await shutdown_event.wait()
    except Exception:
        logger.exception("bot run loop failed")
        raise
    finally:
        # Only attempt a clean disconnect if we actually connected. If
        # connect() itself failed (SASL rejection, network error), calling
        # disconnect() on a half-initialized bot can raise a secondary
        # exception that masks the real failure.
        if connected:
            try:
                await bot.request_shutdown()
            except Exception:
                logger.debug("shutdown did not complete cleanly", exc_info=True)
        logger.info("the-deep-archive shutting down")


if __name__ == "__main__":
    raise SystemExit(main())
