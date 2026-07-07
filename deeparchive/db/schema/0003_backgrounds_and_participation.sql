-- Phase 7 personnel backgrounds and lightweight File participation.

ALTER TABLE players ADD COLUMN background_key TEXT NOT NULL DEFAULT 'unassigned';
ALTER TABLE players ADD COLUMN completed_files INTEGER NOT NULL DEFAULT 0;

CREATE TABLE active_file_participants (
    player_id TEXT PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE
);
