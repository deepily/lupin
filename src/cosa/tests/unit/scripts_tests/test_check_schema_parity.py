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
# Live integration — dropped-column detection against a DISPOSABLE Postgres
# ---------------------------------------------------------------------------
# 🔴 THIS LAYER USED TO TOUCH THE LIVE DEV STORE. Corrected 2026-07-27 on Mr
# Radio's stop-and-fix, under Rick's standing rule (decision `2b20a6d6`,
# verbatim): "I absolutely do not want any test touching a live dev data store!
# If it's not isolated then it needs to be removed or fixed."
#
# What it did: connected to `lupin_db_dev` on localhost:5432 with hardcoded dev
# credentials and `CREATE DATABASE`d throwaways there. Teardown was a clean
# `DROP DATABASE … WITH (FORCE)` and zero orphans were ever measured — but ZERO
# ORPHANS MEASURES HYGIENE, and the rule's predicate is CONTACT. A well-behaved
# exception tier was offered to Rick and he rejected the premise: intent does
# not launder the contact, and there is no known-good list.
#
# ⚠️ AND THE CONTACT WAS WORSE THAN THE SETUP LINE SUGGESTED. The old gate was
# `@unittest.skipUnless( _pg_reachable(), ... )`, and a decorator argument is
# evaluated at IMPORT time. So merely COLLECTING this file opened a connection
# to `lupin_db_dev` — the contact happened on every run of the whole unit suite,
# including the runs where this class then skipped.
#
# Now: the operator supplies a DISPOSABLE instance by env var. Unset by default,
# so the default posture is no database, no connection, and a LOUD named skip.
DISPOSABLE_PG_ENV = "LUPIN_TEST_DISPOSABLE_PG_ADMIN_URL"

# The live data stores no test may name in executable code. Assembled at runtime
# so this list is not itself a match for the scanner that reads this file.
_LIVE_STORE_NAMES = ( "lupin_db_" + "dev", "lupin_db_" + "prod" )


def throwaway_url( admin_url, dbname ):
    """
    Build the per-test throwaway DB URL from the operator's admin URL.

    Requires:
        - admin_url is a sqlalchemy URL; dbname is the throwaway's name

    Ensures:
        - returns a connectable URL string with the PASSWORD INTACT

    ⚠️ WHY THIS IS NOT `str( url )`. SQLAlchemy's `URL.__str__` renders the
    password as `***`, so `str()` produces a URL that LOOKS right and cannot
    authenticate — every opt-in run died `FATAL: password authentication failed`.
    Found by Clayton 😎 on the first real opt-in; it was invisible to me because
    a trust / `.pgpass` URL has no password to mask, and the skip meant nobody
    had ever executed this path.

    Returns:
        str
    """
    return admin_url.set( database=dbname ).render_as_string( hide_password=False )


def _live_store_literals( source ):
    """
    Return every EXECUTABLE string literal in `source` naming a live data store.

    Requires:
        - source is Python text

    Ensures:
        - returns a list of the offending literal values, [] when clean
        - comments cannot match: they do not survive parsing to AST
        - DOCSTRINGS are excluded deliberately — prose describing this defect is
          a record of it, not an instance of it
        - unparseable source raises rather than returning [], because a silent []
          from a broken parse is a green that means nothing

    Args:
        source: Python source text

    Returns:
        list[str]
    """
    import ast

    tree = ast.parse( source )

    docstring_nodes = set()
    for node in ast.walk( tree ):
        if isinstance( node, ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef ) ):
            body = getattr( node, "body", [] )
            if body and isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ) \
               and isinstance( body[ 0 ].value.value, str ):
                docstring_nodes.add( id( body[ 0 ].value ) )

    return [
        node.value
        for node in ast.walk( tree )
        if isinstance( node, ast.Constant ) and isinstance( node.value, str )
        and id( node ) not in docstring_nodes
        and any( name in node.value for name in _LIVE_STORE_NAMES )
    ]


