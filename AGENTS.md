# The Deep Archive - AGENTS.md

## Mission

Build a maintainable IRC game, not a complicated framework.

The atmosphere should be mysterious.

The implementation should be straightforward.

## Technology

Preferred:
- Python 3.12+
- SQLite
- TOML
- Type hints
- Small modules

Avoid unnecessary complexity.

## Design Rules

Never increase the public command count without updating SPEC.md.

Player commands:

- !help
- !case
- !profile
- !room
- !investigate
- !interview
- !force
- !ritual

Reserved:
- !confront

No !joincase.
No !assist.

## Narrative Rules

The IRC channel is the Deep Archive.

The bot is the-archivist.

Players always return to the Archive after a File resolves.

Use restrained atmospheric writing.

Prefer subtle horror over constant dramatic narration.

The Archive should slowly develop history through:
- relics
- personnel records
- scars
- completed Files
- meta-arcs

## Engineering Rules

Separate:
- IRC
- game engine
- persistence
- content

Game content should live in TOML files whenever practical.

Store all persistent state in SQLite.

Write tests for:
- rolls
- case generation
- resolution
- scar modifiers
- relic modifiers
- migrations

Implement PLAN.md in order.

Do not build boss fights before the base game is fun.
