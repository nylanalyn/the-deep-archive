"""Tests for the seeded RNG.

Reproducibility is the whole point: same seed, same sequence. These tests
also pin the public surface (chance, choice, sample) so engine code can rely
on it.
"""
from __future__ import annotations

import secrets

import pytest

from deeparchive.rng import Rng, make_rng, seeded_iterator


class TestReproducibility:
    def test_same_seed_same_sequence(self):
        a = Rng(seed=42)
        b = Rng(seed=42)
        assert [a.random() for _ in range(10)] == [b.random() for _ in range(10)]

    def test_different_seed_different_sequence(self):
        a = Rng(seed=1)
        b = Rng(seed=2)
        assert [a.random() for _ in range(10)] != [b.random() for _ in range(10)]

    def test_make_rng_unseeded_is_random(self):
        # Two unseeded RNGs should (with overwhelming probability) diverge.
        a = make_rng()
        b = make_rng()
        assert [a.random() for _ in range(5)] != [b.random() for _ in range(5)]

    def test_make_rng_unseeded_exposes_seed(self):
        # The seed is recorded so a production roll can be replayed for debug.
        rng = make_rng()
        assert rng.seed is not None
        # And replaying with that seed reproduces the rolls.
        replay = Rng(seed=rng.seed)
        assert [rng.random() for _ in range(5)] == [replay.random() for _ in range(5)]

    def test_seeded_iterator_is_reproducible(self):
        stream_a = seeded_iterator(123)
        stream_b = seeded_iterator(123)
        a = next(stream_a)
        b = next(stream_b)
        assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]

    def test_seeded_iterator_children_diverge(self):
        stream = seeded_iterator(123)
        first = next(stream)
        second = next(stream)
        assert first.seed != second.seed
        assert [first.random() for _ in range(5)] != [second.random() for _ in range(5)]


class TestRandint:
    def test_within_bounds(self):
        rng = Rng(seed=0)
        for _ in range(1000):
            value = rng.randint(1, 6)
            assert 1 <= value <= 6

    def test_inclusive_high(self):
        # Both ends must be reachable. With enough draws on a tiny range,
        # we should see the endpoints.
        rng = Rng(seed=7)
        seen = {rng.randint(1, 2) for _ in range(100)}
        assert seen == {1, 2}

    def test_low_equal_high(self):
        assert Rng(seed=0).randint(5, 5) == 5

    def test_inverted_bounds_raises(self):
        with pytest.raises(ValueError):
            Rng(seed=0).randint(5, 1)


class TestChance:
    def test_always_true_at_one(self):
        rng = Rng(seed=0)
        assert all(rng.chance(1.0) for _ in range(100))

    def test_always_false_at_zero(self):
        rng = Rng(seed=0)
        assert not any(rng.chance(0.0) for _ in range(100))

    def test_roughly_half_at_point_five(self):
        # The SPEC's investigate action is "roughly 50/50". Verify the mean
        # lands near 0.5 over a healthy sample without being brittle about it.
        rng = Rng(seed=99)
        draws = [rng.chance(0.5) for _ in range(4000)]
        mean = sum(draws) / len(draws)
        assert 0.45 < mean < 0.55

    def test_rejects_out_of_range(self):
        rng = Rng(seed=0)
        with pytest.raises(ValueError):
            rng.chance(-0.1)
        with pytest.raises(ValueError):
            rng.chance(1.1)


class TestChoice:
    def test_picks_member_of_sequence(self):
        rng = Rng(seed=0)
        seq = ["a", "b", "c", "d"]
        for _ in range(100):
            assert rng.choice(seq) in seq

    def test_empty_sequence_raises(self):
        with pytest.raises(IndexError):
            Rng(seed=0).choice([])

    def test_choices_with_replacement(self):
        rng = Rng(seed=3)
        picks = rng.choices(["x", "y"], k=50)
        assert len(picks) == 50
        assert all(p in {"x", "y"} for p in picks)

    def test_choices_zero_k(self):
        assert Rng(seed=0).choices(["x"], k=0) == []


class TestSample:
    def test_distinct_elements(self):
        rng = Rng(seed=0)
        out = rng.sample(range(10), k=4)
        assert len(out) == 4
        assert len(set(out)) == 4

    def test_sample_full_range(self):
        rng = Rng(seed=0)
        out = rng.sample([1, 2, 3], k=3)
        assert sorted(out) == [1, 2, 3]

    def test_oversample_raises(self):
        with pytest.raises(ValueError):
            Rng(seed=0).sample([1, 2, 3], k=4)

    def test_negative_k_raises(self):
        with pytest.raises(ValueError):
            Rng(seed=0).sample([1, 2, 3], k=-1)


class TestShuffle:
    def test_shuffle_preserves_membership(self):
        rng = Rng(seed=0)
        seq = list(range(20))
        rng.shuffle(seq)
        assert sorted(seq) == list(range(20))

    def test_shuffled_does_not_mutate_original(self):
        rng = Rng(seed=0)
        original = [1, 2, 3, 4, 5]
        result = rng.shuffled(original)
        assert original == [1, 2, 3, 4, 5]
        assert sorted(result) == [1, 2, 3, 4, 5]
