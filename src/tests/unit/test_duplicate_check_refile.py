"""
Filing again from a saved result file, with every store write faked.

The result files here are made by the real daily run, so the findings are the producer's own.
The filing that reads them is the real file_findings. Nothing calls a model or the live store.
"""
import datetime
import io
import json

import pytest

from lupin_mcp import duplicate_check_daily as dd
from lupin_mcp import duplicate_check_filing as ff
from lupin_mcp import duplicate_check_refile as rf
from tests.unit.test_duplicate_check_daily import NOW, history, parts_of, repo, results   # noqa: F401  (repo is a fixture)
from tests.unit.test_duplicate_check_filing import Store, resolver

LATER = NOW + datetime.timedelta( hours=3 )


def working_filer( store, folder_seen=None ):
    """Ensures: returns a filer that files with the real file_findings against this store."""
    def filer( findings, folder ):
        if folder_seen is not None: folder_seen.append( folder )
        return ff.file_findings( findings, folder, store, "Cheech", [ "Cheech", "Tiberius" ], resolver( "lineage" ) )
    return filer


def broken_filer( findings, folder ):
    """Ensures: raises the way a missing key file or a client that cannot start does."""
    raise ConnectionError( "store down" )


def a_day_whose_filing_failed( repo, tmp_path ):
    """Ensures: runs the real daily check with a raising filer; returns its result file path."""
    history( repo )
    doc = dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path, filer=broken_filer ) )
    assert doc[ "filing" ] == { "error": "ConnectionError: store down" }, "the day's filing failed"
    return results( tmp_path )[ 0 ]


def test_the_daily_run_keeps_its_findings_without_their_text_and_with_their_store_keys( repo, tmp_path ):
    path = a_day_whose_filing_failed( repo, tmp_path )
    kept = json.loads( path.read_text() )[ "findings" ]
    assert len( kept ) == 3 and all( "text" not in f for f in kept ), "three findings, none holding source text"
    assert all( f[ "correlation_key" ].startswith( ff.KEY_PREFIX ) and len( f[ "correlation_key" ] ) == len( ff.KEY_PREFIX ) + ff.KEY_HEX for f in kept )
    assert len( { f[ "correlation_key" ] for f in kept } ) == 3 and all( set( rf.NEEDED ) <= set( f ) for f in kept )


def test_a_file_with_no_findings_list_cannot_be_refiled_and_a_run_with_no_filer_now_keeps_them( repo, tmp_path ):
    history( repo )
    dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    path = results( tmp_path )[ 0 ]
    doc  = json.loads( path.read_text() )
    assert len( doc[ "findings" ] ) == 3, "a run with no filer keeps its findings"
    del doc[ "findings" ]
    path.write_text( json.dumps( doc ) )
    out = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=broken_filer ) == 3 and "holds no findings list" in out.getvalue() and "Nothing was filed." in out.getvalue()


def test_refiling_a_failed_day_files_every_finding_once_in_the_folder_of_the_file( repo, tmp_path ):
    path   = a_day_whose_filing_failed( repo, tmp_path )
    store  = Store()
    folders = []
    out    = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store, folders ), now=LATER ) == 0
    answer = json.loads( out.getvalue() )
    assert len( answer[ ff.FILED ] ) == 3 and not answer[ ff.ALREADY ] and not answer[ ff.QUEUED ] and not answer[ ff.REFUSED ]
    assert len( store.created ) == 3 and folders == [ path.parent ], "three rows made, the spool folder is the file's own"
    assert {p[ "correlation_key" ] for p in store.created} == {f[ "correlation_key" ] for f in json.loads( path.read_text() )[ "findings" ]}, "each row has its finding's key"
    assert all( p[ "created_by" ] == ff.CREATED_BY and p[ "priority" ] == ff.PRIORITY for p in store.created )


def test_refiling_again_makes_no_second_row_and_adds_a_second_record( repo, tmp_path ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    store = Store()
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( store ), now=LATER ) == 0
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ), now=LATER + datetime.timedelta( hours=1 ) ) == 0
    again = json.loads( out.getvalue() )
    assert len( again[ ff.ALREADY ] ) == 3 and not again[ ff.FILED ], "the second run found every row"
    assert len( store.created ) == 3, "the store was asked to create three rows in all"
    kept = json.loads( path.read_text() )[ rf.REFILINGS ]
    assert [ r[ "at" ] for r in kept ] == [ LATER.isoformat(), ( LATER + datetime.timedelta( hours=1 ) ).isoformat() ]
    assert len( kept[ 0 ][ "answer" ][ ff.FILED ] ) == 3 and len( kept[ 1 ][ "answer" ][ ff.ALREADY ] ) == 3


def test_a_finding_whose_row_the_first_try_made_is_not_made_again( repo, tmp_path ):
    path   = a_day_whose_filing_failed( repo, tmp_path )
    store  = Store()
    keys   = [ f[ "correlation_key" ] for f in json.loads( path.read_text() )[ "findings" ] ]
    store.rows[ keys[ 0 ] ] = { "correlation_key": keys[ 0 ] }                   # the failed run did file one before it broke
    out    = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ) ) == 0
    answer = json.loads( out.getvalue() )
    assert [ r[ "key" ] for r in answer[ ff.ALREADY ] ] == [ keys[ 0 ] ] and len( answer[ ff.FILED ] ) == 2 and len( store.created ) == 2


