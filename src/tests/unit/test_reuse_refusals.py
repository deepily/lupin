"""
The refusal record: one line per scanned outcome line, once per document hash and line.

Every data folder here is temporary; nothing touches the shared one and nothing calls a model.
The call log and the search record are the real ones captured from a seat, copied into the temporary folder.
"""
import io
import json
import pathlib
import threading

import pytest

import cosa.utils.util as cu
from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_refusals as rr

HERE        = pathlib.Path( __file__ ).parent
REAL_LOG    = HERE / "reuse_call_log_real_2026.11.02.jsonl"
REAL_RECORD = HERE / "reuse_search_record_real_rs-bc3ca2c901.json"
RID, SID    = "5d37236290c7d93f", "rs-bc3ca2c901"                       # a real check_exists receipt and the real search made on it
PLAN        = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.24-reuse-detection-remediation-plan.md"
GOOD        = f"REUSE-OUTCOME {RID} :: {SID} :: REUSED lupin_mcp.reuse_shadow.sweep_of :: {PLAN}#12.3-D1"
NOT_IN_LOG  = f"REUSE-OUTCOME 0123456789abcdef :: {SID} :: REUSED m.q :: {PLAN}#12.3-D1"
BAD_SHAPE   = f"REUSE-OUTCOME {RID} :: {SID} :: REUSED two tokens :: {PLAN}#12.3-D1"
TOKEN_LINE  = f"REUSE-OUTCOME excluded :: {SID} :: WROTE_NEW m.zz was refused :: {PLAN}#12.3-D1"
MISMATCH    = f"REUSE-OUTCOME {RID} :: {SID} :: EXTENDED lupin_mcp.reuse_shadow.sweep_of :: {PLAN}#12.3-D1"
TEMPLATE    = "REUSE-OUTCOME <receipt id> :: <search id> :: REUSED <symbol> | EXTENDED <symbol> | WROTE_NEW <difference> :: <plan path>#<step>"
RULINGS     = f"RULING lupin_mcp.new_helper :: DUPLICATE :: reuse-receipt: {RID}\nRULING m.q :: DUPLICATE :: reuse-receipt: 0123456789abcdef"
ROOT        = pathlib.Path( cu.get_project_root() )


@pytest.fixture
def data( tmp_path ):
    """Ensures: a temporary data folder holding the real call log and the real search record."""
    ( tmp_path / "call-log" ).mkdir()
    ( tmp_path / "call-log" / "real.jsonl" ).write_text( REAL_LOG.read_text( encoding="utf-8" ), encoding="utf-8" )
    ( tmp_path / "search-records" ).mkdir()
    ( tmp_path / "search-records" / f"{SID}.json" ).write_text( REAL_RECORD.read_text( encoding="utf-8" ), encoding="utf-8" )
    return tmp_path


def document( tmp_path, *lines ):
    """Ensures: returns the path of a review document holding the rulings and the given lines."""
    doc = tmp_path / "review.md"
    doc.write_text( "# review\n\n" + RULINGS + "\n\n```text\n" + TEMPLATE + "\n```\n\n" + "\n".join( lines ) + "\n", encoding="utf-8" )
    return doc


def run( data, doc, *extra ):
    """Ensures: returns ( exit code, the printed summary ) of the command on a document."""
    out  = io.StringIO()
    code = rr.main( [ str( doc ), "--data-dir", str( data ), "--root", str( ROOT ), *extra ], out=out )
    return code, json.loads( out.getvalue() )


def kept( data ):
    """Ensures: returns the records of refusals.jsonl, one parsed object per line."""
    return [ json.loads( line ) for line in ( data / rr.REFUSALS_NAME ).read_text( encoding="utf-8" ).splitlines() ]


