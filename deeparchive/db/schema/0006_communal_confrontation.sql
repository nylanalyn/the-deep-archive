-- Extras E13: communal confrontation. The Sealed File is decided by the
-- first side to reach two confrontation results, one attempt per
-- investigator per day, instead of a single roll.

ALTER TABLE active_file ADD COLUMN confront_successes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE active_file ADD COLUMN confront_failures INTEGER NOT NULL DEFAULT 0;

-- One row per confrontation attempt. day_key mirrors daily_actions so the
-- once-per-day gate shares the configured day boundary.
CREATE TABLE active_file_confronts (
    player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    day_key   TEXT NOT NULL,
    PRIMARY KEY (player_id, day_key)
);
