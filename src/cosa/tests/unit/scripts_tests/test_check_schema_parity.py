"""
Unit tests for src/scripts/check_schema_parity.py — the read-only ORM-model
vs live-DB schema parity checker.

Mocked unit layer (always run) drives every function/branch to 100%; a live
layer (skipped if Postgres is unreachable) proves the dropped-column detection
end-to-end against a throwaway DB.
"""

import io
import os
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

# check_schema_parity lives under src/scripts (not a package) — import by path.
_SCRIPTS_DIR = os.path.join(
    os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( __file__ ) ) ) ) ),
    "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert( 0, _SCRIPTS_DIR )

import check_schema_parity as csp   # noqa: E402


class TestPureHelpers( unittest.TestCase ):

    def test_get_model_columns_includes_users_is_protected( self ):
        cols = csp.get_model_columns()
        self.assertIn( "users", cols )
        self.assertIn( "is_protected", cols[ "users" ] )

    def test_compute_drift_model_only( self ):
        drift = csp.compute_drift( { "t": { "a", "b" } }, { "t": { "a" } } )
        self.assertEqual( drift[ "t" ][ "model_only" ], [ "b" ] )
        self.assertEqual( drift[ "t" ][ "db_only" ], [] )
        self.assertFalse( drift[ "t" ][ "missing_table" ] )

    def test_compute_drift_db_only( self ):
        drift = csp.compute_drift( { "t": { "a" } }, { "t": { "a", "x" } } )
        self.assertEqual( drift[ "t" ][ "db_only" ], [ "x" ] )

    def test_compute_drift_missing_table_flagged( self ):
        drift = csp.compute_drift( { "t": { "a", "b" } }, { "t": set() } )
        self.assertTrue( drift[ "t" ][ "missing_table" ] )
        self.assertEqual( drift[ "t" ][ "model_only" ], [ "a", "b" ] )

    def test_compute_drift_in_parity_table_omitted( self ):
        drift = csp.compute_drift( { "t": { "a" } }, { "t": { "a" } } )
        self.assertEqual( drift, {} )

    def test_compute_drift_uses_empty_set_for_absent_db_table( self ):
        # db_columns lacks the key entirely → treated as empty set.
        drift = csp.compute_drift( { "t": { "a" } }, {} )
        self.assertTrue( drift[ "t" ][ "missing_table" ] )

    def test_format_report_parity( self ):
        self.assertIn( "Schema parity", csp.format_report( {} ) )

    def test_format_report_drift_all_sections( self ):
        drift = {
            "users"   : { "model_only": [ "is_protected" ], "db_only": [], "missing_table": False },
            "ghosts"  : { "model_only": [ "a" ], "db_only": [ "b" ], "missing_table": True },
            # db_only-ONLY entry (empty model_only) covers the false arm of the
            # `if info["model_only"]` branch in format_report.
            "orphans" : { "model_only": [], "db_only": [ "stale_col" ], "missing_table": False },
        }
        report = csp.format_report( drift )
        self.assertIn( "DRIFT", report )
        self.assertIn( "model-only", report )
        self.assertIn( "db-only", report )
        self.assertIn( "TABLE MISSING", report )
        self.assertIn( "stale_col", report )


class TestGetDbColumns( unittest.TestCase ):

    def test_maps_rows_into_sets( self ):
        rows = [ ( "users", "id" ), ( "users", "email" ), ( "notifications", "id" ) ]
        fake_conn = MagicMock()
        fake_conn.execute.return_value = rows
        fake_engine = MagicMock()
        fake_engine.connect.return_value.__enter__.return_value = fake_conn

        result = csp.get_db_columns( fake_engine, [ "users", "notifications" ] )
        self.assertEqual( result[ "users" ], { "id", "email" } )
        self.assertEqual( result[ "notifications" ], { "id" } )