def disposable_admin_url():
    """
    The operator-supplied admin URL of a DISPOSABLE Postgres, or None.

    Requires:
        - nothing; reads the environment only

    Ensures:
        - returns the URL string when DISPOSABLE_PG_ENV is set and non-blank
        - returns None otherwise
        - OPENS NO CONNECTION. The skip decision must never itself be the
          contact it exists to prevent — that was the original defect

    Returns:
        str | None
    """
    return os.environ.get( DISPOSABLE_PG_ENV ) or None


# The skip is decided by the ENVIRONMENT, not by probing a server. It names the
# variable so the skip is actionable rather than a silent hole in the suite.
@unittest.skipUnless(
    disposable_admin_url(),
    f"SKIPPED (not a pass): set {DISPOSABLE_PG_ENV} to a DISPOSABLE Postgres admin URL "
    f"to run the live parity layer. It CREATEs and DROPs databases, so it must never "
    f"point at a live dev/prod store (Rick's rule, decision 2b20a6d6)."
)
class TestCheckParityLive( unittest.TestCase ):

    def setUp( self ):
        import psycopg2
        from psycopg2 import sql
        from sqlalchemy.engine import make_url

        self._sql   = sql
        admin_url   = make_url( disposable_admin_url() )
        self.dbname = "lupin_parity_ut_" + uuid.uuid4().hex[ :12 ]

        self._admin = psycopg2.connect(
            dbname   = admin_url.database,
            user     = admin_url.username,
            password = admin_url.password,
            host     = admin_url.host,
            port     = admin_url.port or 5432,
        )
        self._admin.autocommit = True
        # Registered BEFORE the CREATE so a failure anywhere below still closes it.
        self.addCleanup( self._admin.close )

        with self._admin.cursor() as cur:
            cur.execute( sql.SQL( "CREATE DATABASE {}" ).format( sql.Identifier( self.dbname ) ) )

        # ⚠️ REGISTERED IMMEDIATELY AFTER THE CREATE, not in tearDown. unittest does
        # NOT call tearDown when setUp raises, and `run_migrations_to_head` below CAN
        # raise — so a tearDown-based DROP leaks the throwaway on exactly the runs that
        # fail. Measured by Clayton 😎 on the first real opt-in: 2 orphan
        # `lupin_parity_ut_*` databases, one per failed attempt. addCleanup runs even
        # when a later line of setUp raises.
        self.addCleanup( self._drop_throwaway )

        # The throwaway inherits the operator's own connection details — nothing
        # about the target instance is hardcoded here any more.
        self.url = throwaway_url( admin_url, self.dbname )
        self._pg = dict(
            user     = admin_url.username,
            password = admin_url.password,
            host     = admin_url.host,
            port     = admin_url.port or 5432,
        )
        from cosa.rest.db.auto_migrate import run_migrations_to_head
        run_migrations_to_head( database_url=self.url )   # bootstrap to head from models

    def _drop_throwaway( self ):
        """Drop the per-test database. Safe to call when the CREATE succeeded and
        anything after it did not."""
        with self._admin.cursor() as cur:
            cur.execute(
                self._sql.SQL( "DROP DATABASE IF EXISTS {} WITH ( FORCE )" ).format( self._sql.Identifier( self.dbname ) )
            )

    def test_in_parity_then_dropped_column_flagged( self ):
        drift, _ = csp.check_parity( database_url=self.url )
        self.assertEqual( drift, {}, "freshly-bootstrapped DB should be in parity" )

        import psycopg2
        conn = psycopg2.connect( dbname=self.dbname, **self._pg )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute( "ALTER TABLE users DROP COLUMN is_protected" )
        conn.close()

        drift, _ = csp.check_parity( database_url=self.url )
        self.assertIn( "users", drift )
        self.assertIn( "is_protected", drift[ "users" ][ "model_only" ] )
        self.assertEqual( csp.main( [ "--database-url", self.url ] ), 1 )


