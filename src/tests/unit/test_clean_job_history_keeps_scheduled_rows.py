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

from cosa.rest import job_history_cleanup as rule
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
        if sql.lstrip().upper().startswith( ( "SET LOCAL", "LOCK TABLE" ) ):
            return _Result( [] )
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
    kept = rule.clean_job_history( conn )
    assert kept == [ "future::u" ]
    assert [ row[ 0 ] for row in conn.rows ] == [ "future::u" ]


def test_the_delete_is_bound_to_exactly_the_kept_ids():
    conn = _Connection( [ ( "a::u", "pending", _iso( timedelta( hours=2 ) ) ), ( "b::u", "completed", None ) ] )
    rule.clean_job_history( conn )
    ( _, delete_params ), = [ call for call in conn.seen if call[ 0 ].lstrip().upper().startswith( "DELETE" ) ]
    assert delete_params == { "keep": [ "a::u" ] }


def test_an_empty_table_sends_an_empty_keep_list_and_deletes_nothing_it_has_not_got():
    conn = _Connection( [] )
    assert rule.clean_job_history( conn ) == []
    assert [ params for sql, params in conn.seen if sql.lstrip().upper().startswith( "DELETE" ) ] == [ { "keep": [] } ]


def test_the_future_test_is_the_servers_own_predicate( monkeypatch ):
    """Replace the server's test with a constant: the helper must follow it, not a copy."""
    conn = _Connection( [ ( "future::u", "pending", _iso( timedelta( days=1 ) ) ) ] )
    monkeypatch.setattr( rule, "_is_future_scheduled", lambda scheduled_at: False )
    assert rule.clean_job_history( conn ) == []
    assert conn.rows == []


def test_the_delete_statement_spares_nothing_but_the_kept_ids():
    conn = _Connection( [ ( "x::u", "pending", _iso( timedelta( days=1 ) ) ) ] )
    rule.clean_job_history( conn )
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


def test_the_table_is_locked_before_the_kept_ids_are_read():
    conn = _Connection( [ ( "x::u", "pending", _iso( timedelta( days=1 ) ) ) ] )
    rule.clean_job_history( conn )
    kinds = [ sql.lstrip().split( None, 1 )[ 0 ].upper() + " " + sql.lstrip().split( None, 2 )[ 1 ].upper() for sql, _ in conn.seen ]
    assert kinds[ :4 ] == [ "SET LOCAL", "LOCK TABLE", "SELECT ID_HASH,", "DELETE FROM" ], kinds
    lock_sql = conn.seen[ 1 ][ 0 ]
    assert "SHARE ROW EXCLUSIVE" in lock_sql and "job_history" in lock_sql, lock_sql
    assert "lock_timeout" in conn.seen[ 0 ][ 0 ], "a lock that cannot be had must fail, not hang"


# ---- the planted row: it removes itself, and it cannot run if it survives ----------------------

class _Persistence:
    """An in-memory stand-in for job_persistence that honours what it is given."""

    def __init__( self, deletes=True, persists=True ):
        self.rows, self.deletes, self.persists, self.calls = {}, deletes, persists, []

    def persist_job_created_from_metadata( self, id_hash, user_id, metadata ):
        self.calls.append( "persist" )
        if self.persists: self.rows[ id_hash ] = { "id_hash": id_hash, "status": "pending", "metadata_json": metadata }

    def get_job_by_id_hash( self, id_hash ):
        return self.rows.get( id_hash )

    def delete_job_history( self, id_hash ):
        self.calls.append( "delete" )
        if self.deletes: self.rows.pop( id_hash, None )


def _metadata():
    return job_history_cleanup.planted_job_metadata( _iso( timedelta( days=1 ) ) )


def test_a_planted_row_exists_inside_the_block_and_is_gone_after_it():
    persistence = _Persistence()
    with job_history_cleanup.planted_job_row( persistence, "p::u", "u", _metadata() ) as id_hash:
        assert persistence.get_job_by_id_hash( id_hash )[ "status" ] == "pending"
    assert persistence.rows == {}


def test_a_planted_row_is_removed_even_when_the_test_body_fails():
    persistence = _Persistence()
    with pytest.raises( ZeroDivisionError ):
        with job_history_cleanup.planted_job_row( persistence, "p::u", "u", _metadata() ):
            1 / 0
    assert persistence.rows == {} and persistence.calls == [ "persist", "delete" ]


