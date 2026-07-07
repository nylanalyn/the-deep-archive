"""Tests for content domain dataclasses and validation.

Two layers:

1. Factory/validation tests — feed malformed dicts and assert clear errors.
2. Shipped-content tests — parse the actual .toml files in deeparchive/content
   and verify they load cleanly through the factories.

Phase 3's loader will add its own tests for file discovery and reload; here we
prove the shapes and the shipped defaults are coherent.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from deeparchive.content.models import (
    ContentError,
    ContentPack,
    FragmentLibrary,
    RelicDefinition,
    RelicEffect,
    RESOLUTION_TIERS,
    ScarDefinition,
    StatModifier,
    ThemeDefinition,
    VALID_STATS,
)

SHIPPED_CONTENT_DIR = Path(__file__).resolve().parent.parent / "deeparchive" / "content"


def _minimum_fragments() -> dict:
    return {
        "file_openings": {"default": ["A new file."]},
        "archive_returns": {"default": ["You return."]},
        "resolution_tiers": {
            tier: [f"The result is {tier}."] for tier in RESOLUTION_TIERS
        },
        "archive_descriptions": {"default": ["Shelves."]},
        "room_weather": {"default": ["Rain."]},
        "room_moods": {"default": ["Quiet."]},
        "personnel_titles": {
            "new": ["New"],
            "active": ["Active"],
            "veteran": ["Veteran"],
            "marked": ["Marked"],
        },
    }


def _load_shipped() -> ContentPack:
    """Load all four shipped TOML files into a ContentPack."""
    domains: dict[str, dict] = {}
    for name in (
        "themes", "scars", "relics", "backgrounds", "meta_arcs", "fragments"
    ):
        path = SHIPPED_CONTENT_DIR / f"{name}.toml"
        with path.open("rb") as f:
            domains[name] = tomllib.load(f)
    return ContentPack.from_files(domains)


# ---------------------------------------------------------------------------
# Shipped content loads cleanly
# ---------------------------------------------------------------------------


class TestShippedContent:
    """The .toml files shipped in the package must be valid content."""

    def test_all_files_parse(self):
        pack = _load_shipped()
        assert len(pack.themes) >= 1
        assert len(pack.scars) >= 1
        assert len(pack.relics) >= 1
        assert len(pack.backgrounds) >= 1
        assert len(pack.meta_arcs) >= 1
        assert len(pack.fragments.file_openings) >= 1

    def test_themes_have_expected_keys(self):
        pack = _load_shipped()
        # The three seed themes from the plan.
        assert {"darkness", "flood", "geometry"}.issubset(pack.themes.keys())

    def test_scars_have_expected_keys(self):
        pack = _load_shipped()
        # The four SPEC-named scar examples.
        assert {"paper_bones", "glass_eye", "scales", "borrowed_shadow"}.issubset(
            pack.scars.keys()
        )

    def test_relics_have_expected_keys(self):
        pack = _load_shipped()
        # The four SPEC-named relic examples.
        assert {"brass_lantern", "choir_register", "moth_eaten_map", "black_cabinet"}.issubset(
            pack.relics.keys()
        )

    def test_fragment_tiers_cover_all_resolution_tiers(self):
        pack = _load_shipped()
        for tier in RESOLUTION_TIERS:
            assert tier in pack.fragments.resolution_tiers, (
                f"fragment library missing resolution tier {tier!r}"
            )
            assert len(pack.fragments.resolution_tiers[tier]) > 0

    def test_archive_flavour_sections_are_shipped(self):
        fragments = _load_shipped().fragments
        assert fragments.archive_descriptions["default"]
        assert fragments.room_weather["default"]
        assert fragments.room_moods["default"]
        assert {"new", "active", "veteran", "marked"}.issubset(
            fragments.personnel_titles
        )

    def test_fragment_openings_cover_all_themes(self):
        # Every shipped theme should have at least a 'default' fallback, and
        # ideally its own themed openings.
        pack = _load_shipped()
        assert "default" in pack.fragments.file_openings
        for theme_key in pack.themes:
            # themed opening is optional, but if present must be non-empty
            if theme_key in pack.fragments.file_openings:
                assert len(pack.fragments.file_openings[theme_key]) > 0

    def test_all_scar_modifiers_use_valid_stats(self):
        pack = _load_shipped()
        for scar in pack.scars.values():
            for mod in scar.modifiers:
                assert mod.stat in VALID_STATS

    def test_all_relic_effects_have_tags(self):
        # Every effect must carry tags (inherited or own) — a tag-less
        # stat_bonus would never trigger, which is almost certainly a mistake.
        pack = _load_shipped()
        for relic in pack.relics.values():
            for effect in relic.effects:
                assert len(effect.tags) > 0, (
                    f"relic {relic.key!r} has an effect with no tags"
                )


# ---------------------------------------------------------------------------
# StatModifier validation
# ---------------------------------------------------------------------------


class TestStatModifier:
    def test_valid(self):
        mod = StatModifier.from_dict({"stat": "wit", "delta": 1})
        assert mod.stat == "wit"
        assert mod.delta == 1

    def test_negative_delta_allowed(self):
        mod = StatModifier.from_dict({"stat": "strength", "delta": -1})
        assert mod.delta == -1

    def test_invalid_stat_rejected(self):
        with pytest.raises(ContentError, match="not a valid stat"):
            StatModifier.from_dict({"stat": "charisma", "delta": 1})

    def test_missing_stat_rejected(self):
        with pytest.raises(ContentError, match="must be a non-empty string"):
            StatModifier.from_dict({"delta": 1})

    def test_non_integer_delta_rejected(self):
        with pytest.raises(ContentError, match="must be an integer"):
            StatModifier.from_dict({"stat": "wit", "delta": "high"})

    def test_bool_delta_rejected(self):
        # bool is a subclass of int in Python; catch it explicitly so a typo
        # like delta = true doesn't silently become delta = 1.
        with pytest.raises(ContentError, match="must be an integer"):
            StatModifier.from_dict({"stat": "wit", "delta": True})


# ---------------------------------------------------------------------------
# ScarDefinition validation
# ---------------------------------------------------------------------------


class TestScarDefinition:
    def test_valid_with_multiple_modifiers(self):
        scar = ScarDefinition.from_dict(
            "paper_bones",
            {
                "name": "Paper Bones",
                "description": "thin and dry",
                "modifiers": [
                    {"stat": "strength", "delta": -1},
                    {"stat": "occultism", "delta": 1},
                ],
            },
        )
        assert scar.key == "paper_bones"
        assert len(scar.modifiers) == 2

    def test_missing_name_rejected(self):
        with pytest.raises(ContentError, match="name must be"):
            ScarDefinition.from_dict("x", {"description": "d", "modifiers": []})

    def test_empty_modifiers_allowed(self):
        # A scar with no modifiers is odd but not structurally invalid — it's
        # just a pure-flavour scar. Don't reject; let content authors decide.
        scar = ScarDefinition.from_dict(
            "flavor_only", {"name": "Marker", "description": "d", "modifiers": []}
        )
        assert scar.modifiers == ()

    def test_bad_modifier_propagates_error(self):
        with pytest.raises(ContentError, match="not a valid stat"):
            ScarDefinition.from_dict(
                "x",
                {
                    "name": "X",
                    "description": "d",
                    "modifiers": [{"stat": "agility", "delta": 1}],
                },
            )


# ---------------------------------------------------------------------------
# RelicDefinition / RelicEffect validation
# ---------------------------------------------------------------------------


class TestRelicEffect:
    def test_inherits_parent_tags(self):
        effect = RelicEffect.from_dict(
            {"type": "stat_bonus", "amount": 1},
            parent_tags=("darkness",),
            context="relic x",
        )
        assert effect.tags == ("darkness",)

    def test_overrides_tags(self):
        effect = RelicEffect.from_dict(
            {"type": "stat_bonus", "amount": 1, "tags": ["flood"]},
            parent_tags=("darkness",),
            context="relic x",
        )
        assert effect.tags == ("flood",)

    def test_unknown_effect_type_rejected(self):
        with pytest.raises(ContentError, match="not known"):
            RelicEffect.from_dict(
                {"type": "time_travel", "amount": 1},
                parent_tags=(),
                context="relic x",
            )

    def test_missing_amount_rejected(self):
        with pytest.raises(ContentError, match="amount"):
            RelicEffect.from_dict(
                {"type": "stat_bonus"},
                parent_tags=("darkness",),
                context="relic x",
            )

    @pytest.mark.parametrize("tag", [1, True, ""])
    def test_invalid_override_tag_rejected(self, tag):
        with pytest.raises(ContentError, match="non-empty strings|must be strings"):
            RelicEffect.from_dict(
                {"type": "stat_bonus", "amount": 1, "tags": [tag]},
                parent_tags=("darkness",),
                context="relic x",
            )


class TestRelicDefinition:
    def test_valid(self):
        relic = RelicDefinition.from_dict(
            "brass_lantern",
            {
                "name": "Brass Lantern",
                "description": "steady flame",
                "tags": ["darkness"],
                "effects": [{"type": "stat_bonus", "amount": 1}],
            },
        )
        assert relic.key == "brass_lantern"
        assert len(relic.effects) == 1
        assert relic.effects[0].tags == ("darkness",)  # inherited

    def test_missing_tags_defaults_to_empty(self):
        relic = RelicDefinition.from_dict(
            "tagless",
            {"name": "N", "description": "d", "effects": []},
        )
        assert relic.tags == ()

    @pytest.mark.parametrize("tag", [1, True, ""])
    def test_invalid_tag_rejected(self, tag):
        with pytest.raises(ContentError, match="non-empty strings|must be strings"):
            RelicDefinition.from_dict(
                "bad",
                {"name": "N", "description": "d", "tags": [tag]},
            )


# ---------------------------------------------------------------------------
# ThemeDefinition validation
# ---------------------------------------------------------------------------


class TestThemeDefinition:
    def test_valid(self):
        theme = ThemeDefinition.from_dict(
            "darkness",
            {
                "name": "Darkness",
                "tags": ["darkness", "void"],
                "locations": ["the Stacks", "the Catalogue Hall"],
                "title_parts": {"prefix": ["The Quiet"], "noun": ["Lantern"]},
            },
        )
        assert theme.key == "darkness"
        assert theme.tags == ("darkness", "void")
        assert len(theme.locations) == 2
        assert theme.title_parts["prefix"] == ("The Quiet",)

    def test_empty_locations_rejected(self):
        with pytest.raises(ContentError, match="locations must be a non-empty"):
            ThemeDefinition.from_dict(
                "x",
                {"name": "X", "tags": [], "locations": [], "title_parts": {"noun": ["b"]}},
            )

    def test_empty_title_parts_rejected(self):
        with pytest.raises(ContentError, match="title_parts must be"):
            ThemeDefinition.from_dict(
                "x",
                {"name": "X", "tags": [], "locations": ["a"], "title_parts": {}},
            )

    def test_empty_title_fragment_list_rejected(self):
        with pytest.raises(ContentError, match="must be a non-empty list"):
            ThemeDefinition.from_dict(
                "x",
                {
                    "name": "X",
                    "tags": [],
                    "locations": ["a"],
                    "title_parts": {"noun": []},
                },
            )

    def test_title_parts_requires_noun(self):
        with pytest.raises(ContentError, match="contain a 'noun'"):
            ThemeDefinition.from_dict(
                "x",
                {
                    "name": "X",
                    "tags": [],
                    "locations": ["a"],
                    "title_parts": {"prefix": ["The Quiet"]},
                },
            )

    @pytest.mark.parametrize("tag", [1, True, ""])
    def test_invalid_tag_rejected(self, tag):
        with pytest.raises(ContentError, match="non-empty strings|must be strings"):
            ThemeDefinition.from_dict(
                "x",
                {
                    "name": "X",
                    "tags": [tag],
                    "locations": ["a"],
                    "title_parts": {"noun": ["File"]},
                },
            )


# ---------------------------------------------------------------------------
# FragmentLibrary validation
# ---------------------------------------------------------------------------


class TestFragmentLibrary:
    def test_valid(self):
        lib = FragmentLibrary.from_dict(
            {
                "file_openings": {"default": ["A new file."]},
                "archive_returns": {"default": ["You return."]},
                "resolution_tiers": {"success": ["The file is closed."]},
            }
        )
        assert lib.file_openings["default"] == ("A new file.",)

    def test_empty_sections_default_to_empty_dict(self):
        lib = FragmentLibrary.from_dict({})
        assert lib.file_openings == {}

    def test_empty_line_list_rejected(self):
        with pytest.raises(ContentError, match="must be a non-empty list"):
            FragmentLibrary.from_dict({"file_openings": {"default": []}})


# ---------------------------------------------------------------------------
# ContentPack assembly
# ---------------------------------------------------------------------------


class TestContentPack:
    def test_from_files_unwraps_domain_tables(self):
        # Simulates the loader: each file parsed to its full content.
        pack = ContentPack.from_files(
            {
                "themes": {"themes": {"darkness": {"name": "Darkness", "tags": [], "locations": ["a"], "title_parts": {"noun": ["x"]}}}},
                "scars": {"scars": {"x": {"name": "X", "description": "d", "modifiers": []}}},
                "relics": {"relics": {"y": {"name": "Y", "description": "d", "tags": [], "effects": []}}},
                "backgrounds": {"backgrounds": {"archivist": {"name": "Archivist", "description": "d", "weight": 1, "stats": {"wit": 2, "strength": 0, "occultism": 1}}}},
                "fragments": _minimum_fragments(),
            }
        )
        assert "darkness" in pack.themes
        assert "x" in pack.scars
        assert "y" in pack.relics
        assert "default" in pack.fragments.file_openings

    def test_from_dict_flat_shape(self):
        # from_dict takes already-unwrapped domain dicts.
        pack = ContentPack.from_dict(
            {
                "themes": {"darkness": {"name": "Darkness", "tags": [], "locations": ["a"], "title_parts": {"noun": ["x"]}}},
                "scars": {},
                "relics": {},
                "backgrounds": {"archivist": {"name": "Archivist", "description": "d", "weight": 1, "stats": {"wit": 2, "strength": 0, "occultism": 1}}},
                "fragments": _minimum_fragments(),
            }
        )
        assert "darkness" in pack.themes

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda raw: raw["themes"].clear(), "at least one theme"),
            (
                lambda raw: raw["fragments"]["file_openings"].pop("default"),
                "file_openings.default",
            ),
            (
                lambda raw: raw["fragments"]["archive_returns"].pop("default"),
                "archive_returns.default",
            ),
            (
                lambda raw: raw["fragments"]["resolution_tiers"].pop("failure"),
                "resolution_tiers missing",
            ),
        ],
    )
    def test_minimum_viable_pack_required(self, mutate, message):
        raw = {
            "themes": {
                "darkness": {
                    "name": "Darkness",
                    "tags": [],
                    "locations": ["a"],
                    "title_parts": {"noun": ["File"]},
                }
            },
            "scars": {},
            "relics": {},
            "backgrounds": {"archivist": {"name": "Archivist", "description": "d", "weight": 1, "stats": {"wit": 2, "strength": 0, "occultism": 1}}},
            "fragments": _minimum_fragments(),
        }
        mutate(raw)

        with pytest.raises(ContentError, match=message):
            ContentPack.from_dict(raw)