# ---------------------------------------------------------------------------
# THE CONTROL — fails if the isolation is removed
# ---------------------------------------------------------------------------
class TestLiveLayerIsolation( unittest.TestCase ):
    """
    Always runs. If someone restores a hardcoded live-store target or a
    connecting skip-gate, these go RED.

    ⚠️ A test file that skips its own live layer is not evidence of isolation —
    the ORIGINAL defect skipped correctly and connected anyway, at collection.
    So the assertions below are about CONTACT, not about the skip.
    """

    def test_no_EXECUTABLE_string_in_this_module_names_a_live_data_store( self ):
        """
        The concrete regression: the live store was hardcoded twice — as the
        reachability probe's target and as the CREATE DATABASE admin connection.

        ⚠️ THE PREDICATE IS ABOUT CODE, NOT PROSE. A plain text scan flags the
        comments ABOVE that explain the defect, and a checker a description of
        the bug can trip is not a checker about the bug. So: parse to AST
        (comments do not survive), collect string CONSTANTS, drop docstrings.
        What is left is what can actually reach a connection.
        """
        offenders = _live_store_literals( open( __file__, encoding="utf-8" ).read() )
        self.assertEqual(
            offenders, [],
            f"a live data store name reached executable code in this file: {offenders}"
        )

    def test_the_scanner_ITSELF_catches_a_planted_offender( self ):
        """
        THE ARM THAT MUST FAIL. Without it, `_live_store_literals` returning []
        proves nothing — a scanner that always returns empty passes the test
        above forever. Plant the exact shape that was removed; require a hit.
        """
        planted = 'conn = psycopg2.connect( dbname="lupin_db_' + 'dev", host="x" )\n'
        self.assertTrue(
            _live_store_literals( planted ),
            "the scanner did not flag a hardcoded live-store connection — it is inert"
        )

    def test_the_scanner_does_NOT_flag_prose( self ):
        """The other direction: prose naming the store is a RECORD of the
        defect, not the defect. Without this the scanner could be a text grep."""
        prose = '# once connected to lupin_db_' + 'dev\n"""and lupin_db_' + 'dev in a docstring."""\n'
        self.assertEqual( _live_store_literals( prose ), [] )

    def test_IMPORTING_this_module_opens_NO_connection( self ):
        """
        🔴 THE COLLECTION-SCOPE CONTROL — the half a "the test didn't run" check
        misses entirely.

        `@unittest.skipUnless( _pg_reachable(), … )` evaluates its argument at
        IMPORT time, so the old gate dialled the live database during pytest
        COLLECTION, before any test ran and regardless of whether it then
        skipped. Deleting the test class would not have fixed that; the gate had
        to go.

        Runs in a SUBPROCESS because this module is already imported in-process —
        an in-process check could never observe its own import-time behaviour.
        `psycopg2.connect` is replaced before the import, so any attempt aborts
        with a nameable marker.
        """
        import subprocess

        probe = (
            "import sys, importlib, psycopg2\n"
            "def _trap( *a, **k ): raise SystemExit( 'CONNECTED_AT_IMPORT' )\n"
            "psycopg2.connect = _trap\n"
            f"sys.path.insert( 0, {os.path.dirname( os.path.abspath( __file__ ) )!r} )\n"
            # Importing the TEST module is what reproduces collection: the module
            # body runs, and any decorator argument is evaluated right there.
            "importlib.import_module( 'test_check_schema_parity' )\n"
            "print( 'IMPORTED_CLEAN' )\n"
        )
        env = dict( os.environ )
        env.pop( DISPOSABLE_PG_ENV, None )   # the default posture is what is under test
        result = subprocess.run(
            [ sys.executable, "-c", probe ],
            capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertNotIn( "CONNECTED_AT_IMPORT", result.stdout + result.stderr,
                          "importing this module opened a database connection" )
        self.assertIn( "IMPORTED_CLEAN", result.stdout,
                       f"the probe did not complete, so it proves nothing:\n{result.stderr[-800:]}" )

    def test_the_throwaway_url_KEEPS_the_password( self ):
        """
        DEFECT 1 regression lock. `str( URL )` masks the password as `***`, so the
        URL looks correct and cannot authenticate. Every opt-in run died on it.

        The `str()` arm is the CONTROL: without it, an implementation that also
        masked would pass the first assertion by producing something merely
        non-empty. The two must DISAGREE.
        """
        from sqlalchemy.engine import make_url

        admin = make_url( "postgresql+psycopg2://someuser:s3cr3t@localhost:55433/postgres" )
        built = throwaway_url( admin, "lupin_parity_ut_deadbeef" )

        self.assertIn( "s3cr3t", built, "the password was masked — this URL cannot authenticate" )
        self.assertNotIn( "***", built )
        self.assertIn( "lupin_parity_ut_deadbeef", built )
        self.assertNotIn( "s3cr3t", str( admin.set( database="lupin_parity_ut_deadbeef" ) ),
                          "str() no longer masks — this control has stopped controlling" )

    def test_a_setUp_failure_still_DROPS_the_throwaway( self ):
        """
        DEFECT 2 regression lock. unittest does NOT call tearDown when setUp
        raises, so a tearDown-based DROP leaks the database on exactly the runs
        that fail — measured as 2 orphans on the first real opt-in.

        Drives the real setUp with a fake psycopg2 and a migration that RAISES,
        then asserts a DROP was still issued. No database anywhere.
        """
        import psycopg2

        executed = []

        class _FakeCursor:
            def __enter__( self ): return self
            def __exit__( self, *a ): return False
            def execute( self, statement, *a ): executed.append( str( statement ) )

        class _FakeConn:
            autocommit = False
            def cursor( self ): return _FakeCursor()
            def close( self ): executed.append( "CLOSE" )

        real_connect = psycopg2.connect
        import cosa.rest.db.auto_migrate as am
        real_migrate = am.run_migrations_to_head

        def _boom( *a, **k ): raise RuntimeError( "migration blew up after CREATE" )

        psycopg2.connect          = lambda *a, **k: _FakeConn()
        am.run_migrations_to_head = _boom
        os.environ[ DISPOSABLE_PG_ENV ] = "postgresql+psycopg2://u:p@localhost:55433/postgres"
        try:
            # setUp/doCleanups directly, NOT case.run(): the class-level
            # `skipUnless` was evaluated at IMPORT with the env unset, so run()
            # skips and this scenario would silently prove nothing. (That the
            # decorator cannot be re-armed at runtime is itself confirmation the
            # gate is import-time — the property the original defect abused.)
            case = TestCheckParityLive( "test_in_parity_then_dropped_column_flagged" )
            with self.assertRaises( RuntimeError ):
                case.setUp()
            case.doCleanups()
        finally:
            psycopg2.connect          = real_connect
            am.run_migrations_to_head = real_migrate
            os.environ.pop( DISPOSABLE_PG_ENV, None )

        created = [ s for s in executed if "CREATE DATABASE" in s ]
        dropped = [ s for s in executed if "DROP DATABASE" in s ]
        self.assertTrue( created, "the scenario never reached the CREATE — it proves nothing" )
        self.assertTrue( dropped, "setUp raised after CREATE and the throwaway was NOT dropped" )

    def test_the_live_layer_is_OFF_unless_the_operator_opts_in( self, ):
        """
        Default posture: no env var, no database. Asserted against the real
        environment — if this box has the var set, the assertion inverts rather
        than being skipped, so the test still says something true.
        """
        if os.environ.get( DISPOSABLE_PG_ENV ):
            self.assertTrue( disposable_admin_url(), "env var set but not read" )
        else:
            self.assertIsNone( disposable_admin_url() )


if __name__ == "__main__":
    unittest.main()
