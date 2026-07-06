"""Dataclasses modeling the four content domains, with validation.

These are pure shapes — no file loading here (that's Phase 3). Factory
functions (``ScarDefinition.from_dict`` etc.) are the contract enforcement
points: they check stat names, reject unknown effect types, and normalize
tuples. Phase 3's loader parses TOML and calls these factories; Phase 5's
case generation depends on the typed objects.

Design notes:

- Frozen dataclasses throughout: content is read-only after load. Mutation
  happens by editing the TOML and reloading, not by poking objects.
- Tuples (not lists) for all collection fields: hashable, immutable, signals
  "don't append to this".
- Validation fails loudly at construction with :class:`ContentError`, never
  silently coerces bad data. A typo in a scar's stat name should crash the
  loader, not produce a subtly-broken scar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The canonical stat names. Used to validate every StatModifier. Keeping this
# here (not in config) because content is the authority on what stats exist —
# the SPEC says "three stats only: Wit, Strength, Occultism."
VALID_STATS: frozenset[str] = frozenset({"wit", "strength", "occultism"})

# The resolution tiers, in order from worst to best. Used to validate the
# fragment library's tier keys and (later) resolution outcomes.
RESOLUTION_TIERS: tuple[str, ...] = (
    "disaster",
    "failure",
    "mixed_failure",
    "partial_success",
    "success",
    "clean_success",
)

# The relic effect types the engine knows how to apply. MVP implements only
# stat_bonus; the list structure supports adding more without changing the
# model. An unknown type at load time is a content error, not silently ignored.
VALID_EFFECT_TYPES: frozenset[str] = frozenset({"stat_bonus"})


class ContentError(ValueError):
    """Raised when content data is missing, malformed, or references unknown names."""


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatModifier:
    """A single stat change: which stat, and how much.

    Used by scars (permanent) and could be reused by relic effects that modify
    stats directly. ``stat`` is one of :data:`VALID_STATS`; ``delta`` may be
    negative (penalty), positive (bonus), or a pair on one scar.
    """

    stat: str
    delta: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any], context: str = "") -> "StatModifier":
        stat = raw.get("stat")
        delta = raw.get("delta")
        if not isinstance(stat, str) or not stat:
            raise ContentError(f"{context}: modifier.stat must be a non-empty string")
        if stat not in VALID_STATS:
            raise ContentError(
                f"{context}: modifier.stat {stat!r} is not a valid stat "
                f"(expected one of {sorted(VALID_STATS)})"
            )
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise ContentError(
                f"{context}: modifier.delta must be an integer, got {delta!r}"
            )
        return cls(stat=stat, delta=delta)


# ---------------------------------------------------------------------------
# Scars
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScarDefinition:
    """A permanent investigator trade-off.

    Modifiers are looked up from this definition at runtime by ``scar_key``;
    the DB row stores only the key (per the Phase 2 design decision: TOML is
    the single source of truth for scar mechanics).
    """

    key: str
    name: str
    description: str
    modifiers: tuple[StatModifier, ...]

    @classmethod
    def from_dict(cls, key: str, raw: dict[str, Any]) -> "ScarDefinition":
        name = raw.get("name")
        description = raw.get("description")
        if not isinstance(name, str) or not name:
            raise ContentError(f"scar {key!r}: name must be a non-empty string")
        if not isinstance(description, str) or not description:
            raise ContentError(f"scar {key!r}: description must be a non-empty string")

        raw_modifiers = raw.get("modifiers", [])
        if not isinstance(raw_modifiers, list):
            raise ContentError(f"scar {key!r}: modifiers must be a list")
        modifiers = tuple(
            StatModifier.from_dict(m, context=f"scar {key!r}")
            for m in raw_modifiers
        )
        return cls(key=key, name=name, description=description, modifiers=modifiers)


# ---------------------------------------------------------------------------
# Relics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelicEffect:
    """One effect on a relic. MVP: ``stat_bonus`` only.

    ``tags`` are inherited from the parent relic unless the effect overrides
    them (rare in MVP). The +1 applies to all stat checks during a File whose
    theme tags intersect this effect's tags.
    """

    type: str
    amount: int
    tags: tuple[str, ...]

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], parent_tags: tuple[str, ...], context: str = ""
    ) -> "RelicEffect":
        effect_type = raw.get("type")
        if not isinstance(effect_type, str) or not effect_type:
            raise ContentError(f"{context}: effect.type must be a non-empty string")
        if effect_type not in VALID_EFFECT_TYPES:
            raise ContentError(
                f"{context}: effect.type {effect_type!r} is not known "
                f"(expected one of {sorted(VALID_EFFECT_TYPES)})"
            )

        amount = raw.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise ContentError(
                f"{context}: effect.amount must be an integer, got {amount!r}"
            )

        # Effects inherit the relic's tags unless they declare their own. This
        # keeps the common case (one tag-matched +1) to a single tag list on
        # the relic, while allowing a future effect to target different tags.
        own_tags = raw.get("tags")
        if own_tags is None:
            tags = parent_tags
        elif isinstance(own_tags, list):
            tags = tuple(str(t) for t in own_tags)
        else:
            raise ContentError(f"{context}: effect.tags must be a list if present")
        return cls(type=effect_type, amount=amount, tags=tags)


@dataclass(frozen=True, slots=True)
class RelicDefinition:
    """A communal relic shelved in the Archive."""

    key: str
    name: str
    description: str
    tags: tuple[str, ...]
    effects: tuple[RelicEffect, ...]

    @classmethod
    def from_dict(cls, key: str, raw: dict[str, Any]) -> "RelicDefinition":
        name = raw.get("name")
        description = raw.get("description")
        if not isinstance(name, str) or not name:
            raise ContentError(f"relic {key!r}: name must be a non-empty string")
        if not isinstance(description, str) or not description:
            raise ContentError(f"relic {key!r}: description must be a non-empty string")

        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ContentError(f"relic {key!r}: tags must be a list")
        tags = tuple(str(t) for t in raw_tags)

        raw_effects = raw.get("effects", [])
        if not isinstance(raw_effects, list):
            raise ContentError(f"relic {key!r}: effects must be a list")
        effects = tuple(
            RelicEffect.from_dict(e, parent_tags=tags, context=f"relic {key!r}")
            for e in raw_effects
        )
        return cls(
            key=key, name=name, description=description, tags=tags, effects=effects
        )


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ThemeDefinition:
    """A File theme: the flavour and mechanical identity of a case.

    Case generation picks a theme, rolls a title from ``title_parts``, picks a
    location, and tags the File with ``tags`` (which relics respond to).
    """

    key: str
    name: str
    tags: tuple[str, ...]
    locations: tuple[str, ...]
    title_parts: dict[str, tuple[str, ...]]

    @classmethod
    def from_dict(cls, key: str, raw: dict[str, Any]) -> "ThemeDefinition":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ContentError(f"theme {key!r}: name must be a non-empty string")

        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ContentError(f"theme {key!r}: tags must be a list")
        tags = tuple(str(t) for t in raw_tags)

        raw_locations = raw.get("locations", [])
        if not isinstance(raw_locations, list) or not raw_locations:
            raise ContentError(
                f"theme {key!r}: locations must be a non-empty list"
            )
        locations = tuple(str(loc) for loc in raw_locations)

        raw_title_parts = raw.get("title_parts", {})
        if not isinstance(raw_title_parts, dict) or not raw_title_parts:
            raise ContentError(
                f"theme {key!r}: title_parts must be a non-empty table"
            )
        title_parts: dict[str, tuple[str, ...]] = {}
        for part_name, fragments in raw_title_parts.items():
            if not isinstance(fragments, list) or not fragments:
                raise ContentError(
                    f"theme {key!r}: title_parts.{part_name} must be a non-empty list"
                )
            title_parts[str(part_name)] = tuple(str(f) for f in fragments)

        return cls(
            key=key,
            name=name,
            tags=tags,
            locations=locations,
            title_parts=title_parts,
        )


# ---------------------------------------------------------------------------
# Fragments
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FragmentLibrary:
    """The hand-authored prose library, organized by context.

    The engine composes from these; it does not generate. Each section maps a
    key (theme key, tier name, or 'default') to a tuple of short lines. The
    engine picks one line at random when it needs prose for that context.
    """

    file_openings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    archive_returns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    resolution_tiers: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FragmentLibrary":
        def parse_section(section_name: str) -> dict[str, tuple[str, ...]]:
            section = raw.get(section_name, {})
            if not isinstance(section, dict):
                raise ContentError(
                    f"fragments.{section_name} must be a table"
                )
            parsed: dict[str, tuple[str, ...]] = {}
            for key, lines in section.items():
                if not isinstance(lines, list) or not lines:
                    raise ContentError(
                        f"fragments.{section_name}.{key} must be a non-empty list"
                    )
                parsed[str(key)] = tuple(str(line) for line in lines)
            return parsed

        return cls(
            file_openings=parse_section("file_openings"),
            archive_returns=parse_section("archive_returns"),
            resolution_tiers=parse_section("resolution_tiers"),
        )


# ---------------------------------------------------------------------------
# ContentPack — the aggregate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContentPack:
    """All loaded content, as typed objects. Phase 3's loader produces this."""

    themes: dict[str, ThemeDefinition]
    scars: dict[str, ScarDefinition]
    relics: dict[str, RelicDefinition]
    fragments: FragmentLibrary

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ContentPack":
        """Build a ContentPack from four parsed TOML tables.

        Each domain file (themes.toml, scars.toml, etc.) has a single
        top-level table keyed by the domain name (e.g. ``[themes]`` wrapping
        ``[themes.darkness]``). The loader passes one dict per file; this
        method receives them keyed by domain name::

            {
                "themes": {"darkness": {...}, "flood": {...}},
                "scars": {"paper_bones": {...}},
                "relics": {"brass_lantern": {...}},
                "fragments": {...},   # FragmentLibrary's raw shape
            }

        It unwraps each domain's outer table and delegates to the definition
        factories.
        """
        themes_raw = raw.get("themes", {})
        scars_raw = raw.get("scars", {})
        relics_raw = raw.get("relics", {})
        fragments_raw = raw.get("fragments", {})

        if not isinstance(themes_raw, dict):
            raise ContentError("themes must be a table")
        if not isinstance(scars_raw, dict):
            raise ContentError("scars must be a table")
        if not isinstance(relics_raw, dict):
            raise ContentError("relics must be a table")
        if not isinstance(fragments_raw, dict):
            raise ContentError("fragments must be a table")

        themes = {
            key: ThemeDefinition.from_dict(key, val)
            for key, val in themes_raw.items()
        }
        scars = {
            key: ScarDefinition.from_dict(key, val)
            for key, val in scars_raw.items()
        }
        relics = {
            key: RelicDefinition.from_dict(key, val)
            for key, val in relics_raw.items()
        }
        fragments = FragmentLibrary.from_dict(fragments_raw)

        return cls(themes=themes, scars=scars, relics=relics, fragments=fragments)

    @classmethod
    def from_files(cls, domains: dict[str, dict[str, Any]]) -> "ContentPack":
        """Build a ContentPack from per-domain parsed TOML.

        ``domains`` maps each domain name to that file's full parsed content
        (including the outer domain table). This is the shape Phase 3's loader
        produces naturally: one ``tomllib.load`` per file, keyed by name.

        Example::

            domains = {
                "themes":    tomllib.load(themes_file),     # {"themes": {...}}
                "scars":     tomllib.load(scars_file),
                "relics":    tomllib.load(relics_file),
                "fragments": tomllib.load(fragments_file),
            }
            pack = ContentPack.from_files(domains)
        """
        unwrapped: dict[str, Any] = {}
        for domain, file_content in domains.items():
            # Each file wraps its entries under the domain name: unwrap one
            # level. fragments is special — its top-level IS the library, so
            # it passes through without unwrapping.
            if domain == "fragments":
                unwrapped[domain] = file_content
            else:
                unwrapped[domain] = file_content.get(domain, {})
        return cls.from_dict(unwrapped)
