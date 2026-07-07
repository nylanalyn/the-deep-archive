"""Content-driven attempt and outcome narration for player actions."""

from __future__ import annotations

from typing import Protocol

from deeparchive.content.models import ContentPack


class ChoiceSource(Protocol):
    def choice(self, seq): ...


class ActionNarrator:
    def __init__(self, content: ContentPack, rng: ChoiceSource) -> None:
        self._fragments = content.fragments
        self._rng = rng

    def attempt(self, action: str) -> str:
        verb = self._rng.choice(self._fragments.action_verbs[action])
        target = self._rng.choice(self._fragments.action_targets[action])
        method = self._rng.choice(self._fragments.action_methods[action])
        return f"You {verb} {target} {method}."

    def result(self, action: str, success: bool) -> str:
        table = (
            self._fragments.action_successes
            if success
            else self._fragments.action_failures
        )
        return self._rng.choice(table[action])
