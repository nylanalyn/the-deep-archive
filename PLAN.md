# The Deep Archive - PLAN.md

## Phase 0
Project skeleton, configuration, logging, SQLite.

## Phase 1
IRC connectivity and command routing.

## Phase 2
Database schema:
- rooms
- players
- active_files
- file_history
- scars
- relics
- daily_actions
- meta_arc_state

## Phase 3
Content loader using TOML.

## Phase 4
Automatic player creation and !profile.

## Phase 5
Single active File generation.

Implement:
- !case
- title generation
- atmospheric descriptions

## Phase 6
Core gameplay

Implement:
- !investigate
- !interview
- !force
- !ritual

Daily action limits.

## Phase 7
Automatic File resolution.

Generate:
- ending narration
- Archive return narration
- relic rewards
- scars
- next File

## Phase 8
Relics and scar modifiers.

## Phase 9
Archive flavour

Expand:
- richer descriptions
- room history
- personnel titles
- more content tables

## Phase 10
Hidden Meta-Arcs

- recurring themes
- cross references
- Sealed Files
- !confront
- boss rewards/consequences

Every phase should remain playable before beginning the next.
