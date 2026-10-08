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
-- rollback=1 (optional, CUTOVER ONLY, never with reassign) is the reassign in reverse: every object
-- in public that lupin_app owns goes back to lupin_dev (the schema itself to pg_database_owner), and nothing else is run. No password
-- variable is needed. It does not create, alter or drop a role, reset a password, or grant or
-- revoke anything; the roles and their grants stay as they were.
--
-- grants_only=1 (optional, never with reassign) runs the grants, the REVOKE and the default privileges
-- and nothing else. It needs no password variable and creates, alters and drops no role, so it needs
-- no password file and no root. It stops with a named error when one of the three roles is missing.
--
-- IDEMPOTENT: roles are created if absent and their passwords reset each run; grants repeat
-- harmlessly. Not applied to the live database by anyone yet.

\set ON_ERROR_STOP on

-- Keep the passwords out of the server log. Under log_statement='ddl' the CREATE ROLE / ALTER ROLE
-- statements built below are logged WITH the clear password, and a failing one is logged again under
-- log_min_error_statement. These settings are per session, so they are repeated after every \connect.
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;

-- ---- ROLLBACK ONLY: hand the dev database back to the bootstrap superuser ---------------
-- The reassign block below in reverse, with the same extension exclusions and the two role names
-- swapped. It runs before everything else and ends the session, so no role, password or grant
-- statement further down is reached. A test pins that the object statements differ by the role
-- names only, and pins the two closing statements, which differ on purpose (see below).
\if :{?rollback}
  \connect lupin_db_dev
  SET log_statement = 'none';
  SET log_min_error_statement = 'panic';
  SET log_min_duration_statement = -1;
  SELECT format( 'ALTER %s %I.%I OWNER TO lupin_dev',
                 CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                                WHEN 'f' THEN 'FOREIGN TABLE' WHEN 'S' THEN 'SEQUENCE' ELSE 'TABLE' END,
                 n.nspname, c.relname )
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_roles o ON o.oid = c.relowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_app' AND c.relkind IN ( 'r', 'p', 'v', 'm', 'f', 'S' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ( 'e', 'a', 'i' ) )
  \gexec
  SELECT format( 'ALTER TYPE %I.%I OWNER TO lupin_dev', n.nspname, t.typname )
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace JOIN pg_roles o ON o.oid = t.typowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_app' AND t.typtype IN ( 'e', 'd' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e' )
  \gexec
  SELECT format( 'ALTER %s %I.%I( %s ) OWNER TO lupin_dev', CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END,
                 n.nspname, p.proname, pg_get_function_identity_arguments( p.oid ) )
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles o ON o.oid = p.proowner
   WHERE n.nspname = 'public' AND o.rolname = 'lupin_app' AND p.prokind IN ( 'f', 'p' )
     AND NOT EXISTS ( SELECT FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e' )
  \gexec
  -- The schema and the database are moved back only when lupin_app owns them now. The live public
  -- schema is owned by pg_database_owner (Mr. Radio, measured in both databases), so that is where
  -- it returns; the database returns to lupin_dev. A rollback with no prior reassign changes neither.
  SELECT 'ALTER SCHEMA public OWNER TO pg_database_owner'
   WHERE EXISTS ( SELECT FROM pg_namespace n JOIN pg_roles o ON o.oid = n.nspowner WHERE n.nspname = 'public' AND o.rolname = 'lupin_app' )
  \gexec
  SELECT format( 'ALTER DATABASE %I OWNER TO lupin_dev', current_database() )
   WHERE EXISTS ( SELECT FROM pg_database d JOIN pg_roles o ON o.oid = d.datdba WHERE d.datname = current_database() AND o.rolname = 'lupin_app' )
  \gexec
  \quit
\endif

\if :{?grants_only}
\else
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
\endif

-- ---- precheck: both databases must exist before anything is applied ---------------------
-- Without this, a missing lupin_db_test fails at the second \connect, after the dev half is applied.
SELECT EXISTS ( SELECT FROM pg_database WHERE datname = 'lupin_db_test' ) AS has_test_db \gset
\if :has_test_db
\else
  DO $$ BEGIN RAISE EXCEPTION 'init-db-roles.sql: database lupin_db_test does not exist'; END $$;
\endif

\if :{?grants_only}
  SELECT count(*) > 0 AS any, coalesce( string_agg( r, ', ' ORDER BY r ), '' ) AS names
    FROM ( VALUES ( 'lupin_app' ), ( 'lupin_host' ), ( 'lupin_test' ) ) AS v( r )
   WHERE NOT EXISTS ( SELECT FROM pg_roles WHERE rolname = r )
  \gset missing_
  \if :missing_any
    \echo init-db-roles.sql: missing roles :missing_names
    DO $$ BEGIN RAISE EXCEPTION 'init-db-roles.sql: a role is missing, and grants_only does not create roles'; END $$;
  \endif
\else
-- ---- roles -----------------------------------------------------------------------------
SELECT format( 'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', r, p )
  FROM ( VALUES ( 'lupin_app', :'app_pw' ), ( 'lupin_host', :'host_pw' ), ( 'lupin_test', :'test_pw' ) ) AS v( r, p )
 WHERE NOT EXISTS ( SELECT FROM pg_roles WHERE rolname = r )
\gexec

SELECT format( 'ALTER ROLE %I PASSWORD %L', r, p )
  FROM ( VALUES ( 'lupin_app', :'app_pw' ), ( 'lupin_host', :'host_pw' ), ( 'lupin_test', :'test_pw' ) ) AS v( r, p )
\gexec

-- lupin_test may create databases: the integration tier logs in as lupin_test and its files run
-- CREATE DATABASE for a throwaway database. lupin_app and lupin_host keep NOCREATEDB. This is an
-- ALTER, not part of the CREATE ROLE above, so a role that already exists gets it on a re-apply.
ALTER ROLE lupin_test CREATEDB;
\endif

-- ---- who may connect to which database ---------------------------------------------------
REVOKE CONNECT ON DATABASE lupin_db_dev  FROM PUBLIC;
REVOKE CONNECT ON DATABASE lupin_db_test FROM PUBLIC;
GRANT  CONNECT ON DATABASE lupin_db_dev  TO lupin_app, lupin_host;
GRANT  CONNECT ON DATABASE lupin_db_test TO lupin_app, lupin_test;

-- ---- lupin_db_dev ------------------------------------------------------------------------
\connect lupin_db_dev
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;

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

-- RE-RUN THIS FILE AFTER MIGRATIONS that create tables: a table created before the role existed has
-- no default grants, and revision b80513825c02 repeats the approval_settings REVOKE on the migration path.
-- Ordering: run before --reassign; tables still owned by lupin_dev do not get the lupin_host default grants.
-- Tables the app creates later belong to lupin_app and must come with the same host rights.
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lupin_host;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO lupin_host;
-- A table is owned by the login that ran the migration: lupin_dev today, lupin_test for the integration tier,
-- lupin_app after the cutover (measured on a throwaway server, all 27 tables each time). So every creator
-- carries the grants. lupin_test cannot connect to this database; its lines are here so the three creators match.
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev IN SCHEMA public GRANT ALL ON TABLES    TO lupin_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lupin_host;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev IN SCHEMA public GRANT USAGE, SELECT, UPDATE          ON SEQUENCES TO lupin_host;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT ALL ON TABLES    TO lupin_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lupin_host;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT USAGE, SELECT, UPDATE          ON SEQUENCES TO lupin_host;

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
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;

GRANT USAGE, CREATE ON SCHEMA public TO lupin_app, lupin_test;
GRANT ALL ON ALL TABLES    IN SCHEMA public TO lupin_app, lupin_test;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO lupin_app, lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public GRANT ALL ON TABLES    TO lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev  IN SCHEMA public GRANT ALL ON TABLES    TO lupin_app, lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_dev  IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_app, lupin_test;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT ALL ON TABLES    TO lupin_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lupin_test IN SCHEMA public GRANT ALL ON SEQUENCES TO lupin_app;
