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

## Extras — upgrade pass (July 2026)

From the post-Phase-10 review. Bug fixes first, then rebalance, then features,
then content. Keep SPEC.md in step where mechanics change; every extra lands
with tests.

### Bug fixes
- [x] E1. Confrontation defeat still writes the pre-rebalance consequence
      scale (`failures = 5`) and resolves as `partial_success` — it can shelve
      a relic and never scars anyone. Defeat must land as `disaster`.
- [x] E2. Scar assignment can hand a player a scar they already carry.
      Exclude owned scars.
- [x] E3. Scar mechanics: TOML is the declared source of truth, but checks
      read the DB's `modifiers_json` snapshot. Read from content by
      `scar_key`; keep the JSON as a historical record.
- [x] E4. `steal_relic` renders names from the key (`Moth Eaten Map`); use the
      content pack's real names.
- [x] E5. `!room` lists every relic forever; cap at the three newest plus a
      count line.
- [x] E6. `reply_delay` pauses before reply index 1 even when the reply is a
      resolution, not an attempt/result beat. Pause only before genuine
      SUCCESS/FAILURE lines.
- [x] E7. Tidy `_reserved_reply` (f-string with no placeholder, unused arg).

### Rebalance
- [x] E8. Natural 1 always fails; natural 6 always succeeds (stat checks and
      confrontation). Kills the auto-success degenerate case at stat 3+.
- [x] E9. Action dispositions: each theme favours one stat action (+1) and
      resists another (−1), telegraphed by an approach-hint line in `!case`.
      Gives the channel something to coordinate about.
- [x] E10. Danger becomes its own dial. Failed actions add danger by action
      (investigate/interview +1, force/ritual +2); a successful `!investigate`
      can steady the File (chance to bleed 1 danger) and rarely complicates
      (danger spike). Resolution tier reads danger alone, not
      `max(failures, danger)`.
- [x] E11. Danger omens: atmospheric warnings when danger crosses 4 and 8; at
      12 the File bites and the acting investigator is scarred mid-File.
- [x] E12. Visible progress: `!case` describes how thick/near-done the File
      feels (band from successes/threshold). Threshold stays hidden.

### Features
- [x] E13. Communal confrontation: one `!confront` per investigator per day;
      the arc resolves when either side reaches two results. No more
      single-die boss.
- [x] E14. The Archive quotes itself: occasional cross-references to closed
      File titles and participant nicks in resolution lines.
- [x] E15. Daily heartbeat: one unprompted line when the day turns
      (allowances reset); `!room` weather is seeded per day so the whole
      channel shares it.

### Content
- [x] E16. Three new themes (dust, mirrors, clocks) with dispositions,
      openings, and meta-arcs.
- [x] E17. Trade-off relics (tag-matched bonus, off-tag penalty) and six new
      scars.
- [x] E18. Fragment expansion across all sections; new sections for omens,
      progress bands, confrontation beats, echoes, and heartbeats.
