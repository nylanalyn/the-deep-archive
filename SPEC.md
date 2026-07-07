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
- Rare complications are allowed.

!interview
- Wit check.

!force
- Strength check.

!ritual
- Occultism check.

Each action updates hidden file state.

## Files

Each room always contains exactly one active File.

Hidden values include:
- successes
- failures
- danger
- clue count
- reward table
- scar table

Each File receives a fixed hidden success threshold at creation. It does not change based on room size or player count. If a File resolves quickly, that is fine.

Resolution tiers:

- Disaster
- Failure
- Mixed Failure
- Partial Success
- Success
- Clean Success

Immediately after resolution, a new File is created.

## The Archive

The room is the Deep Archive.

After every completed File, investigators return to the Archive.

The Archivist narrates this return with short atmospheric text describing the library, weather, shelves, lamps, dust, reading rooms, or catalogues.

The Archive itself slowly changes over time.

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

## Shelved Relics

Relics are communal. They belong to the Archive, not to investigators.

Each File carries theme tags (e.g. darkness, flood, geometry). A relic's effects are a list. MVP relics carry one effect: a tag-matched +1 to all checks while a File with a matching tag is active. Later relics may define unique effects without changing the model.

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

Boss victories permanently enrich the Archive.

Boss defeats steal relics, alter scars, and return the world to uneasy normality until another arc awakens.

The reveal should surprise players. The bot never announces that a meta-arc has started.

## Admin Surface

Admin commands are out-of-band. They are not player commands and do not count toward the command surface.

Admin reaches the bot through the shared Discord router. The bot exposes `POST /v1/command` and `GET /v1/events`, matching the contract other bots already use.

Admin can: view internal state, force-resolve a stuck File, reload content, quiet the bot.
