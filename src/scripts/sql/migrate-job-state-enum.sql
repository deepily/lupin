-- CJ Flow: Unified Job State Machine — PostgreSQL Migration
--
-- Adds CHECK constraint on status column to enforce valid JobState values.
-- No data migration needed: existing values (pending, running, completed,
-- failed, interrupted) are all valid in the new enum.
--
-- New values added: queued, scheduled, paused, cancelled
-- The status column remains VARCHAR(50) — no Postgres enum type.
--
-- Date: 2026-03-30
-- Ref: src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine.md

BEGIN;

-- Step 1: Add CHECK constraint for valid JobState values
ALTER TABLE job_history
    ADD CONSTRAINT chk_job_state_valid
    CHECK ( status IN (
        'pending', 'queued', 'scheduled', 'paused',
        'running',
        'completed', 'failed', 'interrupted', 'cancelled'
    ) );

-- Step 2: Verify constraint was applied
DO $$
DECLARE
    constraint_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.check_constraints
        WHERE constraint_name = 'chk_job_state_valid'
    ) INTO constraint_exists;

    IF constraint_exists THEN
        RAISE NOTICE 'Migration successful: chk_job_state_valid constraint added';
    ELSE
        RAISE EXCEPTION 'Migration failed: constraint not found after ALTER TABLE';
    END IF;
END $$;

COMMIT;
