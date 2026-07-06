"""Logging setup with secret redaction.

Production runs log connection details and roll outcomes. SASL passwords and
tokens must never reach a log file. We attach a filter that scrubs known
secrets from every record before it is emitted, mirroring the pattern in
ircbot_core's shared_irc.py.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from pathlib import Path

from deeparchive.config import Config


class RedactFilter(logging.Filter):
    """Replace known secret substrings with ``[REDACTED]`` in log records."""

    def __init__(self, secrets: Iterable[str | None]) -> None:
        super().__init__()
        # Drop empties; a blank secret would redact nothing useful and the
        # `.replace("", ...)` call is also a footgun.
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for secret in self._secrets:
            if secret and secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED]")
        if redacted != message:
            # Mutating the record in place keeps the rendered form consistent
            # for any downstream handlers (file + stream both see the scrub).
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(config: Config) -> None:
    """Configure root logging from ``[logging]`` and attach secret redaction."""
    log_conf = config.logging
    level = getattr(logging, log_conf.level, logging.INFO)
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_conf.file:
        file_path = Path(log_conf.file)
        if not file_path.is_absolute():
            file_path = config.config_dir / file_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.insert(0, logging.FileHandler(file_path))

    # basicConfig is a no-op if handlers already exist; call force=True so a
    # reconfigure (e.g. tests, hot reload) actually takes effect.
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)

    secrets: list[str | None] = []
    if config.irc.sasl:
        secrets.append(config.irc.sasl.password)
    redact = RedactFilter(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redact)
