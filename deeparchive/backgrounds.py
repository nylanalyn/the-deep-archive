"""No-duplicate assignment of investigator backgrounds.

A small IRC channel produced a pile of identical classes under the old
weighted-with-replacement draw. Assignment now hands out distinct classes
until the roster has one of each (a min-count rotation), so a handful of
players end up differentiated and a hard File genuinely needs a specific
person. Rare backgrounds (the Gambler) sit outside the rotation and only
surface on their own long odds.
"""

from __future__ import annotations

from collections.abc import Mapping

from deeparchive.content.models import BackgroundDefinition, ContentPack
from deeparchive.rng import Rng

# Odds that a new investigator is drawn from the rare pool instead of the
# rotation. Independent per player, so the Gambler stays a genuine surprise.
RARE_ODDS = 0.04


class BackgroundAssigner:
    def __init__(self, content: ContentPack, rng: Rng) -> None:
        self._backgrounds = content.backgrounds
        self._rng = rng

    def choose(self, existing_counts: Mapping[str, int] | None = None) -> BackgroundDefinition:
        """Pick a background given how many players already hold each one.

        ``existing_counts`` maps ``background_key`` -> current holder count.
        The least-held common background wins (random tiebreak), so the first
        players catalogued get distinct classes. A rare background may pre-empt
        the rotation on its own odds.
        """
        counts = existing_counts or {}
        common = [b for b in self._backgrounds.values() if not b.rare]
        rare = [b for b in self._backgrounds.values() if b.rare]

        if rare and self._rng.chance(RARE_ODDS):
            return self._rng.choice(rare)
        if not common:
            # A pack of only rare backgrounds: fall back to the whole set.
            return self._rng.choice(tuple(self._backgrounds.values()))

        fewest = min(counts.get(b.key, 0) for b in common)
        pool = tuple(b for b in common if counts.get(b.key, 0) == fewest)
        return self._rng.choice(pool)
