-- =============================================================================
-- Decision Proxy Schema Migration
-- Date: 2026-02-14
-- Purpose: Create tables for the trust-aware decision proxy framework
-- Database: lupin_auth
--
-- Tables:
--   proxy_decisions: Logs every decision classified and acted on (or shadowed)
--   trust_states: Per-user, per-domain, per-category trust snapshots
--
-- IMPORTANT: This migration is ADDITIVE only — no ALTER on existing tables.
-- =============================================================================

-- Enable UUID generation if not already enabled
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- Table: proxy_decisions
-- =============================================================================

CREATE TABLE IF NOT EXISTS proxy_decisions (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Decision context
    notification_id         VARCHAR(255)    NOT NULL,
    domain                  VARCHAR(50)     NOT NULL,
    category                VARCHAR(100)    NOT NULL,
    question                TEXT            NOT NULL,
    sender_id               VARCHAR(255),

    -- Decision outcome
    action                  VARCHAR(50)     NOT NULL,    -- shadow, suggest, act, defer
    decision_value          TEXT,
    confidence              FLOAT,
    trust_level             INTEGER         NOT NULL DEFAULT 1,
    reason                  TEXT,

    -- Ratification
    ratification_state      VARCHAR(50)     NOT NULL DEFAULT 'not_required',
    ratified_by             VARCHAR(255),
    ratified_at             TIMESTAMPTZ,
    ratification_feedback   TEXT,

    -- Extensible metadata
    metadata_json           JSONB,

    -- Data provenance
    data_origin             VARCHAR(50)     NOT NULL DEFAULT 'organic',

    -- Timestamps
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes for proxy_decisions
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_notification_id
    ON proxy_decisions ( notification_id );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_domain
    ON proxy_decisions ( domain );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_category
    ON proxy_decisions ( category );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_action
    ON proxy_decisions ( action );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_sender_id
    ON proxy_decisions ( sender_id );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_ratification
    ON proxy_decisions ( ratification_state );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_created_at
    ON proxy_decisions ( created_at );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_domain_category
    ON proxy_decisions ( domain, category );

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_data_origin
    ON proxy_decisions ( data_origin );


-- =============================================================================
-- Table: trust_states
-- =============================================================================

CREATE TABLE IF NOT EXISTS trust_states (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Trust context
    user_email              VARCHAR(255)    NOT NULL,
    domain                  VARCHAR(50)     NOT NULL,
    category                VARCHAR(100)    NOT NULL,

    -- Trust metrics
    trust_level             INTEGER         NOT NULL DEFAULT 1,
    total_decisions         INTEGER         NOT NULL DEFAULT 0,
    successful_decisions    INTEGER         NOT NULL DEFAULT 0,
    rejected_decisions      INTEGER         NOT NULL DEFAULT 0,

    -- Circuit breaker
    circuit_breaker_state   JSONB,

    -- Timestamps
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes for trust_states
CREATE INDEX IF NOT EXISTS idx_trust_states_user_email
    ON trust_states ( user_email );

CREATE INDEX IF NOT EXISTS idx_trust_states_user_domain
    ON trust_states ( user_email, domain );

CREATE INDEX IF NOT EXISTS idx_trust_states_category
    ON trust_states ( category );

-- Unique composite index — one trust state per user+domain+category
CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_states_user_domain_category
    ON trust_states ( user_email, domain, category );


-- =============================================================================
-- Verification
-- =============================================================================

-- Verify tables were created
DO $$
BEGIN
    RAISE NOTICE 'Decision proxy schema migration complete.';
    RAISE NOTICE 'Tables created: proxy_decisions, trust_states';

    IF EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_name = 'proxy_decisions' ) THEN
        RAISE NOTICE '  ✓ proxy_decisions table exists';
    ELSE
        RAISE WARNING '  ✗ proxy_decisions table NOT found';
    END IF;

    IF EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_name = 'trust_states' ) THEN
        RAISE NOTICE '  ✓ trust_states table exists';
    ELSE
        RAISE WARNING '  ✗ trust_states table NOT found';
    END IF;
END $$;