class TestCheckParity( unittest.TestCase ):

    def test_resolves_url_and_disposes_engine( self ):
        fake_engine = MagicMock()
        with patch( "check_schema_parity.resolve_database_url", return_value="postgresql://x" ) as rdu, \
             patch( "check_schema_parity.create_engine", return_value=fake_engine ), \
             patch( "check_schema_parity.get_model_columns", return_value={ "t": { "a" } } ), \
             patch( "check_schema_parity.get_db_columns", return_value={ "t": { "a" } } ):
            drift, report = csp.check_parity()
        rdu.assert_called_once()
        fake_engine.dispose.assert_called_once()
        self.assertEqual( drift, {} )
        self.assertIn( "Schema parity", report )

    def test_passes_explicit_url_through( self ):
        fake_engine = MagicMock()
        with patch( "check_schema_parity.resolve_database_url", return_value="postgresql://explicit" ) as rdu, \
             patch( "check_schema_parity.create_engine", return_value=fake_engine ), \
             patch( "check_schema_parity.get_model_columns", return_value={ "t": { "a" } } ), \
             patch( "check_schema_parity.get_db_columns", return_value={ "t": set() } ):
            drift, _ = csp.check_parity( database_url="postgresql://explicit" )
        rdu.assert_called_once_with( "postgresql://explicit" )
        self.assertIn( "t", drift )


class TestClassify( unittest.TestCase ):
    """
    THREE OUTCOMES, NOT TWO (row 3eb6dc41). The probe shipped with two: an
    unreachable database raised out of main and CPython exited 1 — byte-identical
    to DRIFT. Anything wiring it would have printed drift's remedy ("run a
    migration") at an operator whose database was merely unreachable.
    """

    def test_a_reason_ALWAYS_wins_and_is_never_folded_into_a_verdict( self ):
        code, verdict, detail = csp.classify( None, "connection refused" )
        self.assertEqual( code, csp.EXIT_CANNOT_DETERMINE )
        self.assertEqual( verdict, "CANNOT_DETERMINE" )
        self.assertIn( "connection refused", detail )

    def test_a_reason_wins_even_when_a_drift_dict_is_also_present( self ):
        # An error must never be reported as drift, whatever else was collected.
        code, verdict, _ = csp.classify( { "users": {} }, "boom" )
        self.assertEqual( code, csp.EXIT_CANNOT_DETERMINE )
        self.assertEqual( verdict, "CANNOT_DETERMINE" )

    def test_a_multiline_reason_is_FLATTENED_to_one_line( self ):
        # A shell caller reads this with `grep -m1 '^DETAIL='`; an unflattened
        # DBAPI message would truncate to its first line and drop the host.
        _, _, detail = csp.classify( None, "line one\n\tIs the server running?\n\nmore" )
        self.assertNotIn( "\n", detail )
        self.assertIn( "Is the server running?", detail )

    def test_drift_names_its_tables_sorted( self ):
        code, verdict, detail = csp.classify( { "zeta": {}, "alpha": {} }, None )
        self.assertEqual( code, csp.EXIT_DRIFT )
        self.assertEqual( verdict, "DRIFT" )
        self.assertEqual( detail, "tables with drift: alpha, zeta" )

    def test_empty_drift_is_parity_with_no_detail( self ):
        code, verdict, detail = csp.classify( {}, None )
        self.assertEqual( code, csp.EXIT_PARITY )
        self.assertEqual( verdict, "PARITY" )
        self.assertEqual( detail, "" )

    def test_the_three_exit_codes_are_pairwise_DISTINCT( self ):
        codes = { csp.EXIT_PARITY, csp.EXIT_DRIFT, csp.EXIT_CANNOT_DETERMINE }
        self.assertEqual( len( codes ), 3 )


