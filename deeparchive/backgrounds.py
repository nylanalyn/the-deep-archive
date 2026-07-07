"""Weighted assignment of investigator backgrounds."""

from __future__ import annotations

from deeparchive.content.models import BackgroundDefinition, ContentPack
from deeparchive.rng import Rng


class BackgroundAssigner:
    def __init__(self, content: ContentPack, rng: Rng) -> None:
        self._backgrounds = content.backgrounds
        self._rng = rng

    def choose(self) -> BackgroundDefinition:
        weighted = tuple(
            background
            for background in self._backgrounds.values()
            for _ in range(background.weight)
        )
        return self._rng.choice(weighted)
