"""Content domain package.

Holds the shipped default TOML content files (version-controlled) and the
dataclasses that model them. Phase 3's loader reads these files; this package
defines the shapes and the shipped defaults.

Each domain is one TOML file:
- themes.toml    — File themes (the spine of case generation)
- scars.toml     — permanent investigator trade-offs
- relics.toml    — communal relics with effect lists
- backgrounds.toml — weighted investigator backgrounds and starting stats
- meta_arcs.toml — hidden recurring patterns and Sealed File rewards
- fragments.toml — hand-authored atmospheric prose
"""

from deeparchive.content.loader import CONTENT_DOMAINS, ContentLoader, load_content
from deeparchive.content.models import ContentError, ContentPack

__all__ = [
    "CONTENT_DOMAINS",
    "ContentError",
    "ContentLoader",
    "ContentPack",
    "load_content",
]
