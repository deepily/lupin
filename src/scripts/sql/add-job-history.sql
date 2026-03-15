-- =============================================================================
-- CJ Flow Persistence: Job History Table
-- Date: 2026-03-14
-- Purpose: Durable PostgreSQL-backed persistence for agentic job state
-- Database: lupin_db_dev
--
-- Tables:
--   job_history: Tracks lifecycle of AgenticJobBase jobs (deep_research,
--                podcast, claude_code, swe_team, research_to_podcast)
--
-- IMPORTANT: This migration is ADDITIVE only — no ALTER on existing tables.
-- =============================================================================

-- =============================================================================
-- Table: job_history
-- =============================================================================

CREATE TABLE IF NOT EXISTS job_history (
    -- PK is the scoped "{hash}::{user_id}" string from CJ Flow
    id_hash             VARCHAR(255)    PRIMARY KEY,

    -- Job classification
    job_type            VARCHAR(100)    NOT NULL,

    -- User context (VARCHAR, not UUID FK — matches CJ Flow string-based user IDs)
    user_id             VARCHAR(255)    NOT NULL,
    user_email          VARCHAR(255),
    session_id          VARCHAR(255),
    routing_command     VARCHAR(255),

    -- Job state
    status              VARCHAR(50)     NOT NULL DEFAULT 'pending',
    question_text       TEXT,
    error               TEXT,
    is_cache_hit        BOOLEAN         DEFAULT FALSE,
    duration_seconds    FLOAT,

    -- Rich metadata (response_text, abstract, report_link, cost_summary, artifacts)
    metadata_json       JSONB,

    -- Timestamps
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes for job_history
CREATE INDEX IF NOT EXISTS idx_job_history_user_id
    ON job_history ( user_id );

CREATE INDEX IF NOT EXISTS idx_job_history_status
    ON job_history ( status );

CREATE INDEX IF NOT EXISTS idx_job_history_job_type
    ON job_history ( job_type );

CREATE INDEX IF NOT EXISTS idx_job_history_created_at
    ON job_history ( created_at DESC );

CREATE INDEX IF NOT EXISTS idx_job_history_user_status
    ON job_history ( user_id, status );


-- =============================================================================
-- Verification
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'CJ Flow persistence schema migration complete.';
    RAISE NOTICE 'Table created: job_history';

    IF EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_name = 'job_history' ) THEN
        RAISE NOTICE '  ✓ job_history table exists';
    ELSE
        RAISE WARNING '  ✗ job_history table NOT found';
    END IF;
END $$;
