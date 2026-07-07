"""Dataclasses modeling the content domains, with validation.

These are pure shapes; file loading lives in :mod:`deeparchive.content.loader`.
Factory functions (``ScarDefinition.from_dict`` etc.) are the contract
enforcement points: they check stat names, reject unknown effect types, and
normalize tuples. Phase 5's case generation depends on the typed objects.

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


def _parse_string_list(
    value: Any,
    context: str,
    *,
    field_name: str = "list",
    non_empty: bool = False,
) -> tuple[str, ...]:
    """Parse a TOML list into a tuple of non-empty strings.

    Used for tags, locations, title fragments — any list that should contain
    only meaningful strings. Rejects non-strings, empty strings, and bools
    (a Python int subclass footgun: ``true`` would otherwise stringify to
    ``"True"``). Tags drive mechanics, so we afford them the same strictness
    as names and descriptions.

    Parameters
    ----------
    non_empty:
        If ``True``, the list itself must contain at least one entry. Use for
        fields where emptiness is structurally invalid (e.g. locations).
    """
    if not isinstance(value, list):
        raise ContentError(f"{context}: {field_name} must be a list")
    if non_empty and not value:
        raise ContentError(f"{context}: {field_name} must be a non-empty list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or isinstance(item, bool):
            raise ContentError(
                f"{context}: {field_name} entries must be strings, got {item!r}"
            )
        if not item.strip():
            raise ContentError(
                f"{context}: {field_name} entries must be non-empty strings"
            )
        out.append(item)
    return tuple(out)


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


@dataclass(frozen=True, slots=True)
class BackgroundDefinition:
    """A weighted personnel background and its initial stat spread."""

    key: str
    name: str
    description: str
    weight: int
    stats: dict[str, int]

    @classmethod
    def from_dict(cls, key: str, raw: dict[str, Any]) -> "BackgroundDefinition":
        name = raw.get("name")
        description = raw.get("description")
        weight = raw.get("weight")
        stats = raw.get("stats")
        if not isinstance(name, str) or not name:
            raise ContentError(f"background {key!r}: name must be a non-empty string")
        if not isinstance(description, str) or not description:
            raise ContentError(
                f"background {key!r}: description must be a non-empty string"
            )
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
            raise ContentError(f"background {key!r}: weight must be a positive integer")
        if not isinstance(stats, dict) or set(stats) != VALID_STATS:
            raise ContentError(
                f"background {key!r}: stats must contain exactly {sorted(VALID_STATS)}"
            )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in stats.values()):
            raise ContentError(f"background {key!r}: stat values must be integers")
        return cls(
            key=key,
            name=name,
            description=description,
            weight=weight,
            stats={stat: int(stats[stat]) for stat in VALID_STATS},
        )


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
        else:
            tags = _parse_string_list(own_tags, context, field_name="effect.tags")
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
        tags = _parse_string_list(raw_tags, f"relic {key!r}", field_name="tags")

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
        tags = _parse_string_list(raw_tags, f"theme {key!r}", field_name="tags")

        raw_locations = raw.get("locations", [])
        locations = _parse_string_list(
            raw_locations, f"theme {key!r}", field_name="locations", non_empty=True
        )

        raw_title_parts = raw.get("title_parts", {})
        if not isinstance(raw_title_parts, dict) or not raw_title_parts:
            raise ContentError(
                f"theme {key!r}: title_parts must be a non-empty table"
            )
        # The generator (Phase 5) composes a title from prefix + noun + suffix.
        # ``noun`` is required — without it the generator has nothing to build
        # around. prefix and suffix are optional embellishments.
        if "noun" not in raw_title_parts:
            raise ContentError(
                f"theme {key!r}: title_parts must contain a 'noun' key"
            )
        title_parts: dict[str, tuple[str, ...]] = {}
        for part_name, fragments in raw_title_parts.items():
            title_parts[str(part_name)] = _parse_string_list(
                fragments,
                f"theme {key!r}",
                field_name=f"title_parts.{part_name}",
                non_empty=True,
            )

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
    archive_descriptions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    room_weather: dict[str, tuple[str, ...]] = field(default_factory=dict)
    room_moods: dict[str, tuple[str, ...]] = field(default_factory=dict)
    personnel_titles: dict[str, tuple[str, ...]] = field(default_factory=dict)

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
                parsed[str(key)] = _parse_string_list(
                    lines,
                    f"fragments.{section_name}.{key}",
                    field_name="lines",
                    non_empty=True,
                )
            return parsed

        return cls(
            file_openings=parse_section("file_openings"),
            archive_returns=parse_section("archive_returns"),
            resolution_tiers=parse_section("resolution_tiers"),
            archive_descriptions=parse_section("archive_descriptions"),
            room_weather=parse_section("room_weather"),
            room_moods=parse_section("room_moods"),
            personnel_titles=parse_section("personnel_titles"),
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
    backgrounds: dict[str, BackgroundDefinition]
    fragments: FragmentLibrary

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ContentPack":
        """Build a ContentPack from parsed TOML domain tables.

        Each domain file (themes.toml, scars.toml, etc.) has a single
        top-level table keyed by the domain name (e.g. ``[themes]`` wrapping
        ``[themes.darkness]``). The loader passes one dict per file; this
        method receives them keyed by domain name::

            {
                "themes": {"darkness": {...}, "flood": {...}},
                "scars": {"paper_bones": {...}},
                "relics": {"brass_lantern": {...}},
                "backgrounds": {"archivist": {...}},
                "fragments": {...},   # FragmentLibrary's raw shape
            }

        It unwraps each domain's outer table and delegates to the definition
        factories.
        """
        themes_raw = raw.get("themes", {})
        scars_raw = raw.get("scars", {})
        relics_raw = raw.get("relics", {})
        backgrounds_raw = raw.get("backgrounds", {})
        fragments_raw = raw.get("fragments", {})

        if not isinstance(themes_raw, dict):
            raise ContentError("themes must be a table")
        if not isinstance(scars_raw, dict):
            raise ContentError("scars must be a table")
        if not isinstance(relics_raw, dict):
            raise ContentError("relics must be a table")
        if not isinstance(backgrounds_raw, dict):
            raise ContentError("backgrounds must be a table")
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
        backgrounds = {
            key: BackgroundDefinition.from_dict(key, val)
            for key, val in backgrounds_raw.items()
        }
        fragments = FragmentLibrary.from_dict(fragments_raw)

        # Minimum viable pack: the engine cannot open without at least one
        # theme to generate from, a default file-opening line, a default
        # archive-return line, and every resolution tier covered. The per-
        # definition factories stay permissive for isolated tests; the
        # aggregate enforces what the running Archive actually needs.
        if not themes:
            raise ContentError("ContentPack requires at least one theme")
        if not backgrounds:
            raise ContentError("ContentPack requires at least one background")
        if "default" not in fragments.file_openings:
            raise ContentError(
                "ContentPack requires fragments.file_openings.default "
                "(the fallback when a theme has no themed opening)"
            )
        if "default" not in fragments.archive_returns:
            raise ContentError(
                "ContentPack requires fragments.archive_returns.default"
            )
        for section_name, section in (
            ("archive_descriptions", fragments.archive_descriptions),
            ("room_weather", fragments.room_weather),
            ("room_moods", fragments.room_moods),
        ):
            if "default" not in section:
                raise ContentError(
                    f"ContentPack requires fragments.{section_name}.default"
                )
        missing_titles = [
            key
            for key in ("new", "active", "veteran", "marked")
            if key not in fragments.personnel_titles
        ]
        if missing_titles:
            raise ContentError(
                f"ContentPack fragments.personnel_titles missing: {missing_titles}"
            )
        missing_tiers = [
            tier
            for tier in RESOLUTION_TIERS
            if tier not in fragments.resolution_tiers
        ]
        if missing_tiers:
            raise ContentError(
                f"ContentPack fragments.resolution_tiers missing: {missing_tiers}"
            )

        return cls(
            themes=themes,
            scars=scars,
            relics=relics,
            backgrounds=backgrounds,
            fragments=fragments,
        )

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
