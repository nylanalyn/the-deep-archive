# The Deep Archive - SPEC.md

## Overview

The Deep Archive is a persistent IRC anomaly-investigation game.

The IRC channel is the Archive itself: an endless dark-academia library of impossible shelves, sealed files, forgotten relics, and quiet lamps. Players are recurring investigators. The bot, **the-archivist**, maintains the Archive, opens new files, records scars, shelves relics, and quietly notices patterns no one else sees.

The bot should feel like a calm librarian documenting impossible events.

## Core Design Principles

- One active case ("File") per room.
- Cases never expire because nobody played.
- The bot speaks mostly when spoken to.
- Small command surface.
- Mechanics are hidden; atmosphere is visible.
- Failure changes the world instead of wasting time.
- Room progression matters as much as player progression.

## Architecture

The bot is standalone. It owns its IRC connection and runs a pure Python game engine with no IRC dependency in the core logic.

Layers, kept separate:
- IRC adapter (thin)
- game engine (pure, testable)
- persistence (SQLite)
- content (TOML)

Admin commands flow through the shared Discord router (`discord_admin.py`) via the same HTTP contract other bots use: `POST /v1/command`, `GET /v1/events`. The router is unchanged.

## The Archive & Files

The channel is the Deep Archive: one canonical room.

A File is an expedition. The Archivist opens a File; investigators act on it; it resolves; they return to the Archive.

A File has an internal location (the Stacks, the Catalogue Hall, a reading room) used for atmosphere only. There is no rooms table.

Each File always exists. When one resolves, the next opens immediately.

## Identity

Each investigator is a UUID.

Account is authoritative. When NickServ or SASL provides an account, the investigator is the account.

When no account is present, identity follows the nick. If the bot observes a nick change in channel, it rebinds the new nick to the same investigator.

Unknown nicks with no account become new investigators.

Accounts recover links the bot missed. Pure-nick users do not.

## Commands

Player:
- !help
- !case
- !profile [nick]
- !room
- !investigate
- !interview
- !force
- !ritual

Sealed Files only:
- !confront

No !joincase.
No !assist.

`!help` gives a two-line summary of the game loop and command surface.

## Stats

Three stats only:

- Wit
- Strength
- Occultism

Players receive five actions per day by default.

The day boundary is a single configurable timezone for the whole bot. Default is UTC.

## Actions

!investigate
- Luck based.
- Roughly 50/50 chance to discover something useful.
- The scout's action: a success can steady the File (bleed off accumulated
  danger); a rare complication (5%) agitates it instead.

!interview
- Wit check.

!force
- Strength check.

!ritual
- Occultism check.

Stat checks are d6 + effective stat against a fixed target. A natural 1
always fails and a natural 6 always succeeds — no stack of relics makes an
investigator infallible, and no stat spread leaves one hopeless.

Each theme favours one stat action (+1) and resists another (−1). The
disposition also softens or sharpens the danger of failing that action. The
File telegraphs its dispositions through an approach-hint line in !case; the
channel is expected to read it and coordinate.

Failure feeds the File's hidden danger: interview +1, force and ritual +2
(±1 by disposition). Danger crossing hidden thresholds produces omens in the
channel; at the highest threshold the File bites, scarring the acting
investigator mid-File.

Each action updates hidden file state.

Actions are narrated in two beats: a short generated description of the
attempt, followed by an explicit SUCCESS or FAILURE result. Individual checks
remain binary; the six broader outcome tiers apply when the whole File closes.

## Files

Each room always contains exactly one active File.

Hidden values include:
- successes
- failures
- danger
- clue count
- reward table
- scar table

Each File receives a fixed hidden success threshold at creation. It does not
change based on room size or player count. Thresholds are tuned so a few active
investigators will usually carry a File across more than one daily allowance,
though exceptional luck can still close one sooner.

Resolution tiers:

- Disaster
- Failure
- Mixed Failure
- Partial Success
- Success
- Clean Success

The tier is decided by accumulated danger relative to the File's length.
Failures are recorded in history but do not directly set the tier — what the
Archive remembers is how agitated the File became.

!case never shows numbers, but it does describe how far along the File feels
(a progress band derived from successes against the hidden threshold) and
carries the theme's approach hint.

Immediately after resolution, a new File is created. Resolution lines
occasionally cross-reference older closed Files by title, and good closes
occasionally credit an investigator by nick — the Archive quotes itself.

## The Archive

The room is the Deep Archive.

After every completed File, investigators return to the Archive.

The Archivist narrates this return with short atmospheric text describing the library, weather, shelves, lamps, dust, reading rooms, or catalogues.

The Archive itself slowly changes over time.

The weather is seeded per day: everyone who asks sees the same sky until the
day turns. When the day does turn (and action allowances reset), the
Archivist speaks exactly one unprompted line — the only time the bot speaks
without being spoken to.

## Atmosphere & Voice

The Archivist speaks like a calm librarian documenting impossible events.

Prose comes from a hand-authored library of short fragments, organized by context: Archive returns, File openings, resolution tiers, room weather. The engine composes; it does not generate.

Prefer short lines. Prefer silence over filler. Let gaps do work.

## Personnel Files

Player profiles contain:
- stats
- scars
- titles
- action count
- completed investigations

Profiles show atmospheric information (titles, scars, relic ties) more than raw numbers, especially for other investigators' profiles.

## Scars

Scars are permanent trade-offs.

Each scar is a set of stat modifiers: a bonus, a penalty, or both.

Examples:
- Scales
- Borrowed Shadow
- Glass Eye
- Paper Bones

Scars make investigators stranger, not simply weaker.

An investigator never receives the same scar twice. Scar mechanics live in
content (TOML) as the single source of truth; the database keeps a snapshot
only as a historical record.

## Shelved Relics

Relics are communal. They belong to the Archive, not to investigators.

Each File carries theme tags (e.g. darkness, flood, geometry). A relic's effects are a list. The base effect is a tag-matched +1 to all stat checks while a File with a matching tag is active. An effect may declare its own tags and a negative amount, so some relics help one kind of File and hinder another — the shelf's composition matters. Later relics may define unique effects without changing the model.

Successful investigations can shelve new relics. Relics affect future Files.

Examples of relics:
- Brass Lantern
- Choir Register
- Moth-Eaten Map
- Black Cabinet

## Meta-Arcs

Meta-arcs remain hidden until their pattern becomes visible:
- Files quietly share recurring themes.
- Endings include subtle cross-references.
- A hidden counter reaches its threshold.
- A Sealed File is revealed.
- Investigators gather evidence through normal actions.
- The final confrontation unlocks via !confront.

The confrontation is communal: each investigator may face the Sealed File
once per day (spending an action), and the arc resolves when either side
reaches two results. A defeat lands as a full Disaster.

Boss victories permanently enrich the Archive.

Boss defeats steal relics, alter scars, and return the world to uneasy normality until another arc awakens.

The reveal should surprise players. The bot never announces that a meta-arc has started.

## Admin Surface

Admin commands are out-of-band. They are not player commands and do not count toward the command surface.

Admin reaches the bot through the shared Discord router. The bot exposes `POST /v1/command` and `GET /v1/events`, matching the contract other bots already use.

Admin can: view internal state, force-resolve a stuck File, reload content, quiet the bot.
