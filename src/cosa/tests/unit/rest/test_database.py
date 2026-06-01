"""
Unit tests for PostgreSQL session management (cosa.rest.db.database).

Covers get_database_url (production with/without required env → ValueError;
testing; development), get_pool_config (production / testing / development),
swap_database (engine/session rebuild + connection verify + password masking),
and get_db (commit-on-success / rollback-and-reraise-on-exception, always-close)
— to genuine 100% line + branch + function.

No real database connection: create_engine / sessionmaker / scoped_session are
patched in swap_database; SessionLocal is patched in get_db. Module-level engine
construction is lazy (no connection until .connect()). ZERO real DB.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import make_url

from cosa.rest.db import database


class TestGetDatabaseUrl( unittest.TestCase ):
    def test_production_requires_instance_and_password( self ):
        with patch.dict( os.environ, { "LUPIN_ENV": "production" }, clear=True ):
            with self.assertRaises( ValueError ):
                database.get_database_url()

    def test_production_builds_unix_socket_url( self ):
        env = {
            "LUPIN_ENV"                : "production",
            "CLOUD_SQL_CONNECTION_NAME": "proj:region:inst",
            "DB_PASSWORD"              : "secret",
        }
        with patch.dict( os.environ, env, clear=True ):
            url = database.get_database_url()
        self.assertIn( "host=/cloudsql/proj:region:inst", url )
        self.assertIn( "lupin_app", url )       # default DB_USER
        self.assertIn( "lupin_db_prod", url )   # default DB_NAME

    def test_testing_url( self ):
        with patch.dict( os.environ, { "LUPIN_ENV": "testing" }, clear=True ):
            url = database.get_database_url()
        self.assertTrue( url.startswith( "postgresql+psycopg2://" ) )
        self.assertIn( "lupin_db_test", url )

    def test_development_default_when_env_absent( self ):
        with patch.dict( os.environ, {}, clear=True ):
            url = database.get_database_url()
        self.assertIn( "lupin_db_dev", url )


class TestGetPoolConfig( unittest.TestCase ):
    def test_production_pooling( self ):
        with patch.dict( os.environ, { "LUPIN_ENV": "production" }, clear=True ):
            cfg = database.get_pool_config()
        self.assertEqual( cfg[ "pool_size" ], 5 )
        self.assertEqual( cfg[ "max_overflow" ], 10 )

    def test_testing_uses_nullpool( self ):
        with patch.dict( os.environ, { "LUPIN_ENV": "testing" }, clear=True ):
            cfg = database.get_pool_config()
        from sqlalchemy.pool import NullPool
        self.assertIs( cfg[ "poolclass" ], NullPool )

    def test_development_pooling( self ):
        with patch.dict( os.environ, {}, clear=True ):
            cfg = database.get_pool_config()
        self.assertEqual( cfg[ "pool_size" ], 10 )
        self.assertEqual( cfg[ "max_overflow" ], 20 )


class TestSwapDatabase( unittest.TestCase ):
    """Rebuild engine/session globals and verify connectivity — all SA primitives mocked."""

    def setUp( self ):
        self._orig_engine  = database.engine
        self._orig_local   = database.SessionLocal
        self._orig_scoped  = database.ScopedSession

    def tearDown( self ):
        database.engine        = self._orig_engine
        database.SessionLocal  = self._orig_local
        database.ScopedSession = self._orig_scoped

    def test_swap_rebuilds_and_masks_password( self ):
        new_engine     = MagicMock( name="new_engine" )
        new_engine.url = make_url( "postgresql+psycopg2://u:topsecret@h:5432/lupin_db_test" )
        with patch.dict( os.environ, {}, clear=True ), \
             patch.object( database, "engine", MagicMock( name="old_engine" ) ) as old_engine, \
             patch.object( database, "create_engine", return_value=new_engine ) as mk_engine, \
             patch.object( database, "sessionmaker" ) as mk_sm, \
             patch.object( database, "scoped_session" ) as mk_scoped:
            masked       = database.swap_database( "testing" )
            env_during   = os.environ[ "LUPIN_ENV" ]   # captured before patch.dict restores

        self.assertEqual( env_during, "testing" )
        old_engine.dispose.assert_called_once_with()
        mk_engine.assert_called_once()
        mk_sm.assert_called_once()
        mk_scoped.assert_called_once()
        # connection verified
        new_engine.connect.return_value.__enter__.return_value.execute.assert_called_once()
        # password masked
        self.assertIn( "***", masked )
        self.assertNotIn( "topsecret", masked )


class TestGetDb( unittest.TestCase ):
    def test_commit_and_close_on_success( self ):
        session = MagicMock( name="session" )
        with patch.object( database, "SessionLocal", return_value=session ):
            with database.get_db() as s:
                self.assertIs( s, session )
        session.commit.assert_called_once_with()
        session.close.assert_called_once_with()
        session.rollback.assert_not_called()

    def test_rollback_and_reraise_then_close_on_exception( self ):
        session = MagicMock( name="session" )
        with patch.object( database, "SessionLocal", return_value=session ):
            with self.assertRaises( ValueError ):
                with database.get_db():
                    raise ValueError( "boom" )
        session.rollback.assert_called_once_with()
        session.close.assert_called_once_with()
        session.commit.assert_not_called()


def isolated_unit_test():
    """
    Run the database session-management unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} database tests in {secs:.3f}s — {msg}" )