def test_a_row_the_store_gates_stays_in_the_spool_once_and_the_command_says_something_is_left( repo, tmp_path ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    gated = Store( create=( False, 422, { "error": f"{ff.GATED_PHRASE} while the ratio is high" } ) )
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( gated ) ) == 1
    assert len( json.loads( out.getvalue() )[ ff.QUEUED ] ) == 3 and len( ff.read_pending( path.parent ) ) == 3
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( gated ) ) == 1
    assert len( ff.read_pending( path.parent ) ) == 3, "the same three findings are not spooled twice"
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( Store() ) ) == 0 and ff.read_pending( path.parent ) == [], "once the gate opens the spool drains"


def test_a_refused_row_makes_the_command_exit_one( repo, tmp_path ):
    path = a_day_whose_filing_failed( repo, tmp_path )
    out  = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( Store( create=( False, 403, { "error": "priority" } ) ) ) ) == 1
    assert len( json.loads( out.getvalue() )[ ff.REFUSED ] ) == 3


def test_a_filing_that_raises_leaves_the_file_unchanged_and_exits_three( repo, tmp_path ):
    path   = a_day_whose_filing_failed( repo, tmp_path )
    before = path.read_bytes()
    out    = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=broken_filer ) == 3
    assert "the filing raised ConnectionError: store down. The file is unchanged." in out.getvalue() and path.read_bytes() == before


def test_rows_filed_but_a_record_that_cannot_be_written_prints_the_answer_and_warns( repo, tmp_path, monkeypatch ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    store = Store()
    def full_disk( target, doc ): raise OSError( "disk full" )
    monkeypatch.setattr( rf.daily, "write_json", full_disk )
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ) ) == 3
    text  = out.getvalue()
    assert text.index( '"filed"' ) < text.index( "WARNING: the rows were filed, and the record could not be written: OSError: disk full." ), "the answer comes first, so it is not lost"
    assert len( store.created ) == 3 and rf.REFILINGS not in json.loads( path.read_text() )


def test_a_file_that_is_missing_not_json_or_not_a_result_could_not_be_refiled( tmp_path ):
    out = io.StringIO()
    assert rf.main( [ str( tmp_path / "none.json" ) ], out=out, filer=broken_filer ) == 3 and "FileNotFoundError" in out.getvalue()
    bad = tmp_path / "bad.json"
    bad.write_text( "not json", encoding="utf-8" )
    assert rf.main( [ str( bad ) ], out=io.StringIO(), filer=broken_filer ) == 3
    for text in ( "[1]", '{"findings": "x"}', '{"status": "ok"}' ):
        bad.write_text( text, encoding="utf-8" )
        with pytest.raises( rf.RefileError, match="holds no findings list" ): rf.read_result( bad )


def test_a_finding_that_lacks_a_field_the_row_needs_names_it( tmp_path ):
    full = { k: 1 for k in rf.NEEDED }
    bad  = tmp_path / "r.json"
    bad.write_text( json.dumps( { "findings": [ full, { k: v for k, v in full.items() if k not in ( "correlation_key", "others" ) } ] } ), encoding="utf-8" )
    with pytest.raises( rf.RefileError, match="finding 1 of .* lacks others, correlation_key" ): rf.read_result( bad )
    bad.write_text( json.dumps( { "findings": [ "not a dict" ] } ), encoding="utf-8" )
    with pytest.raises( rf.RefileError, match="finding 0 of .* lacks" ): rf.read_result( bad )


def test_a_file_with_no_findings_is_refiled_as_nothing_to_do( tmp_path ):
    path = tmp_path / "r.json"
    path.write_text( json.dumps( { "status": "ok", "findings": [] } ), encoding="utf-8" )
    out  = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( Store() ) ) == 0 and json.loads( out.getvalue() ) == { ff.FILED: [], ff.ALREADY: [], ff.QUEUED: [], ff.REFUSED: [] }


def test_the_command_defaults_to_the_live_filer_and_the_present_time( tmp_path, monkeypatch, capsys ):
    path = tmp_path / "r.json"
    path.write_text( json.dumps( { "findings": [] } ), encoding="utf-8" )
    seen = []
    monkeypatch.setattr( rf.daily, "live_filer", lambda findings, folder: seen.append( ( findings, folder ) ) or { ff.FILED: [], ff.ALREADY: [], ff.QUEUED: [], ff.REFUSED: [] } )
    assert rf.main( [ str( path ) ] ) == 0 and seen == [ ( [], tmp_path ) ]
    assert datetime.datetime.fromisoformat( json.loads( path.read_text() )[ rf.REFILINGS ][ 0 ][ "at" ] ).tzinfo is not None
    assert '"filed": []' in capsys.readouterr().out


def test_a_finding_with_a_key_and_no_text_makes_the_same_row_as_one_with_its_text():
    found  = { "id": "d-1", "name": "a1", "file": "client/a1.py", "line": 3, "text": "def a1(): pass", "session_id": "s-1", "window": { "start": "a", "end": "b", "commits": 1 }, "others": [ { "id": "d-9", "name": "twin", "file": "s/t.py" } ] }
    manager = { "manager": "Tiberius", "rung": "lineage", "note": "n" }
    assert ff.row_payload( ff.for_record( found ), manager ) == ff.row_payload( found, manager )
    assert "text" in found and "text" not in ff.for_record( found ) and ff.for_record( found )[ "correlation_key" ] == ff.correlation_key( "d-1", "def a1(): pass" )
