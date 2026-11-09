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
from tests.unit.test_duplicate_check_filing import Store

LATER = NOW + datetime.timedelta( hours=3 )


def working_filer( store, folder_seen=None ):
    """Ensures: returns a filer that files with the real file_findings against this store."""
    def filer( findings, folder ):
        if folder_seen is not None: folder_seen.append( folder )
        return ff.file_findings( findings, folder, store, "Cheech", [ "Cheech", "Tiberius" ] )
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
    assert len( kept ) == 1 and all( "text" not in f for f in kept ), "one finding for the one cluster, none holding source text"
    assert all( f[ "correlation_key" ].startswith( ff.KEY_PREFIX ) and len( f[ "correlation_key" ] ) == len( ff.KEY_PREFIX ) + ff.KEY_HEX for f in kept )
    assert len( { f[ "correlation_key" ] for f in kept } ) == 1 and all( set( rf.NEEDED ) <= set( f ) for f in kept )


def test_a_file_with_no_findings_list_cannot_be_refiled_and_a_run_with_no_filer_now_keeps_them( repo, tmp_path ):
    history( repo )
    dd.run( repo, NOW, "hand", 10, "/bin/claude", parts_of( tmp_path ) )
    path = results( tmp_path )[ 0 ]
    doc  = json.loads( path.read_text() )
    assert len( doc[ "findings" ] ) == 1, "a run with no filer keeps its findings"
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
    assert len( answer[ ff.FILED ] ) == 1 and not answer[ ff.ALREADY ] and not answer[ ff.QUEUED ] and not answer[ ff.REFUSED ]
    assert len( store.created ) == 1 and folders == [ path.parent ], "three findings, one row, and the spool folder is the file's own"
    keys = [ f[ "correlation_key" ] for f in json.loads( path.read_text() )[ "findings" ] ]
    assert store.created[ 0 ][ "correlation_key" ] == ff.run_key( keys ) and all( f[ "name" ] in store.created[ 0 ][ "body" ] for f in json.loads( path.read_text() )[ "findings" ] )
    assert store.created[ 0 ][ "created_by" ] == ff.filer_created_by( "cheech", ff.CREATED_BY ) and store.created[ 0 ][ "priority" ] == ff.PRIORITY and store.created[ 0 ][ "owner_persona" ] == "cheech"


def test_refiling_again_files_nothing_more_and_adds_a_second_record( repo, tmp_path ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    store = Store()
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( store ), now=LATER ) == 0
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ), now=LATER + datetime.timedelta( hours=1 ) ) == 0
    again = json.loads( out.getvalue() )
    assert again == { ff.FILED: [], ff.ALREADY: [], ff.QUEUED: [], ff.REFUSED: [], ff.RETIRED: [] }, "every finding is on the first row"
    assert len( store.created ) == 1, "the store was asked to create one row in all"
    kept = json.loads( path.read_text() )[ rf.REFILINGS ]
    assert [ r[ "at" ] for r in kept ] == [ LATER.isoformat(), ( LATER + datetime.timedelta( hours=1 ) ).isoformat() ]
    assert len( kept[ 0 ][ "answer" ][ ff.FILED ] ) == 1 and kept[ 1 ][ "answer" ][ ff.FILED ] == []


def test_a_run_row_the_first_try_made_is_not_made_again_even_when_the_triaged_file_is_gone( repo, tmp_path ):
    path   = a_day_whose_filing_failed( repo, tmp_path )
    store  = Store()
    keys   = [ f[ "correlation_key" ] for f in json.loads( path.read_text() )[ "findings" ] ]
    store.rows[ ff.run_key( keys ) ] = { "correlation_key": ff.run_key( keys ) }      # the failed run did file the row before it broke
    out    = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ) ) == 0
    answer = json.loads( out.getvalue() )
    assert [ r[ "key" ] for r in answer[ ff.ALREADY ] ] == [ ff.run_key( keys ) ] and answer[ ff.FILED ] == [] and store.created == []


def test_a_row_the_store_gates_stays_in_the_spool_once_and_the_command_says_something_is_left( repo, tmp_path ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    gated = Store( create=( False, 422, { "error": f"{ff.GATED_PHRASE} while the ratio is high" } ) )
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( gated ) ) == 1
    assert len( json.loads( out.getvalue() )[ ff.QUEUED ] ) == 1 and len( ff.read_pending( path.parent ) ) == 1
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( gated ) ) == 1
    assert len( ff.read_pending( path.parent ) ) == 1, "the same three findings are not spooled twice"
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( Store() ) ) == 0 and ff.read_pending( path.parent ) == [], "once the gate opens the spool drains"


