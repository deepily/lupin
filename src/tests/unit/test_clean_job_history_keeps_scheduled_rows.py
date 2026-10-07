"""
The test-database cleanup keeps a pending job scheduled ahead and deletes the other rows.

A job scheduled on :8000 waits as a pending job_history row until the server restarts and restores it.
Both clean_test_db fixtures used to empty that table with a bulk truncate, so the job was lost.

The unit tier has no database, so a small in-memory connection stands in for one.
It answers the two statements the helper sends and applies them as their text says.
It records what it was given, so the tests depend on the helper's own inputs.
The real statements are run by an integration test on the live test server, not here.
"""

import ast
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import job_history_cleanup

ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )


def _iso( delta ):
    return ( datetime.now( timezone.utc ) + delta ).isoformat()


class _Result:
    def __init__( self, rows ): self._rows = rows
    def fetchall( self ):       return list( self._rows )


class _Connection:
    """An in-memory job_history: rows are ( id_hash, status, scheduled_at )."""

    def __init__( self, rows ):
        self.rows  = list( rows )
        self.seen  = []

    def execute( self, statement, params=None ):
        sql = str( statement )
        self.seen.append( ( sql, params ) )
        if sql.lstrip().upper().startswith( "SELECT" ):
            assert "status = 'pending'" in sql, "the candidate query no longer asks for pending rows only"
            return _Result( [ ( i, s ) for i, st, s in self.rows if st == "pending" ] )
        assert sql.lstrip().upper().startswith( "DELETE FROM JOB_HISTORY" ), sql
        keep      = params[ "keep" ]
        self.rows = [ row for row in self.rows if row[ 0 ] in keep ]
        return _Result( [] )


def test_a_pending_job_scheduled_in_the_future_is_kept_and_every_other_row_is_deleted():
    conn = _Connection( [
        ( "future::u",          "pending",   _iso( timedelta( days=1 ) ) ),
        ( "past::u",            "pending",   _iso( timedelta( days=-1 ) ) ),
        ( "immediate::u",       "pending",   None ),
        ( "garbled::u",         "pending",   "not-a-date" ),
        ( "done-future::u",     "completed", _iso( timedelta( days=1 ) ) ),
        ( "running-future::u",  "running",   _iso( timedelta( days=1 ) ) ),
        ( "failed::u",          "failed",    None ),
    ] )
    kept = job_history_cleanup.clean_job_history( conn )
    assert kept == [ "future::u" ]
    assert [ row[ 0 ] for row in conn.rows ] == [ "future::u" ]


def test_the_delete_is_bound_to_exactly_the_kept_ids():
    conn = _Connection( [ ( "a::u", "pending", _iso( timedelta( hours=2 ) ) ), ( "b::u", "completed", None ) ] )
    job_history_cleanup.clean_job_history( conn )
    ( _, delete_params ), = [ call for call in conn.seen if call[ 0 ].lstrip().upper().startswith( "DELETE" ) ]
    assert delete_params == { "keep": [ "a::u" ] }


def test_an_empty_table_sends_an_empty_keep_list_and_deletes_nothing_it_has_not_got():
    conn = _Connection( [] )
    assert job_history_cleanup.clean_job_history( conn ) == []
    assert [ params for sql, params in conn.seen if sql.lstrip().upper().startswith( "DELETE" ) ] == [ { "keep": [] } ]


def test_the_future_test_is_the_servers_own_predicate( monkeypatch ):
    """Replace the server's test with a constant: the helper must follow it, not a copy."""
    conn = _Connection( [ ( "future::u", "pending", _iso( timedelta( days=1 ) ) ) ] )
    monkeypatch.setattr( job_history_cleanup, "_is_future_scheduled", lambda scheduled_at: False )
    assert job_history_cleanup.clean_job_history( conn ) == []
    assert conn.rows == []


def test_the_delete_statement_spares_nothing_but_the_kept_ids():
    conn = _Connection( [ ( "x::u", "pending", _iso( timedelta( days=1 ) ) ) ] )
    job_history_cleanup.clean_job_history( conn )
    delete_sql = [ sql for sql, _ in conn.seen if sql.lstrip().upper().startswith( "DELETE" ) ][ 0 ]
    assert "id_hash <> ALL( CAST( :keep AS varchar[] ) )" in delete_sql, delete_sql


def _fixture_calls_and_truncate_text( path ):
    with open( os.path.join( ROOT, path ), encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    fixtures = [ n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == "clean_test_db" ]
    assert len( fixtures ) == 1, f"{path} has {len( fixtures )} clean_test_db fixtures"
    calls    = [ n.func.id for n in ast.walk( fixtures[ 0 ] ) if isinstance( n, ast.Call ) and isinstance( n.func, ast.Name ) ]
    strings  = [ n.value for n in ast.walk( fixtures[ 0 ] ) if isinstance( n, ast.Constant ) and isinstance( n.value, str ) ]
    return calls, [ text for text in strings if text.lstrip().startswith( "TRUNCATE" ) ]


@pytest.mark.parametrize( "path", [ "src/tests/integration/conftest.py", "src/tests/e2e_ui/conftest.py" ] )
def test_both_clean_test_db_fixtures_use_the_helper_and_no_longer_truncate_job_history( path ):
    calls, truncates = _fixture_calls_and_truncate_text( path )
    assert "clean_job_history" in calls, f"{path}: clean_test_db does not call clean_job_history"
    assert truncates, f"{path}: no TRUNCATE statement found, so the check below would pass over nothing"
    assert all( "job_history" not in statement for statement in truncates ), f"{path}: TRUNCATE still names job_history"


@pytest.mark.parametrize( "name", [ "test_a_scheduled_job_survives_clean_test_db_and_is_still_restorable", "test_clean_test_db_still_removes_a_finished_job" ] )
def test_the_survival_tests_build_their_rows_before_the_real_cleanup_runs( name ):
    path = os.path.join( ROOT, "src", "tests", "integration", "test_a_scheduled_job_survives_clean_test_db.py" )
    with open( path, encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    found = [ n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == name ]
    assert len( found ) == 1, f"{name} appears {len( found )} times"
    arguments = [ a.arg for a in found[ 0 ].args.args ]
    assert arguments.index( "clean_test_db" ) == len( arguments ) - 1 and "a_scheduled_job" in arguments, arguments
    assert max( arguments.index( "a_scheduled_job" ), arguments.index( "a_finished_job" ) ) < arguments.index( "clean_test_db" ), \
        f"clean_test_db would run before the rows exist: {arguments}"
