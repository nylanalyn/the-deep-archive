-- Persist the content selections made when an active File is generated.
-- This keeps !case stable across restarts and later content reloads.

ALTER TABLE active_file ADD COLUMN theme_key TEXT NOT NULL DEFAULT '';
ALTER TABLE active_file ADD COLUMN opening_text TEXT NOT NULL DEFAULT 'A file lies open on the reading desk.';
