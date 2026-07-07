-- Sealed File identity on the singleton and its permanent history record.

ALTER TABLE active_file ADD COLUMN is_sealed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE active_file ADD COLUMN arc_key TEXT;
ALTER TABLE file_history ADD COLUMN is_sealed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE file_history ADD COLUMN arc_key TEXT;
