-- The Deep Archive - initial schema.
-- Phase 2 tables from PLAN.md. No rooms table: the channel is one canonical
-- Archive; a File's internal location is flavour text on the File itself.

PRAGMA user_version = 0;

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------

CREATE TABLE players (
    id              TEXT PRIMARY KEY,        -- UUID, assigned once
    account         TEXT UNIQUE,             -- NickServ/SASL account, nullable
    display_nick    TEXT NOT NULL,           -- last known nick, for display
    wit             INTEGER NOT NULL DEFAULT 0,
    strength        INTEGER NOT NULL DEFAULT 0,
    occultism       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Maps the raw IRC nick (case-insensitive via COLLATE NOCASE) to the player
-- UUID that owns it. account-notify/extended-join update this; a nick change
-- we observe in-channel moves a row from old nick -> new nick.
CREATE TABLE nick_map (
    nick            TEXT PRIMARY KEY COLLATE NOCASE,
    player_id       TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    observed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Files (active + history)
-- ---------------------------------------------------------------------------

-- Exactly one row is active at a time (enforced by a partial unique index on
-- resolved_at IS NULL below).
CREATE TABLE active_file (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    -- The generation seed lets us replay rolls for diagnostics/tests.
    seed            INTEGER NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT NOT NULL,           -- flavour: the Stacks, etc.
    theme_tags_json TEXT NOT NULL DEFAULT '[]',
    -- Fixed hidden success threshold rolled at creation. Does not scale with
    -- room size or player count.
    success_threshold INTEGER NOT NULL,
    successes       INTEGER NOT NULL DEFAULT 0,
    failures        INTEGER NOT NULL DEFAULT 0,
    danger          INTEGER NOT NULL DEFAULT 0,
    clue_count      INTEGER NOT NULL DEFAULT 0,
    opened_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE file_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    location        TEXT NOT NULL,
    theme_tags_json TEXT NOT NULL DEFAULT '[]',
    success_threshold INTEGER NOT NULL,
    successes       INTEGER NOT NULL,
    failures        INTEGER NOT NULL,
    danger          INTEGER NOT NULL,
    clue_count      INTEGER NOT NULL,
    -- Resolution tier: one of Disaster/Failure/Mixed Failure/
    -- Partial Success/Success/Clean Success.
    resolution_tier TEXT NOT NULL,
    seed            INTEGER NOT NULL,
    opened_at       TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Daily actions
-- ---------------------------------------------------------------------------

CREATE TABLE daily_actions (
    player_id       TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    -- The day key (e.g. '2026-07-06') under which the allowance is counted.
    -- Computed from the configured day-boundary timezone.
    day_key         TEXT NOT NULL,
    actions_used    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, day_key)
);

-- ---------------------------------------------------------------------------
-- Scars (per-investigator permanent trade-offs)
-- ---------------------------------------------------------------------------

CREATE TABLE scars (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    -- Stable scar id from the TOML content tables (e.g. 'paper_bones').
    scar_key        TEXT NOT NULL,
    -- JSON list of {stat, delta}: a bonus, a penalty, or both.
    modifiers_json  TEXT NOT NULL DEFAULT '[]',
    -- Flavour text shown on the profile.
    description     TEXT NOT NULL,
    -- The File that inflicted this scar, for cross-referencing history.
    source_file_id  INTEGER REFERENCES file_history(id) ON DELETE SET NULL,
    acquired_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Relics (communal, shelved in the Archive)
-- ---------------------------------------------------------------------------

CREATE TABLE relics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Stable relic id from the TOML content tables (e.g. 'brass_lantern').
    relic_key       TEXT NOT NULL UNIQUE,
    -- The theme tags this relic responds to (used by MVP stat_bonus effect).
    theme_tags_json TEXT NOT NULL DEFAULT '[]',
    -- JSON list of effects. MVP carries one: {type:'stat_bonus', tags:[...],
    -- amount:1}. Modelled as a list from day one so new effect types are
    -- additive, per SPEC.md's relic forward-compat note.
    effects_json    TEXT NOT NULL DEFAULT '[]',
    description     TEXT NOT NULL,
    -- The File that shelved this relic.
    source_file_id  INTEGER REFERENCES file_history(id) ON DELETE SET NULL,
    shelved_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- Meta-arc state (Phase 10; defined now so the table exists)
-- ---------------------------------------------------------------------------

CREATE TABLE meta_arc_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    -- JSON object holding the hidden counters the meta-arc uses. Empty until
    -- Phase 10 actually activates an arc.
    state_json      TEXT NOT NULL DEFAULT '{}',
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
