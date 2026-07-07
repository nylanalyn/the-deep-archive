"""Command parsing and the command surface.

This module defines what counts as a player command and how raw PRIVMSG text
becomes a ``(command, args)`` pair. It is the single source of truth for the
command surface: the SPEC-mandated player commands, and nothing else.

Per AGENTS.md: never increase the public command count without updating
SPEC.md. The list below must match SPEC.md's "Commands" section exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

# The canonical player command surface. Keep this in lockstep with SPEC.md.
# Context-gated commands (!confront) are not in the ordinary command set.
PLAYER_COMMANDS: frozenset[str] = frozenset(
    {
        "help",
        "case",
        "profile",
        "room",
        "investigate",
        "interview",
        "force",
        "ritual",
    }
)

# Commands recognized outside the ordinary surface. ``!confront`` is routed
# only when a Sealed File exists and otherwise receives a quiet refusal.
RESERVED_COMMANDS: frozenset[str] = frozenset({"confront"})

COMMAND_PREFIX = "!"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """A parsed player command, or ``None`` for non-command messages.

    ``name`` is lowercased. ``args`` is the raw text after the command word,
    stripped of surrounding whitespace (may be empty). The ``reserved`` flag
    distinguishes "recognised but sealed" from "fully implemented".
    """

    name: str
    args: str
    reserved: bool


def parse_command(message: str) -> ParsedCommand | None:
    """Parse a raw IRC message into a :class:`ParsedCommand`.

    Returns ``None`` only when the message is not a command at all (no ``!``
    prefix, or a bare prefix with nothing after it). Unknown command names
    like ``!frobnicate`` DO return a :class:`ParsedCommand` — the backend
    decides how to reply (atmospheric "not recognised" line), not the parser.

    Examples:
        ``!profile``         -> ``ParsedCommand("profile", "", False)``
        ``!profile alice``   -> ``ParsedCommand("profile", "alice", False)``
        ``!PROFILE``         -> ``ParsedCommand("profile", "", False)`` (case-insensitive)
        ``hello``            -> ``None``
        ``!unknown``         -> ``ParsedCommand("unknown", "", False)`` (routed to unknown handler by backend)
        ``!confront``        -> ``ParsedCommand("confront", "", True)`` (reserved)
    """
    message = message.strip()
    if not message.startswith(COMMAND_PREFIX):
        return None

    # Strip the prefix and split into command + remainder. Everything after
    # the command word is preserved verbatim as args, so subcommands and
    # free-text arguments survive intact.
    body = message[len(COMMAND_PREFIX):]
    if not body:
        return None

    # Split only on the first run of whitespace so multi-word args stay whole.
    parts = body.split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    reserved = name in RESERVED_COMMANDS
    return ParsedCommand(name=name, args=args, reserved=reserved)


def is_known_command(name: str) -> bool:
    """True if ``name`` is a recognised command (player or reserved)."""
    return name in PLAYER_COMMANDS or name in RESERVED_COMMANDS