def test_a_run_leaves_one_record_per_scanned_line_accepted_or_refused_with_its_reason( data ):
    doc          = document( data, GOOD, NOT_IN_LOG, BAD_SHAPE, TOKEN_LINE, MISMATCH, "see REUSE-OUTCOME in the skill" )
    code, shown  = run( data, doc )
    rows         = kept( data )
    assert code == 1 and shown[ "scanned" ] == 5 and shown[ "refused" ] == 4 and shown[ "appended" ] == 5, "the template and the prose line are not scanned"
    assert [ ( r[ "status" ], r[ "line" ] ) for r in rows ] == [ ( "accepted", GOOD ), ( "refused", NOT_IN_LOG ), ( "refused", BAD_SHAPE ), ( "refused", TOKEN_LINE ), ( "refused", MISMATCH ) ]
    assert rows[ 0 ][ "reasons" ] == [] and rows[ 0 ][ "pairs" ] == [ [ "lupin_mcp.new_helper", RID ] ], "the pair the kind check read is kept"
    assert "receipt 0123456789abcdef is not in the log" in rows[ 1 ][ "reasons" ][ 0 ] and rows[ 1 ][ "pairs" ] == [ [ "m.q", "0123456789abcdef" ] ]
    assert rows[ 2 ][ "reasons" ] == [ "the line does not match the REUSE-OUTCOME shape" ] and rows[ 2 ][ "pairs" ] == []
    assert rows[ 3 ][ "reasons" ] == [ "m.zz has no EXCLUDED_ refusal in the log; re-run the lookup and check the log folder, since a failed log write looks the same" ], "a token reason"
    assert len( rows[ 4 ][ "reasons" ] ) == 1 and rows[ 4 ][ "reasons" ][ 0 ].startswith( "the outcome is EXTENDED but the ruling" ) and rows[ 4 ][ "pairs" ] == [ [ "lupin_mcp.new_helper", RID ] ], "a pairing reason"
    lines = doc.read_text( encoding="utf-8" ).splitlines()
    assert [ r[ "n" ] for r in rows ] == [ lines.index( x ) + 1 for x in ( GOOD, NOT_IN_LOG, BAD_SHAPE, TOKEN_LINE, MISMATCH ) ], "n is the line's position in the document, counting from 1"
    assert len( { r[ "doc" ] for r in rows } ) == 1 and shown[ "document" ] == rows[ 0 ][ "doc" ] == rr.document_hash( doc.read_text( encoding="utf-8" ) )
    assert [ x[ "n" ] for x in shown[ "refusals" ] ] == [ r[ "n" ] for r in rows[ 1: ] ]


def test_the_first_line_of_a_document_is_line_one():
    assert [ s[ "n" ] for s in rr.scanned_lines( GOOD + "\nprose\n" + NOT_IN_LOG ) ] == [ 1, 3 ]


def test_a_second_run_on_the_same_document_adds_nothing_and_a_changed_document_adds_its_own( data ):
    doc = document( data, GOOD, NOT_IN_LOG )
    assert run( data, doc )[ 1 ][ "appended" ] == 2
    before = ( data / rr.REFUSALS_NAME ).read_bytes()
    assert run( data, doc )[ 1 ][ "appended" ] == 0 and ( data / rr.REFUSALS_NAME ).read_bytes() == before, "the file is byte for byte the same"
    doc2 = document( data, GOOD, NOT_IN_LOG, f"{GOOD} " )
    assert run( data, doc2 )[ 1 ][ "appended" ] == 3, "a new document hash is counted afresh, line by line"
    assert len( { r[ "doc" ] for r in kept( data ) } ) == 2


def test_a_clean_document_exits_zero_and_a_missing_definition_is_reported( data, tmp_path ):
    doc = document( data, GOOD )
    assert run( data, doc )[ 0 ] == 0
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "added": [ "lupin_mcp.new_helper", "lupin_mcp.other_new" ], "removed": [], "changed": [] } ), encoding="utf-8" )
    code, shown = run( data, doc, "--diff", str( diff ) )
    assert code == 1 and [ m[ "symbol" ] for m in shown[ "missing" ] ] == [ "lupin_mcp.other_new" ] and shown[ "refused" ] == 0


def test_a_diff_that_reports_a_changed_algorithm_is_not_checked( data, tmp_path ):
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "algorithm_changed": True } ), encoding="utf-8" )
    code, shown = run( data, document( data, GOOD ), "--diff", str( diff ) )
    assert code == rr.NOT_CHECKED == 3 and "algorithm changed" in shown[ "error" ] and not ( data / rr.REFUSALS_NAME ).exists(), "nothing is recorded for a run that could not check"


