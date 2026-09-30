"""
Unit tests for cosa.rest.db.auto_migrate — the programmatic startup
auto-migrator (alembic upgrade head without an alembic.ini dependency).

Two layers:
    - Mocked unit tests (always run): drive every line/branch/function of
      auto_migrate to 100% coverage with NO real database. Alembic command,
      create_engine, and the DB-state probe are patched.
    - Live integration tests (skipped if local Postgres is unreachable): create
      throwaway databases on localhost:5432, run the REAL alembic chain through
      env.py, and prove the four DB-state scenarios end-to-end.

The live tests are bonus proof; coverage is satisfied entirely by the mocked
layer so the file is CI-safe with or without Postgres.
"""

import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from cosa.rest.db import auto_migrate


# ---------------------------------------------------------------------------
# Mocked unit tests — 100% coverage, no real DB
# ---------------------------------------------------------------------------
class TestResolveDatabaseUrl( unittest.TestCase ):

    def test_explicit_argument_wins( self ):
        self.assertEqual( auto_migrate.resolve_database_url( "postgresql://explicit" ), "postgresql://explicit" )

    def test_database_url_env_used_when_no_arg( self ):
        with patch.dict( os.environ, { "DATABASE_URL": "postgresql://from-env" }, clear=True ):
            self.assertEqual( auto_migrate.resolve_database_url(), "postgresql://from-env" )

    def test_falls_back_to_app_builder( self ):
        with patch.dict( os.environ, {}, clear=True ):
            with patch( "cosa.rest.db.database.get_database_url", return_value="postgresql://from-builder" ) as gdu:
                self.assertEqual( auto_migrate.resolve_database_url(), "postgresql://from-builder" )
                gdu.assert_called_once()


class TestBuildAlembicConfig( unittest.TestCase ):

    def test_sets_script_location( self ):
        config = auto_migrate.build_alembic_config()
        self.assertTrue( config.get_main_option( "script_location" ).endswith( os.path.join( "src", "migrations" ) ) )

    def test_no_url_means_no_injected_attribute( self ):
        config = auto_migrate.build_alembic_config()
        self.assertNotIn( "injected_db_url", config.attributes )

    def test_url_is_injected_as_attribute( self ):
        config = auto_migrate.build_alembic_config( database_url="postgresql://inject" )
        self.assertEqual( config.attributes[ "injected_db_url" ], "postgresql://inject" )


class TestInspectDbState( unittest.TestCase ):

    def _patch_inspector( self, table_names ):
        fake_inspector = MagicMock()
        fake_inspector.get_table_names.return_value = table_names
        fake_engine = MagicMock()
        return fake_engine, fake_inspector

    def test_both_present( self ):
        engine, inspector = self._patch_inspector( [ "users", "alembic_version", "notifications" ] )
        with patch( "cosa.rest.db.auto_migrate.create_engine", return_value=engine ), \
             patch( "cosa.rest.db.auto_migrate.inspect", return_value=inspector ):
            has_version, has_app = auto_migrate._inspect_db_state( "postgresql://x" )
        self.assertTrue( has_version )
        self.assertTrue( has_app )
        engine.dispose.assert_called_once()

    def test_neither_present( self ):
        engine, inspector = self._patch_inspector( [] )
        with patch( "cosa.rest.db.auto_migrate.create_engine", return_value=engine ), \
             patch( "cosa.rest.db.auto_migrate.inspect", return_value=inspector ):
            has_version, has_app = auto_migrate._inspect_db_state( "postgresql://x" )
        self.assertFalse( has_version )
        self.assertFalse( has_app )
        engine.dispose.assert_called_once()


