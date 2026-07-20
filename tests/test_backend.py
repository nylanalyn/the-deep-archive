"""Tests for the BotBackend — the pure seam between IRC and the game.

These exercise the full inbound path (message -> identity -> routing -> reply)
without any IRC dependency. The IRC layer is a thin adapter; everything that
matters is proven here.
"""

from __future__ import annotations

import pytest

from deeparchive.content import load_content
from deeparchive.irc.backend import BotBackend
from deeparchive.irc.commands import ParsedCommand
from deeparchive.rng import Rng


@pytest.fixture
def backend(migrated_conn):
    return BotBackend(
        conn=migrated_conn,
        channel="#the-deep-archive",
        content=load_content(),
        rng=Rng(42),
        background_rng=Rng(42),
        flavour_rng=Rng(42),
        action_flavour_rng=Rng(42),
    )


class TestHandleMessage:
    """The main inbound entry point."""

    def test_non_command_returns_empty(self, backend):
        assert backend.handle_message("alice", None, "hello there") == []

    def test_help_summarizes_game_and_commands(self, backend):
        replies = backend.handle_message("alice", None, "!help")
        assert len(replies) == 2
        assert "one File at a time" in replies[0]
        for command in (
            "!case",
            "!profile",
            "!room",
            "!investigate",
            "!interview",
            "!force",
            "!ritual",
            "!confront",
        ):
            assert command in replies[1]

    def test_profile_returns_personnel_file(self, backend):
        replies = backend.handle_message("alice", None, "!profile")
        assert replies[0].startswith("Personnel file: alice — ")
        assert replies[1:] == [
            "Effective: Wit 3 · Strength -1 · Occultism 1.",
            "Actions remaining today: 5.",
            "Background: Archivist · Completed Files: 0.",
            "Scars: none recorded.",
        ]

    def test_profile_uses_display_nick(self, backend):
        # Resolve with a different nick first to set display_nick.
        backend.resolve_identity("bob", "bob_acct")
        # Now seen as bob_away but identified by the same account.
        replies = backend.handle_message("bob_away", "bob_acct", "!profile")
        assert replies[0].startswith("Personnel file: bob_away — ")

    def test_profile_looks_up_another_known_nick(self, backend):
        backend.handle_message("bob", None, "hello")
        replies = backend.handle_message("alice", None, "!profile bob")
        assert replies[0].startswith("Personnel file: bob — ")

    def test_profile_lookup_is_case_insensitive(self, backend):
        backend.handle_message("Bob", None, "hello")
        replies = backend.handle_message("alice", None, "!profile bOB")
        assert replies[0].startswith("Personnel file: Bob — ")

    def test_unknown_profile_does_not_create_player(self, backend):
        replies = backend.handle_message("alice", None, "!profile unknown")
        assert replies == ["No personnel file bears that name."]
        assert backend.status()["investigators"] == 1

    def test_profile_includes_stats_and_scars(self, backend, migrated_conn):
        player = backend.resolve_identity("alice", None)
        migrated_conn.execute(
            "UPDATE players SET wit = 2, strength = -1, occultism = 1 WHERE id = ?",
            (player.id,),
        )
        migrated_conn.execute(
            "INSERT INTO scars (player_id, scar_key, description) VALUES (?, ?, ?)",
            (player.id, "glass_eye", "One eye is cold glass."),
        )
        migrated_conn.commit()

        profile = backend.handle_message("alice", None, "!profile")
        assert profile[0].startswith("Personnel file: alice — ")
        assert profile[0].removesuffix(".").split(" — ")[1] in {
            "Marked Investigator",
            "Reader in Altered Condition",
            "Amended Entry",
        }
        # glass_eye's +1 wit comes from content (scars.toml), not the DB row.
        assert profile[1:] == [
            "Effective: Wit 3 · Strength -1 · Occultism 1.",
            "Actions remaining today: 5.",
            "Background: Archivist · Completed Files: 0.",
            "Scars: Glass Eye — One eye is cold glass.",
        ]

    def test_case_describes_active_file(self, backend):
        replies = backend.handle_message("alice", None, "!case")
        assert replies[0].startswith("File: ")
        # Title/location, opening, progress band, approach hint.
        assert len(replies) == 4
        assert replies[3].startswith("A note in the margin:")

    def test_case_is_stable(self, backend):
        first = backend.handle_message("alice", None, "!case")
        second = backend.handle_message("alice", None, "!case")
        assert first == second

    def test_case_labels_sealed_file(self, backend, migrated_conn):
        migrated_conn.execute("UPDATE active_file SET is_sealed = 1 WHERE id = 1")
        migrated_conn.commit()
        assert backend.handle_message("alice", None, "!case")[0].startswith(
            "Sealed File:"
        )

    def test_room_describes_archive(self, backend):
        replies = backend.handle_message("alice", None, "!room")
        assert len(replies) == 4
        assert "closed Files rest" in replies[-1]

    @pytest.mark.parametrize("command", ["investigate", "interview", "force", "ritual"])
    def test_action_commands_are_live(self, backend, command):
        replies = backend.handle_message("alice", None, f"!{command}")
        # An action always narrates attempt + result; it may append a clue or a
        # danger omen after (both are legitimate extra beats), so allow trailers.
        assert len(replies) >= 2
        assert replies[0].startswith("You ")
        assert replies[1].startswith(("SUCCESS —", "FAILURE —"))
        assert "remain today" in replies[1]

    def test_only_action_outcome_line_is_delayed(self, backend):
        assert backend.reply_delay("!interview", 0, "You press the porter.") == 0
        assert backend.reply_delay("!interview", 1, "SUCCESS — done.") == 1.5
        assert backend.reply_delay("!interview", 1, "FAILURE — not today.") == 1.5
        # A resolution line in slot 1 (ready-File recovery) is not delayed.
        assert backend.reply_delay("!interview", 1, "The file is complete.") == 0
        assert backend.reply_delay("!profile", 1, "SUCCESS — done.") == 0

    def test_profile_reflects_consumed_action(self, backend):
        backend.handle_message("alice", None, "!investigate")
        replies = backend.handle_message("alice", None, "!profile")
        assert "Actions remaining today: 4." in replies

    def test_ready_file_resolves_without_consuming_action(self, backend, migrated_conn):
        migrated_conn.execute(
            "UPDATE active_file SET successes = success_threshold WHERE id = 1"
        )
        migrated_conn.commit()
        replies = backend.handle_message("alice", None, "!investigate")
        assert any(line.startswith("New File:") for line in replies)
        profile = backend.handle_message("alice", None, "!profile")
        assert "Actions remaining today: 5." in profile

    def test_unknown_command_gets_atmospheric_reply(self, backend):
        replies = backend.handle_message("alice", None, "!frobnicate")
        assert len(replies) == 1
        assert "does not recognise" in replies[0]

    def test_confront_without_sealed_file_is_quietly_rejected(self, backend):
        replies = backend.handle_message("alice", None, "!confront")
        assert replies == ["The Archive holds no Sealed File for confrontation."]

    def test_ready_sealed_file_blocks_normal_actions_without_cost(
        self, backend, migrated_conn
    ):
        migrated_conn.execute(
            "UPDATE active_file SET is_sealed = 1, arc_key = 'black_index', "
            "successes = success_threshold WHERE id = 1"
        )
        migrated_conn.commit()
        replies = backend.handle_message("alice", None, "!investigate")
        assert replies == [
            "The Sealed File is ready. The Archivist unlocks the final leaf: !confront."
        ]
        assert "Actions remaining today: 5." in backend.handle_message(
            "alice", None, "!profile"
        )

    def test_crossing_sealed_threshold_unlocks_confront(
        self, backend, migrated_conn
    ):
        player = backend.resolve_identity("alice", None)
        migrated_conn.execute(
            "UPDATE active_file SET is_sealed = 1, arc_key = 'black_index', "
            "success_threshold = 1, successes = 0 WHERE id = 1"
        )
        migrated_conn.execute(
            "UPDATE players SET wit = 10 WHERE id = ?", (player.id,)
        )
        migrated_conn.commit()
        seen = []
        for _ in range(5):
            seen.extend(backend.handle_message("alice", None, "!interview"))
            if any("permits: !confront" in line for line in seen):
                break
        assert any("permits: !confront" in line for line in seen)

    def test_empty_message_returns_empty(self, backend):
        assert backend.handle_message("alice", None, "") == []
        assert backend.handle_message("alice", None, "   ") == []


