"""Load and atomically reload the Archive's TOML content pack."""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Protocol

from deeparchive.content.models import ContentError, ContentPack

CONTENT_DOMAINS: tuple[str, ...] = (
    "themes",
    "scars",
    "relics",
    "backgrounds",
    "fragments",
)


class _ContentRoot(Protocol):
    def joinpath(self, *descendants: str): ...


def _read_domain(root: _ContentRoot, domain: str) -> dict:
    source = root.joinpath(f"{domain}.toml")
    try:
        raw_bytes = source.read_bytes()
    except FileNotFoundError:
        raise ContentError(f"missing required content file: {domain}.toml") from None
    except OSError as exc:
        raise ContentError(f"could not read {domain}.toml: {exc}") from exc

    try:
        parsed = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ContentError(f"{domain}.toml is not valid UTF-8: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ContentError(f"invalid TOML in {domain}.toml: {exc}") from exc

    if not isinstance(parsed, dict):  # defensive: tomllib currently always returns dict
        raise ContentError(f"{domain}.toml must contain a TOML table")
    return parsed


def load_content(directory: str | Path | None = None) -> ContentPack:
    """Load and validate all content domains.

    With no directory, files are read through :mod:`importlib.resources`, so
    the defaults work from both a source checkout and an installed wheel.
    A directory override is useful for deployments with custom content.
    """
    root: _ContentRoot
    if directory is None:
        root = resources.files("deeparchive.content")
    else:
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            raise ContentError(f"content directory not found: {root}")

    domains = {domain: _read_domain(root, domain) for domain in CONTENT_DOMAINS}
    return ContentPack.from_files(domains)


class ContentLoader:
    """Own the current immutable content pack and replace it atomically."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self._directory = directory
        self._current = load_content(directory)

    @property
    def current(self) -> ContentPack:
        return self._current

    def reload(self) -> ContentPack:
        """Validate a fresh pack before publishing it as current.

        If loading fails, the exception propagates and ``current`` remains the
        last valid pack.
        """
        replacement = load_content(self._directory)
        self._current = replacement
        return replacement
