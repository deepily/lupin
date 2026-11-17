-- First-start init for the VM's local pgvector container (lupin-pgvector-test, row 8d67e474).
--
-- Mounted at /docker-entrypoint-initdb.d by docker-compose.vm-test-overlay.yml and run once, on an
-- empty data directory, as the superuser lupin_dev connected to lupin_db_dev (POSTGRES_DB).
-- It makes lupin_db_test and puts the extensions in both databases, so the app's non-superuser
-- login never has to create one. It makes no tables: the app's startup migration creates and
-- stamps the schema on its first boot, and `lupin-vm.sh test-server roles` grants after that.
-- Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

SELECT 'CREATE DATABASE lupin_db_test OWNER lupin_dev'
WHERE NOT EXISTS ( SELECT FROM pg_database WHERE datname = 'lupin_db_test' )\gexec

\connect lupin_db_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