def test_a_refused_row_makes_the_command_exit_one( repo, tmp_path ):
    path = a_day_whose_filing_failed( repo, tmp_path )
    out  = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( Store( create=( False, 403, { "error": "priority" } ) ) ) ) == 1
    assert len( json.loads( out.getvalue() )[ ff.REFUSED ] ) == 1


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
    assert len( store.created ) == 1 and rf.REFILINGS not in json.loads( path.read_text() )


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
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( Store() ) ) == 0 and json.loads( out.getvalue() ) == { ff.FILED: [], ff.ALREADY: [], ff.QUEUED: [], ff.REFUSED: [], ff.RETIRED: [] }


def test_the_command_defaults_to_the_live_filer_and_the_present_time( tmp_path, monkeypatch, capsys ):
    path = tmp_path / "r.json"
    path.write_text( json.dumps( { "findings": [] } ), encoding="utf-8" )
    seen = []
    monkeypatch.setattr( rf.daily, "live_filer", lambda findings, folder: seen.append( ( findings, folder ) ) or { ff.FILED: [], ff.ALREADY: [], ff.QUEUED: [], ff.REFUSED: [] } )
    assert rf.main( [ str( path ) ] ) == 0 and seen == [ ( [], tmp_path ) ]
    assert datetime.datetime.fromisoformat( json.loads( path.read_text() )[ rf.REFILINGS ][ 0 ][ "at" ] ).tzinfo is not None
    assert '"filed": []' in capsys.readouterr().out


def test_a_finding_with_a_key_and_no_text_makes_the_same_row_as_one_with_its_text():
    found  = { "id": "d-1", "name": "a1", "file": "client/a1.py", "line": 3, "text": "def a1(): pass", "window": { "start": "a", "end": "b", "commits": 1 }, "others": [ { "id": "d-9", "name": "twin", "file": "s/t.py" } ] }
    owner = { "owner": "cheech", "note": "n" }
    day   = datetime.date( 2026, 11, 7 )
    assert ff.triage_payload( [ ff.for_record( found ) ], owner, day ) == ff.triage_payload( [ found ], owner, day )
    assert "text" in found and "text" not in ff.for_record( found ) and ff.for_record( found )[ "correlation_key" ] == ff.correlation_key( "d-1", "def a1(): pass" )


def test_a_refile_of_an_older_file_titles_the_row_with_the_day_of_the_run_not_the_day_of_the_refile( repo, tmp_path ):
    path  = a_day_whose_filing_failed( repo, tmp_path )
    store = Store()
    assert json.loads( path.read_text() )[ "date" ] == "2026-11-03"
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( store ), now=NOW + datetime.timedelta( days=30 ) ) == 0
    assert store.created[ 0 ][ "title" ].startswith( "[LUPIN] Duplicate check 3 Nov:" ), "the run was on the 3rd"


def test_a_finding_that_already_names_its_day_keeps_it_and_a_file_without_session_ids_can_be_refiled( repo, tmp_path ):
    path = a_day_whose_filing_failed( repo, tmp_path )
    doc  = json.loads( path.read_text() )
    for f in doc[ "findings" ]: f.pop( "session_id", None ); f[ "day" ] = "2026-10-01"
    path.write_text( json.dumps( doc ) )
    store = Store()
    assert rf.main( [ str( path ) ], out=io.StringIO(), filer=working_filer( store ) ) == 0 and "1 Oct:" in store.created[ 0 ][ "title" ]


def test_a_refile_passes_the_files_name_to_the_filer_and_a_run_saves_its_own_file_name_and_day_in_each_finding( repo, tmp_path ):
    path = a_day_whose_filing_failed( repo, tmp_path )
    kept = json.loads( path.read_text() )[ "findings" ]
    assert all( f[ "run_file" ] == path.name and f[ "day" ] == "2026-11-03" for f in kept )
    seen = []
    rf.refile( path, filer=lambda findings, folder: seen.extend( findings ) or { }, now=NOW )
    assert {f[ "run_file" ] for f in seen} == { path.name }
    doc = json.loads( path.read_text() )
    for f in doc[ "findings" ]: f.pop( "run_file" )
    path.write_text( json.dumps( doc ) )
    seen.clear()
    rf.refile( path, filer=lambda findings, folder: seen.extend( findings ) or { }, now=NOW )
    assert {f[ "run_file" ] for f in seen} == { path.name }, "a file written before run_file existed gets its own name"


