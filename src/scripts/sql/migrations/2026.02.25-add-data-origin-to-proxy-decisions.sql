-- =============================================================================
-- Migration: Add data_origin column to proxy_decisions
-- Date: 2026-02-25
-- Purpose: Track provenance of proxy decisions (organic vs synthetic)
--
-- Values:
--   organic             — Real production decisions (default)
--   synthetic_seed      — Initial bootstrap seed data (Session 265)
--   synthetic_generated — Workload generator output
-- =============================================================================

-- Add column (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'proxy_decisions' AND column_name = 'data_origin'
    ) THEN
        ALTER TABLE proxy_decisions
            ADD COLUMN data_origin VARCHAR(50) NOT NULL DEFAULT 'organic';

        CREATE INDEX IF NOT EXISTS idx_proxy_decisions_data_origin
            ON proxy_decisions ( data_origin );

        RAISE NOTICE '✓ Added data_origin column to proxy_decisions';
    ELSE
        RAISE NOTICE '✓ data_origin column already exists — skipping';
    END IF;
END $$;

-- Backfill existing seed data (Session 265 seeded 50 rows with metadata_json.seed_data = true)
UPDATE proxy_decisions
SET    data_origin = 'synthetic_seed'
WHERE  metadata_json->>'seed_data' = 'true'
  AND  data_origin = 'organic';

DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✓ Backfilled % rows with data_origin = synthetic_seed', updated_count;
END $$;

-- Verification
DO $$
DECLARE
    organic_count   INTEGER;
    seed_count      INTEGER;
    generated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO organic_count   FROM proxy_decisions WHERE data_origin = 'organic';
    SELECT COUNT(*) INTO seed_count      FROM proxy_decisions WHERE data_origin = 'synthetic_seed';
    SELECT COUNT(*) INTO generated_count FROM proxy_decisions WHERE data_origin = 'synthetic_generated';

    RAISE NOTICE 'proxy_decisions data_origin distribution:';
    RAISE NOTICE '  organic:             %', organic_count;
    RAISE NOTICE '  synthetic_seed:      %', seed_count;
    RAISE NOTICE '  synthetic_generated: %', generated_count;
END $$;
