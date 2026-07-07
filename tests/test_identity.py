"""Tests for investigator identity resolution.

This is the heart of Phase 1: mapping mutable IRC nicks to stable UUID-keyed
investigators. The resolver is pure Python over a migrated SQLite DB, so every
branch and edge case is exercised directly without IRC.
"""

from __future__ import annotations

import pytest

from deeparchive.identity import IdentityResolver, Player


@pytest.fixture
def resolver(migrated_conn, background_assigner):
    return IdentityResolver(migrated_conn, background_assigner)


class TestResolveIdentityAccountBranch:
    """Account is authoritative: look up or create by account."""

    def test_new_account_creates_player(self, resolver):
        player = resolver.resolve_identity("alice", "alice_acct")
        assert player.account == "alice_acct"
        assert player.display_nick == "alice"
        assert player.id  # UUID populated
        assert resolver.count_investigators() == 1

    def test_existing_account_reuses_player(self, resolver):
        first = resolver.resolve_identity("alice", "alice_acct")
        # Same account, different nick — should resolve to the same player.
        second = resolver.resolve_identity("alice_away", "alice_acct")
        assert second.id == first.id
        assert second.display_nick == "alice_away"  # nick refreshed
        assert resolver.count_investigators() == 1

    def test_account_rebinds_nick_map(self, resolver):
        first = resolver.resolve_identity("alice", "alice_acct")
        resolver.resolve_identity("alice| lunch", "alice_acct")
        # The latest nick should be in nick_map.
        row = resolver._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", ("alice| lunch",)
        ).fetchone()
        assert row is not None
        assert row["player_id"] == first.id

    def test_star_account_treated_as_no_account(self, resolver):
        # IRC sends "*" on logout. Must fall through to nick fallback, not be
        # stored as a literal account named "*".
        first = resolver.resolve_identity("bob", None)
        assert first.account is None

        second = resolver.resolve_identity("bob", "*")
        assert second.id == first.id  # same player, not a new one
        assert second.account is None


class TestResolveIdentityNickBranch:
    """No account: fall back to nick_map."""

    def test_known_nick_resolves_without_account(self, resolver):
        first = resolver.resolve_identity("carol", None)
        # Same nick, still no account — same player.
        second = resolver.resolve_identity("carol", None)
        assert second.id == first.id
        assert resolver.count_investigators() == 1

    def test_nick_fallback_does_not_overwrite_account(self, resolver):
        # Alice identifies via account.
        alice = resolver.resolve_identity("alice", "alice_acct")
        # Later she's seen logged out (no account) on the same nick.
        logged_out = resolver.resolve_identity("alice", None)
        assert logged_out.id == alice.id
        # Her stored account must survive the logged-out sighting.
        assert logged_out.account == "alice_acct"


class TestResolveIdentityFreshBranch:
    """Unknown nick, no account: create a fresh investigator."""

    def test_unknown_nick_creates_player(self, resolver):
        player = resolver.resolve_identity("dave", None)
        assert player.account is None
        assert player.display_nick == "dave"
        assert player.id

    def test_nick_case_insensitive_lookup(self, resolver):
        # nick_map uses COLLATE NOCASE, so "Dave" and "dave" resolve together.
        first = resolver.resolve_identity("Dave", None)
        second = resolver.resolve_identity("dave", None)
        assert second.id == first.id
        assert resolver.count_investigators() == 1


class TestRebindNick:
    def test_basic_rebind(self, resolver):
        first = resolver.resolve_identity("eve", None)
        resolver.rebind_nick("eve", "eve_away")
        # Old nick should no longer be tracked.
        row = resolver._conn.execute(
            "SELECT player_id FROM nick_map WHERE nick = ?", ("eve",)
        ).fetchone()
        assert row is None
        # New nick resolves to the same player.
        again = resolver.resolve_identity("eve_away", None)
        assert again.id == first.id

    def test_rebind_updates_display_nick(self, resolver):
        resolver.resolve_identity("eve", None)
        resolver.rebind_nick("eve", "eve_away")
        row = resolver._conn.execute(
            "SELECT display_nick FROM players WHERE id = "
            "(SELECT player_id FROM nick_map WHERE nick = ?)",
            ("eve_away",),
        ).fetchone()
        assert row["display_nick"] == "eve_away"

    def test_rebind_collision_new_claimant_wins(self, resolver):
        # Two players. frank changes his nick to grace's nick.
        frank = resolver.resolve_identity("frank", None)
        grace = resolver.resolve_identity("grace", None)
        assert frank.id != grace.id

        resolver.rebind_nick("frank", "grace")
        # "grace" now points at frank (the new claimant).
        resolved = resolver.resolve_identity("grace", None)
        assert resolved.id == frank.id

    def test_rebind_same_nick_casefold_is_noop(self, resolver):
        resolver.resolve_identity("henry", None)
        before = resolver.count_tracked_nicks()
        resolver.rebind_nick("henry", "HENRY")
        after = resolver.count_tracked_nicks()
        assert before == after

    def test_rebind_unknown_old_nick_is_noop(self, resolver):
        # Old nick was never tracked — nothing crashes, nothing created.
        before = resolver.count_investigators()
        resolver.rebind_nick("nobody", "somebody")
        assert resolver.count_investigators() == before


class TestUpdateAccount:
    def test_sets_account_on_unidentified_player(self, resolver):
        resolver.resolve_identity("irene", None)
        resolver.update_account("irene", "irene_acct")
        player = resolver.resolve_identity("irene", None)
        assert player.account == "irene_acct"

    def test_does_not_overwrite_existing_account(self, resolver):
        resolver.resolve_identity("jack", "jack_acct")
        # A different account signal arrives. First account wins.
        resolver.update_account("jack", "intruder_acct")
        player = resolver.resolve_identity("jack", None)
        assert player.account == "jack_acct"

    def test_ignores_logout_star(self, resolver):
        resolver.resolve_identity("kate", "kate_acct")
        resolver.update_account("kate", "*")
        player = resolver.resolve_identity("kate", None)
        assert player.account == "kate_acct"

    def test_ignores_untracked_nick(self, resolver):
        # Nick not in nick_map yet — nothing happens, no crash.
        resolver.update_account("ghost", "ghost_acct")


class TestIdempotency:
    def test_repeated_resolution_same_nick_account(self, resolver):
        ids = set()
        for _ in range(5):
            player = resolver.resolve_identity("larry", "larry_acct")
            ids.add(player.id)
        assert len(ids) == 1
        assert resolver.count_investigators() == 1
        assert resolver.count_tracked_nicks() == 1

    def test_repeated_resolution_nick_only(self, resolver):
        ids = set()
        for _ in range(5):
            player = resolver.resolve_identity("mia", None)
            ids.add(player.id)
        assert len(ids) == 1


class TestEmptyNick:
    def test_empty_nick_raises(self, resolver):
        with pytest.raises(ValueError):
            resolver.resolve_identity("", None)

    def test_whitespace_nick_raises(self, resolver):
        with pytest.raises(ValueError):
            resolver.resolve_identity("   ", None)
