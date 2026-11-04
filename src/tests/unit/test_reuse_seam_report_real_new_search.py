"""
Seam: the report reads the searches a live run wrote, the new question's among them.

The fixture holds the first ten members' searches, whole, from the run file of the live run
(`e2e-run.json`, sha256 recorded below). Both questions ran there, so "new" is the real new question, not the old ask
through a patched `NEW_ASK`. Nothing here sends a request.
"""
import collections
import json
import pathlib

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as run

FIXTURE    = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "e2e-run-searches-10-members-20261009.json"
SOURCE_SHA = "3225092674db41b3ca8144a1b8dadd653b1a7baec4b9cf446f976d9add4fdcaf"


def load():
    record = json.loads( FIXTURE.read_text( encoding="utf-8" ) )
    return record[ "source" ], record[ "searches" ]


def test_the_fixture_names_the_run_file_it_was_cut_from_and_holds_both_questions_for_ten_members():
    source, searches = load()
    assert source[ "sha256" ] == SOURCE_SHA and source[ "file" ] == "e2e-run.json"
    assert collections.Counter( s[ "question" ] for s in searches ) == { "old": 10, "new": 10 }
    assert len( { s[ "member" ] for s in searches } ) == 10 and all( s[ "status" ] == "complete" for s in searches )


def test_the_figures_of_the_real_new_question_are_the_counts_of_its_own_searches():
    _, searches = load()
    fig = e2e.figures( searches, [ "old", "new" ] )
    for q in ( "old", "new" ):
        mine = [ s for s in searches if s[ "question" ] == q ]
        assert fig[ q ][ "n_run" ] == 10 and fig[ q ][ "complete" ] == 10 and fig[ q ][ "incomplete" ] == 0 and fig[ q ][ "not_run" ] == 0
        for key in e2e.HEADLINE: assert fig[ q ][ key ][ "k" ] == sum( 1 for s in mine if s[ "read" ][ key ] ) and fig[ q ][ key ][ "n" ] == 10
        assert fig[ q ][ "verdicts" ] == dict( collections.Counter( s[ "read" ][ "verdict" ] for s in mine ) )
    assert fig[ "new" ][ "verdicts" ] == { "EXTEND": 8, "NEW": 2 }                                 # a verdict class only the new question gives
    assert [ fig[ "new" ][ k ][ "k" ] for k in ( "on_shortlist", "ranked_first", "top_ten" ) ] == [ 6, 5, 8 ]
    assert [ fig[ "old" ][ k ][ "k" ] for k in ( "on_shortlist", "ranked_first", "top_ten" ) ] == [ 7, 4, 8 ]


def test_the_report_prints_both_questions_and_the_paired_lines_from_the_real_searches():
    _, searches = load()
    lines = run.report_lines( searches, [ "old", "new" ] )
    text  = "\n".join( lines )
    assert lines[ 0 ] == run.FIRST_LINE
    assert "new: n run: 10 of 100, complete 10, incomplete 0, not run 0" in text
    assert "  twin ranked first (all run): 5 of 10, 95% interval" in text and f"verdict classes {dict( collections.Counter( s[ 'read' ][ 'verdict' ] for s in searches if s[ 'question' ] == 'new' ) )}" in text
    paired = e2e.paired( searches, "old", "new" )
    assert paired[ "ranked_first" ][ "only_new" ] + paired[ "ranked_first" ][ "both" ] == 5            # the new question's five, split by what old did
    assert sum( 1 for l in lines if l.startswith( "paired " ) ) == len( e2e.HEADLINE )
