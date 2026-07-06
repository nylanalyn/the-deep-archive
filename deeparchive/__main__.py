"""Entry point: ``python -m deeparchive``.

Phase 0 wires the skeleton end-to-end without IRC: load config, set up logging,
connect, migrate, and report. The IRC loop arrives in Phase 1; for now this
proves the foundation holds together and gives operators a way to validate a
deployment (``python -m deeparchive --check``) before going live.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from deeparchive import __version__
from deeparchive.config import ConfigError, load_config
from deeparchive.db.connection import connect
from deeparchive.db.migrations import current_version, migrate
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

    # Phase 1 will start the IRC loop here. For Phase 0 there is nothing to
    # keep the process alive, so report and exit cleanly.
    logger.info("Phase 0 skeleton ready. IRC loop arrives in Phase 1.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
