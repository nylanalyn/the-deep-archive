"""Configuration loading.

The bot reads a single TOML file (default ``config.toml``, gitignored).
Secrets come from environment variables referenced as ``${VAR}`` or
``${VAR:-default}``, matching the convention used across the ircbot_core
bots so operators can reuse the same ``.env`` muscle memory.

Returned shape is typed dataclasses, not a bare dict, so the rest of the
codebase gets static guarantees and autocompletion.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or inconsistent."""


def _interpolate_env(value, _path: str = "") -> object:
    """Resolve ``${VAR}`` and ``${VAR:-default}`` references against the env.

    Mirrors the interpolation in ircbot_core's config loader. Unresolved vars
    with no default raise :class:`ConfigError` loudly, rather than silently
    emitting an empty string.
    """
    if isinstance(value, dict):
        return {k: _interpolate_env(v, f"{_path}.{k}" if _path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v, _path) for v in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        if ":-" in inner:
            name, default = inner.split(":-", 1)
        else:
            name, default = inner, None
        resolved = os.getenv(name, default)
        if resolved is None:
            raise ConfigError(f"environment variable {name!r} is not set (referenced at {_path})")
        return resolved
    return value


@dataclass(frozen=True, slots=True)
class SaslConfig:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class IrcConfig:
    server: str
    port: int
    ssl: bool
    tls_verify: bool
    nickname: str
    username: str
    realname: str
    channel: str
    sasl: SaslConfig | None
    day_boundary_timezone: str = "UTC"
    actions_per_day: int = 5


@dataclass(frozen=True, slots=True)
class DbConfig:
    path: str


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    irc: IrcConfig
    db: DbConfig
    logging: LoggingConfig
    # The path the config was loaded from; used by the logging setup to find
    # a sibling .env and to resolve relative data paths.
    config_path: Path = field(default_factory=Path)

    @property
    def config_dir(self) -> Path:
        return self.config_path.parent


def _load_dotenv(config_path: Path) -> None:
    """Load a sibling ``.env`` if present (best-effort, optional dep)."""
    env_path = config_path.parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:
        # Fall back to a tiny manual parser so operators without python-dotenv
        # installed still get ${VAR} resolution from a .env file.
        _parse_dotenv_manual(env_path)
        return
    load_dotenv(env_path)


def _parse_dotenv_manual(env_path: Path) -> None:
    """Minimal .env parser: KEY=VALUE lines, ``#`` comments, ``'``/``"`` quotes."""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        os.environ.setdefault(key, val)


def load_config(path: str | Path = "config.toml") -> Config:
    """Load, validate, and return the :class:`Config` from ``path``.

    Raises :class:`ConfigError` for missing files, missing required keys, or
    unresolved environment references.
    """
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"configuration file not found: {config_path}")

    _load_dotenv(config_path)

    with config_path.open("rb") as f:
        raw = tomllib.load(f)
    interpolated = _interpolate_env(raw)

    try:
        irc_raw = interpolated["irc"]
        db_raw = interpolated["db"]
    except KeyError as e:
        raise ConfigError(f"missing required section {e}") from None

    irc = _build_irc(irc_raw, config_path)
    db = _build_db(db_raw)
    log = _build_logging(interpolated.get("logging", {}))

    return Config(irc=irc, db=db, logging=log, config_path=config_path)


def _build_irc(irc_raw: object, config_path: Path) -> IrcConfig:
    if not isinstance(irc_raw, dict):
        raise ConfigError("[irc] must be a table")
    required = ("server", "port", "nickname", "channel")
    for key in required:
        if key not in irc_raw:
            raise ConfigError(f"missing required key [irc].{key}")

    server = irc_raw["server"]
    nickname = irc_raw["nickname"]
    channel = irc_raw["channel"]
    if not isinstance(server, str) or not server:
        raise ConfigError("[irc].server must be a non-empty string")
    if not isinstance(nickname, str) or not nickname:
        raise ConfigError("[irc].nickname must be a non-empty string")
    if not isinstance(channel, str) or not channel:
        raise ConfigError("[irc].channel must be a non-empty string")

    port = irc_raw["port"]
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("[irc].port must be an integer in [1, 65535]")

    sasl_raw = irc_raw.get("sasl")
    sasl: SaslConfig | None = None
    if sasl_raw is not None:
        if not isinstance(sasl_raw, dict):
            raise ConfigError("[irc.sasl] must be a table")
        su = sasl_raw.get("username")
        sp = sasl_raw.get("password")
        if not isinstance(su, str) or not su:
            raise ConfigError("[irc.sasl].username must be a non-empty string")
        if not isinstance(sp, str) or not sp:
            raise ConfigError("[irc.sasl].password must be a non-empty string")
        sasl = SaslConfig(username=su, password=sp)

    tz = str(irc_raw.get("day_boundary_timezone", "UTC"))
    # Validate the tz name eagerly so a typo fails at startup, not at the
    # first action reset at 00:00 local.
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as e:
        raise ConfigError(f"[irc].day_boundary_timezone {tz!r} is invalid: {e}") from None

    actions_per_day = irc_raw.get("actions_per_day", 5)
    if (
        not isinstance(actions_per_day, int)
        or isinstance(actions_per_day, bool)
        or actions_per_day < 1
    ):
        raise ConfigError("[irc].actions_per_day must be a positive integer")

    return IrcConfig(
        server=server,
        port=int(port),
        ssl=bool(irc_raw.get("ssl", True)),
        tls_verify=bool(irc_raw.get("tls_verify", True)),
        nickname=nickname,
        username=str(irc_raw.get("username", nickname)),
        realname=str(irc_raw.get("realname", "the-archivist")),
        channel=channel,
        sasl=sasl,
        day_boundary_timezone=tz,
        actions_per_day=actions_per_day,
    )


def _build_db(db_raw: object) -> DbConfig:
    if not isinstance(db_raw, dict):
        raise ConfigError("[db] must be a table")
    path = db_raw.get("path")
    if not isinstance(path, str) or not path:
        raise ConfigError("[db].path must be a non-empty string")
    return DbConfig(path=path)


def _build_logging(log_raw: object) -> LoggingConfig:
    if not isinstance(log_raw, dict):
        # An absent logging section is fine; we fall back to defaults.
        return LoggingConfig()
    level = str(log_raw.get("level", "INFO")).upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(
            f"[logging].level must be a valid level, got {level!r}"
        )
    file_value = log_raw.get("file")
    file_str = str(file_value) if file_value else None
    return LoggingConfig(level=level, file=file_str)
