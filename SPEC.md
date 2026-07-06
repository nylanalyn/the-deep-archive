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

## Commands

Player:
- !case
- !profile [nick]
- !room
- !investigate
- !interview
- !force
- !ritual

Reserved for later:
- !confront (boss/meta files only)

No !joincase.
No !assist.

## Stats

Three stats only:

- Wit
- Strength
- Occultism

Players receive five actions per day by default.

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

Files automatically resolve when internal thresholds are reached.

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

## Personnel Files

Player profiles contain:
- stats
- scars
- titles
- action count
- completed investigations

## Scars

Scars are permanent trade-offs.

Examples:
- Scales
- Borrowed Shadow
- Glass Eye
- Paper Bones

Scars should make investigators stranger, not simply weaker.

## Shelved Relics

Successful investigations can reward communal relics.

Examples:
- Brass Lantern
- Choir Register
- Moth-Eaten Map
- Black Cabinet

Relics affect future Files.

## Meta-Arcs

Initially disabled during MVP.

Later:
- Cases quietly begin sharing themes.
- Endings include subtle recurring hints.
- The Archive notices the pattern.
- Hidden counter reaches threshold.
- A Sealed File is revealed.
- Boss confrontation unlocks via !confront.

Boss victories permanently enrich the Archive.

Boss defeats steal relics, alter scars, and return the world to uneasy normality until another arc awakens.

The reveal should surprise players. The bot never announces that a meta-arc has started.
