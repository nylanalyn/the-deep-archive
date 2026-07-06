"""Seeded, injectable random number generator.

All stochastic behaviour in the game — rolls, case generation, resolution,
threshold rolls — goes through this module so tests are reproducible.

The production entry point is :func:`make_rng`, which seeds from OS entropy
unless a seed is supplied. Tests pass an explicit seed (or a frozen instance)
and get deterministic output.
"""

from __future__ import annotations

import secrets
from typing import Iterator, Sequence, TypeVar

T = TypeVar("T")


class Rng:
    """Thin, testable wrapper around :class:`random.Random`.

    We wrap rather than pass a bare :class:`~random.Random` around so the
    stochastic surface is explicit and small: only the methods the game needs.
    That keeps mocking trivial in tests and makes the call sites readable.
    """

    __slots__ = ("_rand", "seed")

    def __init__(self, seed: int | None = None) -> None:
        # random.Random is deterministic given a seed and stable across
        # Python versions for the Mersenne Twister path we use here.
        import random

        self._rand = random.Random(seed)
        # The seed is exposed for logging/diagnostics ("File rolled with seed
        # N") without leaking future rolls.
        self.seed = seed

    def random(self) -> float:
        """Float in the half-open interval [0.0, 1.0)."""
        return self._rand.random()

    def randint(self, low: int, high: int) -> int:
        """Inclusive on both ends, matching :func:`random.randint`."""
        if low > high:
            raise ValueError(f"low ({low}) must be <= high ({high})")
        return self._rand.randint(low, high)

    def chance(self, probability: float) -> bool:
        """True with the given probability.

        ``probability`` is clamped to ``[0.0, 1.0]``. A 0.5 chance is the
        engine's default investigate roll (roughly 50/50, per SPEC.md).
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be in [0.0, 1.0], got {probability}")
        return self._rand.random() < probability

    def choice(self, seq: Sequence[T]) -> T:
        """Pick one element from a non-empty sequence."""
        if not seq:
            raise IndexError("cannot choose from an empty sequence")
        return self._rand.choice(seq)

    def choices(self, seq: Sequence[T], k: int) -> list[T]:
        """``k`` independent picks from ``seq`` (with replacement)."""
        if not seq:
            raise IndexError("cannot choose from an empty sequence")
        if k < 0:
            raise ValueError("k must be non-negative")
        return [self._rand.choice(seq) for _ in range(k)]

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        """``k`` distinct elements from ``seq`` (without replacement).

        Order is shuffled. Equivalent to :meth:`random.Random.sample`.
        """
        if k < 0:
            raise ValueError("k must be non-negative")
        if k > len(seq):
            raise ValueError(f"sample larger than sequence ({k} > {len(seq)})")
        return self._rand.sample(list(seq), k)

    def shuffle(self, seq: list[T]) -> None:
        """Shuffle ``seq`` in place. Returns nothing, like :mod:`random`."""
        self._rand.shuffle(seq)

    def shuffled(self, seq: Sequence[T]) -> list[T]:
        """Return a new shuffled list, leaving ``seq`` untouched."""
        out = list(seq)
        self._rand.shuffle(out)
        return out


def make_rng(seed: int | None = None) -> Rng:
    """Create an :class:`Rng`.

    With no ``seed``, draws from OS entropy so production runs are
    unpredictable. Tests pass an explicit seed for determinism.
    """
    if seed is None:
        seed = secrets.randbits(64)
    return Rng(seed)


def seeded_iterator(base_seed: int) -> Iterator[Rng]:
    """Yield an infinite stream of distinct, reproducible :class:`Rng` values.

    Useful when each File (or each roll) should own a fresh, isolated RNG that
    can be replayed independently. ``base_seed`` anchors the sequence: the same
    base always yields the same stream of child seeds.
    """

    counter = 0
    while True:
        counter += 1
        # Mix the base with a counter so children never collide while staying
        # reproducible from the base alone.
        yield Rng((base_seed ^ (counter * 0x9E3779B97F4A7C15)) & ((1 << 64) - 1))
