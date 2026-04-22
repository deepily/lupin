-- Initialize the test database (lupin_db_test) for E2E and integration testing.
--
-- Mounted at /docker-entrypoint-initdb.d/03-init-test-db.sql in the postgres
-- container. Runs automatically on FIRST postgres startup (when the data
-- directory is empty). For existing installations, run manually:
--
--   docker exec lupin-postgres psql -U lupin_dev -f /docker-entrypoint-initdb.d/03-init-test-db.sql
--
-- Idempotent: safe to run multiple times.
--
-- Created: 2026-04-12 Session 248e740e (dual-container architecture)

-- Create the test database if it doesn't exist
SELECT 'CREATE DATABASE lupin_db_test OWNER lupin_dev'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lupin_db_test')\gexec

-- Apply the same schema as the dev database
\c lupin_db_test
\i /docker-entrypoint-initdb.d/01-schema.sql