def a_result_in_the_old_shape( repo, tmp_path ):
    """
    Ensures: returns ( path, ids ) of a real run's file rewritten to the old shape.

    The real run's one finding is the base. Two copies get their own ids and keys.
    One is the other side of the base's cluster. The other is the member of a second cluster.
    """
    path = a_day_whose_filing_failed( repo, tmp_path )
    doc  = json.loads( path.read_text() )
    base = doc[ "findings" ][ 0 ]
    twin = { **base, "id": "d-zz-twin", "correlation_key": "epic:dupcheck-00000000000000aa", "name": "twin" }
    solo = { **base, "id": "d-zz-solo", "correlation_key": "epic:dupcheck-00000000000000bb", "name": "solo" }
    doc[ "findings" ] = [ base, twin, solo ]
    doc[ "clusters" ]  = [ [ base[ "id" ], "d-zz-twin" ], [ "d-zz-solo", "d-zz-other" ] ]
    path.write_text( json.dumps( doc ) )
    return path, ( base[ "id" ], "d-zz-twin", "d-zz-solo" )


def test_refiling_an_old_shape_file_files_one_finding_per_cluster_and_records_how_many_it_dropped( repo, tmp_path ):
    path, ids = a_result_in_the_old_shape( repo, tmp_path )
    store = Store()
    rf.refile( path, working_filer( store ), LATER )
    row   = store.created[ 0 ]
    listed = [ l for l in row[ "body" ].splitlines() if l.startswith( "- " ) ]
    assert len( store.created ) == 1 and len( listed ) == 2 and ids[ 1 ] not in row[ "body" ] and any( ids[ 0 ] in l for l in listed ) and any( ids[ 2 ] in l for l in listed )
    note = json.loads( path.read_text() )[ rf.REFILINGS ][ -1 ]
    assert ( note[ "findings_in_file" ], note[ "findings_filed" ] ) == ( 3, 2 )


def test_refiling_leaves_out_a_cluster_with_a_verdict_on_either_side( repo, tmp_path ):
    path, ids = a_result_in_the_old_shape( repo, tmp_path )
    ( tmp_path / "io" / "duplicate-check-daily" / "verdicts.jsonl" ).write_text( json.dumps( { "run": path.stem, "finding": ids[ 1 ], "verdict": "DISTINCT", "class": "c", "by": "x", "ts": "2026-11-09T15:00:00Z" } ) + "\n" )
    store = Store()
    rf.refile( path, working_filer( store ), LATER )
    row   = store.created[ 0 ]
    assert len( store.created ) == 1 and ids[ 2 ] in row[ "body" ] and ids[ 0 ] not in row[ "body" ] and ids[ 1 ] not in row[ "body" ], "the twin's verdict settled the pair, the other cluster is filed"
    assert json.loads( path.read_text() )[ rf.REFILINGS ][ -1 ][ "findings_filed" ] == 1


def test_a_damaged_verdicts_file_stops_a_refile_before_anything_is_filed( repo, tmp_path ):
    path, _ = a_result_in_the_old_shape( repo, tmp_path )
    ( tmp_path / "io" / "duplicate-check-daily" / "verdicts.jsonl" ).write_text( "garbage\n" )
    store = Store()
    out   = io.StringIO()
    assert rf.main( [ str( path ) ], out=out, filer=working_filer( store ), now=LATER ) == rf.EXIT_NONE and store.created == [] and "not a verdict record" in out.getvalue()


def test_regroup_without_clusters_drops_only_settled_findings_and_keeps_one_in_no_cluster_unless_settled():
    f = lambda i, k: { "id": i, "correlation_key": k }
    assert rf.regroup( [ f( "a", "k1" ), f( "b", "k2" ) ], None, { "k2" } ) == [ f( "a", "k1" ) ]
    got = rf.regroup( [ f( "a", "k1" ), f( "b", "k2" ), f( "c", "k3" ), f( "d", "k4" ) ], [ [ "b", "a" ], [ "x", "y" ] ], { "k4" } )
    assert [ x[ "id" ] for x in got ] == [ "a", "c" ], "a cluster with no finding gives none; c is in no cluster and kept; d is in none and settled"
