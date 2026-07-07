-- Live-play pacing: preserve progress while extending short pre-balance Files.

UPDATE active_file
SET success_threshold = 17
WHERE is_sealed = 0 AND success_threshold < 14;

UPDATE active_file
SET success_threshold = 18
WHERE is_sealed = 1 AND success_threshold < 18;
