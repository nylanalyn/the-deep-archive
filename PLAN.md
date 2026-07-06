# The Deep Archive - PLAN.md

## Phase 0
Project skeleton, configuration, logging, SQLite.
Seeded injectable RNG for all rolls and generation (so tests are reproducible).

## Phase 1
IRC connectivity and command routing.
pydle with SASL, SSL, `account-notify`, `extended-join`.
Identity resolution: account first, observed nick change second, fresh UUID otherwise.
Minimal admin hook: kill switch + status.

## Phase 2
Database schema (no rooms table) and content shape sketch, together.
Tables:
- players
- nick_map
- active_file (singular)
- file_history
- scars
- relics
- daily_actions
- meta_arc_state

Migrations: numbered `.sql` files, hand-rolled runner.

## Phase 3
Content loader using TOML, built against the Phase 2 shapes.
Themes, stat checks, scar table, relic table, fragment library.

## Phase 4
Automatic player creation and !profile.

## Phase 5
Single active File generation.
Implement:
- !case
- title generation
- atmospheric descriptions (drawn from the fragment library)

Fixed hidden success threshold per File, rolled at creation.

## Phase 6
Core gameplay.
Implement:
- !investigate (luck)
- !interview (Wit)
- !force (Strength)
- !ritual (Occultism)

Daily action limits. Reset at the configured day boundary (global timezone, default UTC).

## Phase 7
Automatic File resolution.
Generate:
- ending narration by tier
- Archive return narration
- relic rewards
- scars
- next File

## Phase 8
Relics and scar modifiers take effect.
Relics store effects as a list; resolution applies them by type. MVP implements one effect type: stat_bonus (tag-matched +1).
Scars apply flat stat deltas to checks.

## Phase 9
Archive flavour.
Expand the fragment library:
- richer Archive descriptions
- weather and mood variants
- personnel titles
- more content tables

## Phase 10
Hidden Meta-Arcs.
- recurring themes
- cross references
- Sealed Files
- !confront
- boss rewards/consequences

## Cross-cutting
Admin API (`discord_admin.py` contract): status, resolve, reload, quiet. Grows with each phase.

Tests for: rolls, case generation, resolution, scar modifiers, relic modifiers, migrations, identity rebinding.

Every phase should remain playable before beginning the next.