def test_a_row_that_cannot_be_removed_fails_the_teardown_and_names_the_row():
    persistence = _Persistence( deletes=False )
    with pytest.raises( AssertionError, match="p::u.*still in job_history" ):
        with job_history_cleanup.planted_job_row( persistence, "p::u", "u", _metadata() ):
            pass
    assert "p::u" in persistence.rows, "the stand-in was meant to leave the row behind"


def test_a_row_that_never_persisted_fails_before_the_body_runs_and_the_teardown_still_runs():
    persistence = _Persistence( persists=False )
    ran = []
    with pytest.raises( AssertionError, match="did not persist" ):
        with job_history_cleanup.planted_job_row( persistence, "p::u", "u", _metadata() ):
            ran.append( "body" )
    assert ran == [] and persistence.calls == [ "persist", "delete" ]


def test_remove_job_row_is_quiet_when_the_row_is_already_gone():
    persistence = _Persistence()
    job_history_cleanup.remove_job_row( persistence, "absent::u" )
    assert persistence.calls == [ "delete" ]


def test_the_planted_metadata_names_no_routing_command_and_no_real_job_type():
    metadata = job_history_cleanup.planted_job_metadata( "2099-01-01T00:00:00+00:00" )
    assert "routing_command" not in metadata
    assert metadata[ "agent_type" ] == "cleanup_survival_marker" and metadata[ "scheduled_at" ].startswith( "2099" )


def test_the_producer_stores_no_routing_command_for_the_planted_metadata( monkeypatch ):
    """The production producer runs over a recording session, so the stored value is its own."""
    from cosa.rest import job_persistence as jp
    added = []

    class _Session:
        def get( self, model, key ): return None
        def add( self, row ): added.append( row )

    class _Scope:
        def __enter__( self ): return _Session()
        def __exit__( self, *exc ): return False

    monkeypatch.setattr( jp, "get_db", lambda: _Scope() )
    jp.persist_job_created_from_metadata( "p::u", "u", _metadata() )
    ( row, ) = added
    assert row.routing_command is None and row.status == "pending" and row.id_hash == "p::u"


def test_the_restore_path_skips_a_row_with_no_routing_command_without_building_a_job():
    from cosa.rest import job_persistence as jp
    built = []
    entry = { "id_hash": "p::u", "job_type": "cleanup_survival_marker", "user_id": "u", "user_email": "", "session_id": "",
              "routing_command": "", "question_text": "", "scheduled_at": _iso( timedelta( days=1 ) ),
              "monopolize": False, "paused": False, "metadata_json": _metadata() }
    restored = jp.restore_pending_jobs( [ entry ], lambda **kw: built.append( kw ), ask_flow=None )
    assert restored == 0 and built == [], "a row with no routing command must never reach the job factory"


def _fixture_node( name ):
    path = os.path.join( ROOT, "src", "tests", "integration", "test_a_scheduled_job_survives_clean_test_db.py" )
    with open( path, encoding="utf-8" ) as handle: tree = ast.parse( handle.read() )
    found = [ n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == name ]
    assert len( found ) == 1, f"{name} appears {len( found )} times"
    return found[ 0 ]


def test_the_scheduled_job_fixture_plants_through_the_self_removing_block():
    node  = _fixture_node( "a_scheduled_job" )
    withs = [ n for n in ast.walk( node ) if isinstance( n, ast.With ) and "planted_job_row" in ast.dump( n.items[ 0 ] ) ]
    assert withs, "the fixture no longer plants through planted_job_row, so nothing removes its row"
    assert any( isinstance( inner, ast.Expr ) and isinstance( inner.value, ast.Yield ) for w in withs for inner in w.body ), \
        "the yield must sit inside the with block, or the row outlives the test"


def test_the_control_fixture_removes_its_row_in_a_finally_block_that_covers_the_yield():
    node    = _fixture_node( "a_finished_job" )
    tries   = [ n for n in ast.walk( node ) if isinstance( n, ast.Try ) and n.finalbody ]
    assert tries, "the control fixture has no finally block"
    finals  = " ".join( ast.dump( stmt ) for t in tries for stmt in t.finalbody )
    yields  = [ n for t in tries for n in ast.walk( ast.Module( body=t.body, type_ignores=[] ) ) if isinstance( n, ast.Yield ) ]
    assert "remove_job_row" in finals and yields, "the finally block must call remove_job_row and cover the yield"
