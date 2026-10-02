-- Database roles for the approval-settings guard rail (row 80513825, option B).
--
-- WHAT THIS BUYS, AND WHAT IT DOES NOT. A seat shell that stays inside the repo's own
-- tools can no longer write approval policy through a database login: the credentials a
-- seat can read (`.env`) belong to roles that hold no write right on `approval_settings`.
-- It does NOT stop a seat that reaches the database another way (`docker exec` into the
-- postgres container authenticates as the superuser with no password, `sudo`, a container
-- mounting the app's secret). That is step 8 of the plan and is not part of this file.
--
-- ROLES (none is a superuser; `lupin_dev` stays the bootstrap superuser and is untouched here)
--
--   lupin_app   the two app containers. All rights on the app schema in both databases.
--               Its password must live where a seat cannot read it, which is a root-owned
--               file and a host-administration step. Not provisioned by this file's callers
--               until that file exists.
--   lupin_host  host-run processes: the arbiter on :8001, the notification listeners, hooks.
--               Measured 2026-10-02: they connect to Postgres today as the superuser, through
--               the `.env` password. INSERT/UPDATE/DELETE on every app table EXCEPT
--               `approval_settings`, which is read-only to it. A seat can read this role's
--               password, by design, and it cannot change policy with it.
--   lupin_test  seats' sandbox. All rights on `lupin_db_test` and NO right to connect to
--               `lupin_db_dev`.
--
-- RUN AS a superuser connected to `lupin_db_dev`, with the three passwords as psql variables
-- (see src/cosa/utils/db_roles.py, which feeds them on stdin so they never reach argv):
--
--     psql -v ON_ERROR_STOP=1 -f init-db-roles.sql        (variables set by \set lines on stdin)
--
-- Variables: app_pw, host_pw, test_pw (required). reassign=1 (optional, CUTOVER ONLY) hands
-- ownership of every dev-database object from lupin_dev to lupin_app, which the app's own
-- boot-time migrations need once it no longer connects as the superuser.
--
-- IDEMPOTENT: roles are created if absent and their passwords reset each run; grants repeat
-- harmlessly. Not applied to the live database by anyone yet.

\set ON_ERROR_STOP on

-- A forgotten variable must stop the run, not set an empty password.
\if :{?app_pw}
\else
  DO $$ BEGIN RAISE EXCEPTION 'init-db-roles.sql: app_pw is not set'; END $$;
\endif
\if :{?host_pw}
\else
  DO $$ BEGIN RAISE EXCEPTION 'init-db-roles.sql: host_pw is not set'; END $$;
\endif
\if :{?test_pw}
\else
  DO $$ BEGIN RAISE EXCEPTION 'init-db-roles.sql: test_pw is not set'; END $$;
\endif

-- ---- roles -----------------------------------------------------------------------------
SELECT format( 'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', r, p )
  FROM ( VALUES ( 'lupin_app', :'app_pw' ), ( 'lupin_host', :'host_pw' ), ( 'lupin_test', :'test_pw' ) ) AS v( r, p )
 WHERE NOT EXISTS ( SELECT FROM pg_roles WHERE rolname = r )
\gexec

SELECT format( 'ALTER ROLE %I PASSWORD %L', r, p )
  FROM ( VALUES ( 'lupin_app', :'app_pw' ), ( 'lupin_host', :'host_pw' ), ( 'lupin_test', :'test_pw' ) ) AS v( r, p )
\gexec

-- ---- who may connect to which database ---------------------------------------------------
REVOKE CONNECT ON DATABASE lupin_db_dev  FROM PUBLIC;
REVOKE CONNECT ON DATABASE lupin_db_test FROM PUBLIC;
GRANT  CONNECT ON DATABASE lupin_db_dev  TO lupin_app, lupin_host;
GRANT  CONNECT ON DATABASE lupin_db_test TO lupin_app, lupin_test;

-- ---- lupin_db_dev ------------------------------------------------------------------------
\connect lupin_db_dev

GRANT USAGE, CREATE ON SCHEMA public TO lupin_app;
GRANT USAGE         ON SCHEMA public TO lupin_host;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO lupin_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO lupin_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lupin_host;
GRANT USAGE, SELECT, UPDATE          ON ALL SEQUENCES IN SCHEMA public TO lupin_host;

-- The one table the host role may only read. It is looked up by name so an older database
-- without the table (before revision a80513825b01) is not an error.
SELECT 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON approval_settings FROM lupin_host'
 WHERE to_regclass( 'public.approval_settings' ) IS NOT NULL
\gexec

-- Tables the app creates later belong to lupin_app and must come with the same host rights.
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lupin_host;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO lupin_host;

-- ---- CUTOVER ONLY: hand the dev database to the app role --------------------------------
-- NOT `REASSIGN OWNED BY lupin_dev`: that fails ("required by the database system"), because the
-- bootstrap superuser owns catalog objects. Each user object is moved by name instead, and an
-- object an extension owns (the pgvector type and functions in public) is left alone.
\if :{?reassign}
  SELECT format( 'ALTER %s %I.%I OWNER TO lupin_app',
                 CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                                WHEN 'f' THEN 'FOREIGN TABLE' WHEN 'S' THEN 'SEQUENCE' ELSE 'TABLE' END,
                 n.nspname, c.relname )
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_roles o ON o.oid = c.relowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_dev' AND c.relkind IN ( 'r', 'p', 'v', 'm', 'f', 'S' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ( 'e', 'a', 'i' ) )
  \gexec
  SELECT format( 'ALTER TYPE %I.%I OWNER TO lupin_app', n.nspname, t.typname )
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace JOIN pg_roles o ON o.oid = t.typowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_dev' AND t.typtype IN ( 'e', 'd' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e' )
  \gexec
  SELECT format( 'ALTER %s %I.%I( %s ) OWNER TO lupin_app', CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END,
                 n.nspname, p.proname, pg_get_function_identity_arguments( p.oid ) )
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles o ON o.oid = p.proowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_dev' AND p.prokind IN ( 'f', 'p' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e' )
  \gexec
  ALTER SCHEMA public OWNER TO lupin_app;
  SELECT format( 'ALTER DATABASE %I OWNER TO lupin_app', current_database() ) \gexec
\endif

-- ---- lupin_db_test -----------------------------------------------------------------------
\connect lupin_db_test

GRANT USAGE, CREATE ON SCHEMA public TO lupin_app, lupin_test;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO lupin_app, lupin_test;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO lupin_app, lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public GRANT ALL ON TABLES    TO lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_test;
