"""Tests for command parsing and the command surface."""

from __future__ import annotations

import pytest

from deeparchive.irc.commands import (
    PLAYER_COMMANDS,
    RESERVED_COMMANDS,
    ParsedCommand,
    is_known_command,
    parse_command,
)


class TestParseCommand:
    def test_basic_command_no_args(self):
        assert parse_command("!profile") == ParsedCommand("profile", "", False)

    def test_command_with_args(self):
        assert parse_command("!profile alice") == ParsedCommand("profile", "alice", False)

    def test_preserves_multiword_args(self):
        # Args after the first split survive whole.
        result = parse_command("!profile alice the brave")
        assert result == ParsedCommand("profile", "alice the brave", False)

    def test_case_insensitive_command(self):
        # Commands are lowercased; args are not.
        result = parse_command("!PROFILE Alice")
        assert result == ParsedCommand("profile", "Alice", False)

    def test_strips_surrounding_whitespace(self):
        result = parse_command("   !profile   alice   ")
        assert result == ParsedCommand("profile", "alice", False)

    def test_no_prefix_returns_none(self):
        assert parse_command("hello there") is None

    def test_empty_message_returns_none(self):
        assert parse_command("") is None
        assert parse_command("   ") is None

    def test_bare_prefix_returns_none(self):
        # "!" with nothing after it is not a command.
        assert parse_command("!") is None

    def test_unknown_command_still_parsed(self):
        # Unknown commands reach the parser; the backend decides how to reply.
        result = parse_command("!frobnicate")
        assert result == ParsedCommand("frobnicate", "", False)
        assert result.reserved is False

    def test_reserved_command_flagged(self):
        result = parse_command("!confront")
        assert result == ParsedCommand("confront", "", True)

    def test_reserved_command_with_args(self):
        result = parse_command("!confront the thing")
        assert result == ParsedCommand("confront", "the thing", True)


class TestCommandSurface:
    def test_player_commands_match_spec(self):
        # This must match SPEC.md's command list exactly.
        assert PLAYER_COMMANDS == frozenset(
            {"case", "profile", "room", "investigate", "interview", "force", "ritual"}
        )

    def test_reserved_commands(self):
        assert RESERVED_COMMANDS == frozenset({"confront"})

    def test_player_and_reserved_disjoint(self):
        assert PLAYER_COMMANDS.isdisjoint(RESERVED_COMMANDS)

    def test_all_player_commands_parse(self):
        # Every player command must be parseable and route to itself.
        for name in PLAYER_COMMANDS:
            result = parse_command(f"!{name}")
            assert result is not None
            assert result.name == name
            assert result.reserved is False

    def test_is_known_command(self):
        assert is_known_command("profile")
        assert is_known_command("confront")
        assert not is_known_command("frobnicate")
        assert not is_known_command("")