class TestMain( unittest.TestCase ):

    def test_returns_zero_on_parity( self ):
        with patch( "check_schema_parity.check_parity", return_value=( {}, "ok" ) ):
            self.assertEqual( csp.main( [] ), 0 )

    def test_returns_one_on_drift( self ):
        with patch( "check_schema_parity.check_parity", return_value=( { "t": {} }, "drift" ) ):
            self.assertEqual( csp.main( [] ), 1 )

    def test_passes_database_url_arg( self ):
        with patch( "check_schema_parity.check_parity", return_value=( {}, "ok" ) ) as cp:
            csp.main( [ "--database-url", "postgresql://cli" ] )
        cp.assert_called_once_with( database_url="postgresql://cli" )

    def test_prints_a_PARSEABLE_record_on_parity( self ):
        with patch( "check_schema_parity.check_parity", return_value=( {}, "human report" ) ), \
             patch( "sys.stdout", new_callable=io.StringIO ) as out:
            code = csp.main( [] )
        printed = out.getvalue()
        self.assertEqual( code, csp.EXIT_PARITY )
        self.assertIn( "human report", printed )
        self.assertIn( "VERDICT=PARITY", printed )
        self.assertNotIn( "DETAIL=", printed )   # no detail line when there is no detail

    def test_prints_VERDICT_and_DETAIL_on_drift( self ):
        with patch( "check_schema_parity.check_parity", return_value=( { "users": {} }, "human report" ) ), \
             patch( "sys.stdout", new_callable=io.StringIO ) as out:
            code = csp.main( [] )
        printed = out.getvalue()
        self.assertEqual( code, csp.EXIT_DRIFT )
        self.assertIn( "VERDICT=DRIFT", printed )
        self.assertIn( "DETAIL=tables with drift: users", printed )

    def test_an_UNREACHABLE_database_is_CANNOT_DETERMINE_not_drift( self ):
        """
        MEASURED before the fix (2026-07-27, `127.0.0.1:59999`): traceback,
        EXIT=1 — indistinguishable from drift. This is the regression guard.
        """
        boom = RuntimeError( "connection refused" )
        with patch( "check_schema_parity.check_parity", side_effect=boom ), \
             patch( "sys.stdout", new_callable=io.StringIO ) as out:
            code = csp.main( [] )
        printed = out.getvalue()
        self.assertEqual( code, csp.EXIT_CANNOT_DETERMINE )
        self.assertNotEqual( code, csp.EXIT_DRIFT )
        self.assertIn( "VERDICT=CANNOT_DETERMINE", printed )
        self.assertIn( "RuntimeError: connection refused", printed )
        # No human report exists when the check could not run — and printing the
        # literal "None" in its place is the kind of noise a caller would parse.
        self.assertNotIn( "None", printed )


# ---------------------------------------------------------------------------
# Live integration — dropped-column detection against a throwaway DB
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
class TestCheckParityLive( unittest.TestCase ):

    def setUp( self ):
        import psycopg2
        from psycopg2 import sql
        self._sql = sql
        self.dbname = "lupin_parity_ut_" + uuid.uuid4().hex[ :12 ]
        self._admin = psycopg2.connect( dbname="lupin_db_dev", **_PG )
        self._admin.autocommit = True
        with self._admin.cursor() as cur:
            cur.execute( sql.SQL( "CREATE DATABASE {}" ).format( sql.Identifier( self.dbname ) ) )
        self.url = f"postgresql+psycopg2://lupin_dev:dev_password@localhost:5432/{self.dbname}"
        from cosa.rest.db.auto_migrate import run_migrations_to_head
        run_migrations_to_head( database_url=self.url )   # bootstrap to head from models

    def tearDown( self ):
        with self._admin.cursor() as cur:
            cur.execute(
                self._sql.SQL( "DROP DATABASE IF EXISTS {} WITH ( FORCE )" ).format( self._sql.Identifier( self.dbname ) )
            )
        self._admin.close()

    def test_in_parity_then_dropped_column_flagged( self ):
        drift, _ = csp.check_parity( database_url=self.url )
        self.assertEqual( drift, {}, "freshly-bootstrapped DB should be in parity" )

        import psycopg2
        conn = psycopg2.connect( dbname=self.dbname, **_PG )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute( "ALTER TABLE users DROP COLUMN is_protected" )
        conn.close()

        drift, _ = csp.check_parity( database_url=self.url )
        self.assertIn( "users", drift )
        self.assertIn( "is_protected", drift[ "users" ][ "model_only" ] )
        self.assertEqual( csp.main( [ "--database-url", self.url ] ), 1 )


if __name__ == "__main__":
    unittest.main()
