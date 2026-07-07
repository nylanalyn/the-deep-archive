"""Generated action attempts and explicit outcome narration."""

from __future__ import annotations

import pytest

from deeparchive.action_flavour import ActionNarrator
from deeparchive.content import load_content
from deeparchive.rng import Rng


@pytest.mark.parametrize("action", ["investigate", "interview", "force", "ritual"])
def test_each_action_generates_attempt_and_outcomes(action) -> None:
    content = load_content()
    narrator = ActionNarrator(content, Rng(42))
    attempt = narrator.attempt(action)
    success = narrator.result(action, True)
    failure = narrator.result(action, False)
    assert attempt.startswith("You ") and attempt.endswith(".")
    assert success in content.fragments.action_successes[action]
    assert failure in content.fragments.action_failures[action]


def test_narration_is_reproducible_without_mechanical_rng() -> None:
    content = load_content()
    first = ActionNarrator(content, Rng(7))
    second = ActionNarrator(content, Rng(7))
    assert first.attempt("interview") == second.attempt("interview")
    assert first.result("interview", True) == second.result("interview", True)
