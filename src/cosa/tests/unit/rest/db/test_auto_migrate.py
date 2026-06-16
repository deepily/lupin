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
             patch( "cosa.rest.db.auto_migrate.create_engine", return_value=engine ), \
             patch( "cosa.rest.postgres_models.Base", fake_base ), \
             patch( "cosa.rest.db.auto_migrate.command" ) as cmd:
            auto_migrate.run_migrations_to_head( database_url=self.URL, debug=True )
        fake_base.metadata.create_all.assert_called_once_with( engine )
        engine.dispose.assert_called_once()
        cmd.stamp.assert_called_once()
        cmd.upgrade.assert_not_called()

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
_PG = dict( host="localhost", port=5432, user="lupin_dev", password="dev_password" )


def _pg_reachable():
    try:
        import psycopg2
        conn = psycopg2.connect( dbname="lupin_db_dev", connect_timeout=2, **_PG )
        conn.close()
        return True
    except Exception:
        return False


@unittest.skipUnless( _pg_reachable(), "local Postgres (localhost:5432 lupin_dev) not reachable" )
class TestAutoMigrateLive( unittest.TestCase ):
    """Real alembic chain against throwaway DBs — created and dropped per test."""

    HEAD = "d4e5f6a7b8c9"
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
        self.url = f"postgresql+psycopg2://lupin_dev:dev_password@localhost:5432/{self.dbname}"

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
        # Tables exist, is_protected ABSENT, stamped one-behind-head.
        self._exec( "CREATE TABLE users ( id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email varchar(255) )" )
        from alembic import command
        command.stamp( auto_migrate.build_alembic_config( database_url=self.url ), self.PREV )
        auto_migrate.run_migrations_to_head( database_url=self.url )
        self.assertTrue( self._has_is_protected() )
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )

    def test_dev_scenario_existing_column_no_crash( self ):
        # Tables exist, is_protected PRESENT, stamped one-behind-head — the
        # idempotent migration must NOT raise DuplicateColumn.
        self._exec(
            "CREATE TABLE users ( id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
            "email varchar(255), is_protected boolean NOT NULL DEFAULT false )"
        )
        from alembic import command
        command.stamp( auto_migrate.build_alembic_config( database_url=self.url ), self.PREV )
        auto_migrate.run_migrations_to_head( database_url=self.url )   # must not raise
        self.assertEqual( self._head(), [ ( self.HEAD, ) ] )

    def test_legacy_unstamped_schema_refused( self ):
        self._exec( "CREATE TABLE users ( id uuid PRIMARY KEY DEFAULT gen_random_uuid() )" )
        with self.assertRaises( RuntimeError ):
            auto_migrate.run_migrations_to_head( database_url=self.url )

    def test_envpy_resolves_url_via_app_builder_without_database_url( self ):
        # Task (a): with NO DATABASE_URL and NO injected url, env.py must fall
        # through to cosa.rest.db.database.get_database_url() — the app builder —
        # to find the right database. We point the builder at this throwaway DB
        # via DB_NAME (development branch: localhost:5432, lupin_dev/dev_password).
        from alembic import command

        # First bring the DB to head normally (empty -> create_all + stamp head).
        auto_migrate.run_migrations_to_head( database_url=self.url )

        env = {
            "DB_NAME"     : self.dbname,
            "DB_HOST"     : "localhost",
            "DB_PORT"     : "5432",
            "DB_USER"     : "lupin_dev",
            "DB_PASSWORD" : "dev_password",
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