def test_two_writers_never_tear_or_double_a_line( data ):
    verdicts = lambda doc_text, count: [ { "n": i, "line": "x" * 5000, "status": "refused", "reasons": [ "r" * 5000 ], "pairs": [] } for i in range( 1, count + 1 ) ]
    texts    = [ "document one", "document two" ]
    threads  = [ threading.Thread( target=rr.record, args=( data, texts[ i % 2 ], verdicts( texts[ i % 2 ], 40 ) ) ) for i in range( 6 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    rows = kept( data )                                                  # every line must parse: a torn line would raise here
    assert len( rows ) == 80 and len( { ( r[ "doc" ], r[ "n" ] ) for r in rows } ) == 80, "three writers per document, one record per document and line"
    assert {r[ "doc" ] for r in rows} == {rr.document_hash( t ) for t in texts}


def test_a_torn_last_line_and_a_foreign_line_do_not_stop_the_next_record( data ):
    path = data / rr.REFUSALS_NAME
    path.write_bytes( b'{"doc": "abc", "n": 1}\nnot json\n[1, 2]\n5\n"text"\nnull\n{"torn": ' )
    assert rr.record( data, "doc", [ { "n": 1, "line": "l", "status": "accepted", "reasons": [], "pairs": [] } ] ) == 1
    lines = path.read_text( encoding="utf-8" ).splitlines()
    assert lines[ -1 ].startswith( '{"at"' ) and json.loads( lines[ -1 ] )[ "n" ] == 1 and lines[ -2 ] == '{"torn": ', "the torn line stays and the new record starts on its own line"
    assert rr.record( data, "doc", [] ) == 0


def test_the_data_folder_defaults_to_the_lookup_tools_choice( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path ) )
    assert rr.default_data_dir( ROOT ) == str( tmp_path )
    monkeypatch.delenv( "LUPIN_REUSE_DATA_DIR" )
    from lupin_mcp import reuse_tools as rt
    assert rr.default_data_dir( ROOT ) == str( rt.data_dir( ROOT ) )


def test_main_reads_the_default_data_folder_and_the_call_log_beside_it( data, monkeypatch ):
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( data ) )
    out  = io.StringIO()
    code = rr.main( [ str( document( data, GOOD ) ), "--root", str( ROOT ) ], out=out )
    assert code == 0 and json.loads( out.getvalue() )[ "appended" ] == 1 and ( data / rr.REFUSALS_NAME ).exists()


def test_main_prints_to_standard_output_by_default( data, capsys ):
    assert rr.main( [ str( document( data, GOOD ) ), "--data-dir", str( data ), "--root", str( ROOT ) ] ) == 0
    assert json.loads( capsys.readouterr().out )[ "scanned" ] == 1


def test_an_unreadable_document_ends_with_a_reason_and_exit_three( data ):
    binary = data / "binary.md"
    binary.write_bytes( b"\xff\xfe not utf-8" )
    for path, needle in ( ( data / "no-such-review.md", "FileNotFoundError" ), ( binary, "UnicodeDecodeError" ) ):
        out = io.StringIO()
        assert rr.main( [ str( path ), "--data-dir", str( data ), "--root", str( ROOT ) ], out=out ) == 3 and needle in json.loads( out.getvalue() )[ "error" ]
    assert not ( data / rr.REFUSALS_NAME ).exists(), "nothing was recorded"


def test_a_missing_data_folder_ends_with_a_reason_and_exit_three( data, tmp_path ):
    out = io.StringIO()
    assert rr.main( [ str( document( data, GOOD ) ), "--data-dir", str( tmp_path / "no-such-folder" ), "--root", str( ROOT ) ], out=out ) == 3
    assert "FileNotFoundError" in json.loads( out.getvalue() )[ "error" ] and not ( tmp_path / "no-such-folder" ).exists(), "the folder is not made for it"


def test_a_diff_file_that_is_missing_or_not_a_symbol_index_diff_ends_with_a_reason_and_exit_three( data, tmp_path ):
    good = document( data, GOOD )
    bad  = tmp_path / "bad-diff.json"
    for body, needle in ( ( None, "FileNotFoundError" ), ( "{not json", "JSONDecodeError" ), ( "[1, 2]", "is not a symbol index diff" ), ( json.dumps( { "added": "m.x" } ), "is not a symbol index diff" ) ):
        if body is not None: bad.write_text( body, encoding="utf-8" )
        out = io.StringIO()
        assert rr.main( [ str( good ), "--data-dir", str( data ), "--root", str( ROOT ), "--diff", str( bad ) ], out=out ) == 3 and needle in json.loads( out.getvalue() )[ "error" ]
    assert not ( data / rr.REFUSALS_NAME ).exists(), "nothing was recorded"