class TestRunMigrationsToHead( unittest.TestCase ):
    """Each DB-state branch, with both debug arms covered."""

    URL = "postgresql://test"

    def test_empty_db_bootstraps_and_stamps_debug_true( self ):
        engine = MagicMock()
        fake_base = MagicMock()
        with patch( "cosa.rest.db.auto_migrate._inspect_db_state", return_value=( False, False ) ), \
             patch( "cosa.rest.db.auto_migrate.create_engine", return_value=engine ) as ce, \
             patch( "cosa.rest.postgres_models.Base", fake_base ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            auto_migrate.run_migrations_to_head( database_url=self.URL, debug=True )
        fake_base.metadata.create_all.assert_called_once_with( engine )
        # EVERY engine opened is disposed. This was `assert_called_once`, which
        # read as "exactly one engine exists" — true only incidentally. Row
        # 0aae1a28 added the before/after revision reads that make the migration
        # announcement possible, and each opens its own engine; `create_engine` is
        # patched module-wide so all of them are this one mock. Asserting the
        # PAIRING is the invariant that was meant; asserting the COUNT was an
        # accident of there having been one.
        self.assertEqual( engine.dispose.call_count, ce.call_count )
        self.assertGreaterEqual( ce.call_count, 1 )
        cmd.stamp.assert_called_once()
        cmd.upgrade.assert_not_called()
        # v0.2.0 pgvector: the `vector` extension is created before create_all.
        conn = engine.begin.return_value.__enter__.return_value
        conn.execute.assert_called_once()
        self.assertIn( "CREATE EXTENSION", str( conn.execute.call_args[ 0 ][ 0 ] ) )

    def test_empty_db_bootstraps_debug_false( self ):
        engine = MagicMock()
        fake_base = MagicMock()
        with patch( "cosa.rest.db.auto_migrate._inspect_db_state", return_value=( False, False ) ), \
             patch( "cosa.rest.db.auto_migrate.create_engine", return_value=engine ), \
             patch( "cosa.rest.postgres_models.Base", fake_base ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            auto_migrate.run_migrations_to_head( database_url=self.URL, debug=False )
        cmd.stamp.assert_called_once()

    def test_legacy_unstamped_raises_runtimeerror( self ):
        with patch( "cosa.rest.db.auto_migrate._inspect_db_state", return_value=( False, True ) ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            with self.assertRaises( RuntimeError ):
                auto_migrate.run_migrations_to_head( database_url=self.URL )
        cmd.upgrade.assert_not_called()
        cmd.stamp.assert_not_called()

    def test_normal_db_upgrades_debug_true( self ):
        with patch( "cosa.rest.db.auto_migrate._inspect_db_state", return_value=( True, True ) ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            auto_migrate.run_migrations_to_head( database_url=self.URL, debug=True )
        cmd.upgrade.assert_called_once()
        self.assertEqual( cmd.upgrade.call_args[ 0 ][ 1 ], "head" )

    def test_normal_db_upgrades_debug_false( self ):
        with patch( "cosa.rest.db.auto_migrate._inspect_db_state", return_value=( True, False ) ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            auto_migrate.run_migrations_to_head( database_url=self.URL, debug=False )
        cmd.upgrade.assert_called_once()


# ---------------------------------------------------------------------------
# Live integration tests — real throwaway DB (skipped if Postgres unreachable)
# ---------------------------------------------------------------------------
# The password is read from the ENVIRONMENT, never hardcoded (row baac2474). It used to be a
# literal, and that same literal configured the live container while sitting in a PUBLIC repo.
#
# ⚠️ A PLACEHOLDER HERE WOULD BE A MASK, NOT A SCRUB. These are real connections: a fake value
# makes _pg_reachable() fail and turns every live test below into a PERMANENT SKIP that reads
# like "Postgres is down". Unset DB_PASSWORD and they skip honestly; set it and they run.
_PG = dict( host="localhost", port=5432, user="lupin_dev",
            password=os.environ.get( "DB_PASSWORD", "" ) )


def _pg_reachable():
    try:
        import psycopg2
        conn = psycopg2.connect( dbname="lupin_db_dev", connect_timeout=2, **_PG )
        conn.close()
        return True
    except Exception:
        return False


def _pgvector_available():
    """
    True iff the reachable Postgres advertises the `vector` extension.

    Since v0.2.0 the app schema (Base.metadata) includes the pgvector vector-store
    tables, so the empty-DB bootstrap these live tests exercise now creates a
    `vector` column and therefore requires pgvector. On the stock
    postgres:16.3-alpine image the extension is absent; these tests skip until the
    docker-compose image swap → pgvector/pgvector:pg16 lands (shared-infra,
    operator-applied). NOT a mask — the precondition genuinely expanded.
    """
    try:
        import psycopg2
        conn = psycopg2.connect( dbname="lupin_db_dev", connect_timeout=2, **_PG )
        try:
            with conn.cursor() as cur:
                cur.execute( "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" )
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


def _resolve_alembic_head():
    """Return the CURRENT single alembic head from the on-disk migration scripts.

    Ensures:
        - resolved from the ScriptDirectory (no DB connection), so the head
          assertions below track the live chain instead of a pinned constant
          that goes stale the moment a new migration lands. This file was
          pinned to "d4e5f6a7b8c9" (then-head); six later migrations advanced
          the chain, silently breaking these live tests the whole time they
          were skip-gated. Dynamic resolution is the durable fix (cf. the same
          stale-hardcoded-head drift addressed in task ad2e40bc).
    """
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config( auto_migrate.build_alembic_config() ).get_current_head()


@unittest.skipUnless(
    _pg_reachable() and _pgvector_available(),
    "local Postgres not reachable OR lacks pgvector (GATED on image swap → "
    "pgvector/pgvector:pg16; v0.2.0 app schema now includes vector tables)",
)
class TestAutoMigrateLive( unittest.TestCase ):
    """Real alembic chain against throwaway DBs — created and dropped per test."""

    # HEAD tracks the live chain (see _resolve_alembic_head) — never pinned.
    HEAD = _resolve_alembic_head()
    # PREV is a FIXED historical anchor: the parent of the is_protected migration
    # (d4e5f6a7b8c9). The cloud/dev scenarios exercise THAT migration
    # specifically, so PREV is tied to it, not to the moving head.
    PREV = "c3d4e5f6a7b8"

    def setUp( self ):
        import psycopg2
        self.dbname = "lupin_am_ut_" + uuid.uuid4().hex[ :12 ]
        self._admin = psycopg2.connect( dbname="lupin_db_dev", **_PG )
        self._admin.autocommit = True
        from psycopg2 import sql
        self._sql = sql
        with self._admin.cursor() as cur:
            cur.execute( sql.SQL( "CREATE DATABASE {}" ).format( sql.Identifier( self.dbname ) ) )
        self.url = f"postgresql+psycopg2://lupin_dev:{_PG[ 'password' ]}@localhost:5432/{self.dbname}"

    def tearDown( self ):
        with self._admin.cursor() as cur:
            cur.execute(
                self._sql.SQL( "DROP DATABASE IF EXISTS {} WITH ( FORCE )" ).format( self._sql.Identifier( self.dbname ) )
            )
        self._admin.close()

    def _query( self, sqlstr ):
        import psycopg2
        conn = psycopg2.connect( dbname=self.dbname, **_PG )
        try:
            with conn.cursor() as cur:
                cur.execute( sqlstr )
                return cur.fetchall()
        finally:
            conn.close()

    def _has_is_protected( self ):
        return bool( self._query(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='is_protected'"
        ) )

    def _head( self ):
        return self._query( "SELECT version_num FROM alembic_version" )

    def _exec( self, sqlstr ):
        import psycopg2
        conn = psycopg2.connect( dbname=self.dbname, **_PG )
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute( sqlstr )
        finally:
            conn.close()

    def test_empty_db_reaches_head_with_is_protected( self ):
        auto_migrate.run_migrations_to_head( database_url=self.url )
        self.assertTrue( self._has_is_protected() )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )
        # Idempotent: second run is a no-op (still at head, no error).
        auto_migrate.run_migrations_to_head( database_url=self.url )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )

    def test_cloud_scenario_missing_column_gets_added( self ):
        # Cloud-shaped DB: the full app schema exists UP TO the is_protected
        # migration's parent — built via the REAL chain so every prior table
        # physically exists (a bare hand-created `users` + stamp would fake
        # "prior applied" and crash later migrations on missing FK targets like
        # `notifications`). is_protected is still ABSENT here; the auto-migrator
        # must run the remaining chain to head and ADD it end-to-end.
        from alembic import command
        command.upgrade( auto_migrate.build_alembic_config( database_url=self.url ), self.PREV )
        self.assertFalse( self._has_is_protected() )                   # not added yet
        auto_migrate.run_migrations_to_head( database_url=self.url )
        self.assertTrue( self._has_is_protected() )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )

    def test_dev_scenario_existing_column_no_crash( self ):
        # Dev-shaped DB: full app schema up to the is_protected parent (real
        # chain), then is_protected added OUT-OF-BAND while still stamped one
        # revision behind its migration. Upgrading to head must run the
        # inspector-guarded is_protected migration IDEMPOTENTLY — no
        # DuplicateColumn.
        from alembic import command
        command.upgrade( auto_migrate.build_alembic_config( database_url=self.url ), self.PREV )
        self._exec( "ALTER TABLE users ADD COLUMN is_protected boolean NOT NULL DEFAULT false" )
        auto_migrate.run_migrations_to_head( database_url=self.url )   # must not raise
        self.assertTrue( self._has_is_protected() )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )

    def test_legacy_unstamped_schema_refused( self ):
        self._exec( "CREATE TABLE users ( id uuid PRIMARY KEY DEFAULT gen_random_uuid() )" )
        with self.assertRaises( RuntimeError ):
            auto_migrate.run_migrations_to_head( database_url=self.url )

    def test_envpy_resolves_url_via_app_builder_without_database_url( self ):
        # Task (a): with NO DATABASE_URL and NO injected url, env.py must fall
        # through to cosa.rest.db.database.get_database_url() — the app builder —
        # to find the right database. We point the builder at this throwaway DB
        # via DB_NAME (development branch: localhost:5432, lupin_dev/$DB_PASSWORD).
        from alembic import command

        # First bring the DB to head normally (empty -> create_all + stamp head).
        auto_migrate.run_migrations_to_head( database_url=self.url )

        env = {
            "DB_NAME"     : self.dbname,
            "DB_HOST"     : "localhost",
            "DB_PORT"     : "5432",
            "DB_USER"     : "lupin_dev",
            "DB_PASSWORD" : _PG[ "password" ],
        }
        # build_alembic_config(database_url=None) => NO injected_db_url attribute,
        # so env.py's OWN resolution (DATABASE_URL -> injected -> builder) runs.
        # If env.py resolved the URL incorrectly it would connect to the wrong /
        # nonexistent DB and raise; an idempotent no-op upgrade here proves it
        # resolved to THIS throwaway DB purely via get_database_url().
        config = auto_migrate.build_alembic_config()
        with patch.dict( os.environ, env, clear=False ):
            os.environ.pop( "DATABASE_URL", None )
            os.environ.pop( "LUPIN_ENV", None )           # -> development branch
            os.environ.pop( "LUPIN_CLOUD_BACKED", None )  # -> local (not cloudsql)
            command.upgrade( config, "head" )             # no-op via builder-resolved URL
        self.assertTrue( self._has_is_protected() )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )


if __name__ == "__main__":
    unittest.main()
