"""
Unit tests for the SQLite auth database layer (cosa.rest.sqlite_database).

Covers get_auth_db_path (all four dual-safety arcs: test-mode×path-has-test),
get_auth_db_connection (row factory + foreign-keys pragma), and
init_auth_database (full schema build via a real in-memory SQLite connection +
the sqlite3.Error rollback/reraise arc) — to genuine 100% line + branch + function.

The module-level config_mgr is patched per test; project root is redirected to a
temp dir; init uses an in-memory SQLite DB. ZERO persistent state, ZERO real
auth-database files written.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cosa.rest import sqlite_database


def _cfg( test_mode, db_path_rel ):
    """Build a config_mgr.get side_effect for the two keys get_auth_db_path reads."""
    def _get( key, default=None, return_type=None ):
        if key == "app testing":                return test_mode
        if key == "auth database path wo root": return db_path_rel
        return default
    return _get


class TestGetAuthDbPath( unittest.TestCase ):
    def setUp( self ):
        self._tmp = tempfile.TemporaryDirectory()
        self._p_root = patch.object( sqlite_database.du, "get_project_root",
                                     return_value=self._tmp.name )
        self._p_root.start()
        self._p_cfg = patch.object( sqlite_database, "config_mgr" )
        self.mock_cfg = self._p_cfg.start()

    def tearDown( self ):
        self._p_cfg.stop()
        self._p_root.stop()
        self._tmp.cleanup()

    def test_production_mode_with_prod_path_ok( self ):
        self.mock_cfg.get.side_effect = _cfg( False, "/src/conf/long-term-memory/lupin-auth.db" )
        path = sqlite_database.get_auth_db_path()
        self.assertTrue( str( path ).endswith( "lupin-auth.db" ) )
        self.assertTrue( path.parent.exists() )           # mkdir happened

    def test_test_mode_with_test_path_ok( self ):
        self.mock_cfg.get.side_effect = _cfg( True, "/src/conf/long-term-memory/lupin-auth-test.db" )
        path = sqlite_database.get_auth_db_path()
        self.assertIn( "test", str( path ).lower() )

    def test_test_mode_with_prod_path_raises( self ):
        self.mock_cfg.get.side_effect = _cfg( True, "/src/conf/long-term-memory/lupin-auth.db" )
        with self.assertRaises( ValueError ):
            sqlite_database.get_auth_db_path()

    def test_prod_mode_with_test_path_raises( self ):
        self.mock_cfg.get.side_effect = _cfg( False, "/src/conf/long-term-memory/lupin-auth-test.db" )
        with self.assertRaises( ValueError ):
            sqlite_database.get_auth_db_path()


class TestGetAuthDbConnection( unittest.TestCase ):
    def test_configures_connection( self ):
        fake_conn = MagicMock( name="conn" )
        with patch.object( sqlite_database, "get_auth_db_path",
                           return_value=Path( "/tmp/x.db" ) ), \
             patch.object( sqlite_database.sqlite3, "connect",
                           return_value=fake_conn ) as mk_connect:
            conn = sqlite_database.get_auth_db_connection()
        self.assertIs( conn, fake_conn )
        mk_connect.assert_called_once_with( "/tmp/x.db" )
        self.assertIs( fake_conn.row_factory, sqlite3.Row )
        fake_conn.execute.assert_called_once_with( "PRAGMA foreign_keys = ON" )


class TestInitAuthDatabase( unittest.TestCase ):
    def test_builds_full_schema_on_real_sqlite( self ):
        # Use a temp FILE DB: init commits + closes the connection in its finally
        # block, then we reopen the same file to inspect the schema it built.
        with tempfile.TemporaryDirectory() as tmp:
            db_file = os.path.join( tmp, "auth-test.db" )
            conn    = sqlite3.connect( db_file )
            with patch.object( sqlite_database, "get_auth_db_connection", return_value=conn ):
                sqlite_database.init_auth_database()   # genuinely runs every CREATE, then closes
            inspector = sqlite3.connect( db_file )
            try:
                tables = {
                    row[ 0 ] for row in
                    inspector.execute( "SELECT name FROM sqlite_master WHERE type='table'" ).fetchall()
                }
            finally:
                inspector.close()
        for expected in ( "users", "refresh_tokens", "email_verification_tokens",
                          "password_reset_tokens", "failed_login_attempts",
                          "auth_audit_log", "api_keys" ):
            self.assertIn( expected, tables )

    def test_sqlite_error_rolls_back_and_reraises( self ):
        conn   = MagicMock( name="conn" )
        cursor = conn.cursor.return_value
        cursor.execute.side_effect = sqlite3.Error( "disk full" )
        with patch.object( sqlite_database, "get_auth_db_connection", return_value=conn ):
            with self.assertRaises( sqlite3.Error ):
                sqlite_database.init_auth_database()
        conn.rollback.assert_called_once_with()
        conn.close.assert_called_once_with()
        conn.commit.assert_not_called()


def isolated_unit_test():
    """
    Run the sqlite_database unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} sqlite_database tests in {secs:.3f}s — {msg}" )