class TestIdentityRecordedEvenWhenQuiet:
    """When quiet, no replies — but identity is still resolved and stored."""

    def test_quiet_silences_replies(self, backend):
        backend.quiet = True
        assert backend.handle_message("alice", None, "!profile") == []

    def test_quiet_still_records_identity(self, backend):
        backend.quiet = True
        backend.handle_message("alice", None, "!profile")
        # The investigator was recorded despite silence.
        assert backend.status()["investigators"] == 1


class TestRouteCommand:
    """Direct routing tests bypassing message parsing."""

    def test_profile_routing(self, backend):
        player = backend.resolve_identity("alice", None)
        result = backend.route_command(player, ParsedCommand("profile", "", False))
        assert result[0].startswith("Personnel file: alice — ")

    def test_unknown_routing(self, backend):
        player = backend.resolve_identity("alice", None)
        result = backend.route_command(player, ParsedCommand("frobnicate", "", False))
        assert len(result) == 1
        assert "does not recognise" in result[0]

    def test_reserved_routing(self, backend):
        player = backend.resolve_identity("alice", None)
        result = backend.route_command(player, ParsedCommand("confront", "", True))
        assert len(result) == 1


class TestStatus:
    def test_empty_status(self, backend):
        status = backend.status()
        assert status["channel"] == "#the-deep-archive"
        assert status["investigators"] == 0
        assert status["tracked_nicks"] == 0
        assert status["quiet"] is False

    def test_status_after_resolves(self, backend):
        backend.resolve_identity("alice", "alice_acct")
        backend.resolve_identity("bob", None)
        backend.resolve_identity("alice_away", "alice_acct")  # same as alice
        status = backend.status()
        assert status["investigators"] == 2  # alice + bob
        # alice, alice_away, bob tracked
        assert status["tracked_nicks"] == 3


class TestIdentityPassthrough:
    """The backend exposes identity operations for the IRC layer to call."""

    def test_rebind_nick(self, backend):
        carol = backend.resolve_identity("carol", None)
        backend.rebind_nick("carol", "carol_away")
        # Old nick is gone from nick_map; the new nick resolves to the same
        # player (not a fresh one).
        again = backend.resolve_identity("carol_away", None)
        assert again.id == carol.id
        assert again.display_nick == "carol_away"
        assert backend.status()["tracked_nicks"] == 1

    def test_update_account(self, backend):
        backend.resolve_identity("dave", None)
        backend.update_account("dave", "dave_acct")
        player = backend.resolve_identity("dave", None)
        assert player.account == "dave_acct"
