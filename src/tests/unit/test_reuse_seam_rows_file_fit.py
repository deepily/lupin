"""
Seam: the rows file the stage-two `rows` step writes and the fit script reads.

The searches and the twins are the live stage-two run's own (both sha256 recorded in the fixture).
They are the first sixteen members of its run file, whole, with their twins as its negatives record gives them.
The rows come from `rows_from_run` and `write_rows`, the split from the real split module.
The reader is `reuse_stage2_fit.main`.
Nothing here sends a request.
"""
import json
import pathlib

import pytest

from cosa.repo.symindex import stage2_split as ss
from lupin_mcp import reuse_stage2_fit as fit
from lupin_mcp import reuse_stage2_run as s2

FIXTURE = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "s2-run-searches-16-members-20261009.json"
RUN_SHA = "8bb790ddda879340c656634b0a904be2fed8ce51f8fd124f275c754326e3c668"
NEG_SHA = "7bc95228fa40707aca58a15d927b9807b8d54bd4cd8062b711b65321d0c38d6f"


def load():
    record = json.loads( FIXTURE.read_text( encoding="utf-8" ) )
    return record[ "source" ], record[ "searches" ], { m: set( t ) for m, t in record[ "twins" ].items() }


def written( tmp_path ):
    """Ensures: returns ( rows file path, split file path, the rows ) written by the real steps."""
    source, searches, twins = load()
    rows     = s2.rows_from_run( searches, twins )
    manifest = { "exact": [ { "members": [ { "id": m } ] + [ { "id": t } for t in sorted( ts ) ] } for m, ts in twins.items() ], "near": [] }
    split    = ss.split_record( manifest, "0" * 64, 20261008 )
    ( tmp_path / "split.json" ).write_text( json.dumps( split ), encoding="utf-8" )
    s2.write_rows( tmp_path / "rows.json", rows )
    return tmp_path / "rows.json", tmp_path / "split.json", rows


def test_the_fixture_names_the_files_it_was_cut_from_and_holds_both_questions_for_sixteen_members():
    source, searches, twins = load()
    assert source[ "run_file" ] == "s2-run.json" and source[ "run_sha256" ] == RUN_SHA and source[ "negatives_sha256" ] == NEG_SHA
    assert len( twins ) == 16 and len( searches ) == 32 and { s[ "question" ] for s in searches } == { "old", "new" }
    assert all( s[ "status" ] == "complete" and len( s[ "rows" ] ) > 0 for s in searches )


def test_the_rows_file_the_step_writes_reads_back_as_the_rows_it_joined_from_the_real_searches( tmp_path ):
    rows_path, _, rows = written( tmp_path )
    on_disk = json.loads( rows_path.read_text( encoding="utf-8" ) )
    assert on_disk[ "format" ] == s2.ROWS_FORMAT and on_disk[ "rows" ] == rows
    _, searches, twins = load()
    assert len( rows ) == sum( len( s[ "rows" ] ) for s in searches if s[ "question" ] == "old" )
    assert sum( 1 for r in rows if r[ "label" ] ) == sum( 1 for m, t in twins.items() for r in rows if r[ "member" ] == m and r[ "candidate" ] in t ) == 46


def test_the_fit_script_reads_that_file_and_reports_every_row_and_member_it_was_given( tmp_path, capsys ):
    rows_path, split_path, rows = written( tmp_path )
    assert fit.main( [ "--rows", str( rows_path ), "--split", str( split_path ), "--rate", "0.05" ] ) == 0
    out = capsys.readouterr().out
    assert "rows: fit 704, check 542" in out and 704 + 542 == len( rows )
    assert "chosen on the fit half" in out and "'members': 9" in out and "'members': 7" in out        # sixteen members, nine on the fit half


def test_the_fit_script_refuses_the_same_file_when_a_member_is_missing_from_the_split( tmp_path ):
    rows_path, split_path, rows = written( tmp_path )
    split = json.loads( split_path.read_text( encoding="utf-8" ) )
    gone  = rows[ 0 ][ "member" ]
    for half in ( "fit", "check" ):
        for g in split[ half ]: g[ "members" ] = [ m for m in g[ "members" ] if m != gone ]
    split_path.write_text( json.dumps( split ), encoding="utf-8" )
    with pytest.raises( ValueError, match="is not in the split" ):
        fit.main( [ "--rows", str( rows_path ), "--split", str( split_path ), "--rate", "0.05" ] )
