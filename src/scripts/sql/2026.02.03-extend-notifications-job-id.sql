-- Migration: Extend job_id column to accommodate compound IDs
-- Format: {SHA256_hash}::{UUID} = 64 + 2 + 36 = 102+ characters
-- Date: 2026-02-03

ALTER TABLE notifications
    ALTER COLUMN job_id TYPE VARCHAR(256);

-- Verify change
SELECT column_name, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'notifications' AND column_name = 'job_id';
