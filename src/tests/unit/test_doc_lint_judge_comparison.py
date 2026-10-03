"""
judge_comparison: per-judge, per-pair-type figures rebuilt from a finished ledger, with no model call.

The ledger under test is written by the real harness runner, driven by the harness tests' fake model
(see test_doc_lint_harness.py): the extractor quotes the old text's lines and the judge calls a claim
present when its words are in the new text or the design doc. Each pair's expected verdict is therefore
fixed by its text, whatever the code under test does.
"""

import asyncio
import json
import os
import shutil

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import harness_report as hr
from cosa.repo.doc_lint import harness_report as hr2
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import jev_judge
from cosa.repo.doc_lint import judge_comparison as jc
from cosa.repo.doc_lint import labelled_pairs as lp
from test_doc_lint_harness import FakeModel, L1, L2, L3, OLD
from test_doc_lint_jev import ENV, haystack_noul, reply
from test_doc_lint_rule_mutations import _run

EXT, ESC, WRI = "ext-m", "esc-m", "writer-m"
HAIKU, SONNET, JEV = "hk-m", "so-m", "jev-m"

#  id, new text, linked_doc, seeded span in old, kind, injection
ROWS = [
    ( "p0", "\n".join( [ L2, L3 ] ),     "",       L1,   "delete",     False ),
    ( "p1", "\n".join( [ L1, L3 ] ),     "",       L2,   "delete",     True ),
    ( "p2", "\n".join( [ L1, L2 ] ),     "",       L3,   "weaken",     False ),
    ( "p3", "\n".join( [ L1, L2 ] ),     L3,       None, "relocate",   False ),
    ( "p4", OLD,                         "",       None, "paraphrase", False ),
    ( "p5", "\n".join( [ L1, L2, "Nothing else is promised." ] ), "", None, "paraphrase", True ),
]


def write_set( tmp_path, name="dev" ):
    base = tmp_path / name
    base.mkdir( exist_ok=True )
    pairs = [ { "id": i, "old": OLD, "new": new, "linked_doc": doc } for i, new, doc, _, _, _ in ROWS ]
    keys  = [ { "id": i, "seeded_positive": span is not None, "x_span_in_old": span or "", "kind": kind, "injection": inj } for i, _, _, span, kind, inj in ROWS ]
    ( base / "pairs.jsonl" ).write_text( "\n".join( json.dumps( p ) for p in pairs ) + "\n" )
    ( base / "keys.jsonl" ).write_text( "\n".join( json.dumps( k ) for k in keys ) + "\n" )
    return str( base / "pairs.jsonl" ), str( base / "keys.jsonl" )


def configs( haiku=True, sonnet=True ):
    out = {}
    if haiku:  out[ "haiku" ]  = ( hn.HarnessConfig( EXT, HAIKU,  ESC, WRI, 2, 3 ), None )
    if sonnet: out[ "sonnet" ] = ( hn.HarnessConfig( EXT, SONNET, ESC, WRI, 2, 3 ), None )
    return out


@pytest.fixture
def run( tmp_path ):
    """A finished ledger for the Haiku and Sonnet judges over ROWS, plus the pairs and keys."""
    pairs_path, keys_path = write_set( tmp_path )
    pairs  = lp.load_pairs( pairs_path, keys_path )
    ledger = hn.Ledger( str( tmp_path / "ledger.jsonl" ) )
    for config, _ in configs().values():
        asyncio.run( hn.run_all( pairs, config, ledger, query_fn=FakeModel() ) )
    return { "pairs_path": pairs_path, "keys_path": keys_path, "pairs": pairs, "keys": jc.key_rows( keys_path ), "ledger": ledger, "tmp": tmp_path }


# ---- keys and groups -------------------------------------------------------------------------

def test_key_rows_keep_the_three_grouping_fields_and_refuse_a_malformed_key( tmp_path ):
    _, keys_path = write_set( tmp_path )
    assert jc.key_rows( keys_path )[ "p1" ] == { "kind": "delete", "seeded_positive": True, "injection": True }
    rows = [ json.loads( l ) for l in open( keys_path ) ]
    for bad, text in ( ( { **rows[ 0 ], "kind": "rewrite" }, "unknown kind" ), ( { **rows[ 0 ], "injection": "no" }, "must be true or false" ),
                       ( { **rows[ 0 ], "seeded_positive": 1 }, "must be true or false" ), ( { k: v for k, v in rows[ 0 ].items() if k != "kind" }, "'kind' is missing" ) ):
        path = tmp_path / "bad.jsonl"
        path.write_text( json.dumps( bad ) + "\n" )
        with pytest.raises( ValueError, match=text ): jc.key_rows( str( path ) )


def test_a_key_whose_kind_and_seeded_positive_disagree_is_refused_so_a_group_never_mixes_error_types( tmp_path ):
    _, keys_path = write_set( tmp_path )
    rows = [ json.loads( l ) for l in open( keys_path ) ]
    for kind, seeded in ( ( "paraphrase", True ), ( "relocate", True ), ( "delete", False ), ( "weaken", False ) ):
        path = tmp_path / "mixed.jsonl"
        path.write_text( json.dumps( { **rows[ 0 ], "kind": kind, "seeded_positive": seeded } ) + "\n" )
        with pytest.raises( ValueError, match="error type is undefined" ): jc.key_rows( str( path ) )
    for kind, seeded in ( ( "paraphrase", False ), ( "relocate", False ), ( "delete", True ), ( "weaken", True ) ):
        path = tmp_path / "ok.jsonl"
        path.write_text( json.dumps( { **rows[ 0 ], "kind": kind, "seeded_positive": seeded } ) + "\n" )
        assert jc.key_rows( str( path ) )[ rows[ 0 ][ "id" ] ][ "kind" ] == kind


def test_a_group_that_mixes_seeded_and_unseeded_pairs_is_refused_whatever_order_they_arrive_in():
    keys  = { "a": { "kind": "delete", "seeded_positive": True, "injection": False }, "b": { "kind": "delete", "seeded_positive": True, "injection": False } }
    empty = { "claims": [], "flags": [], "flag_words": [], "discards": [], "parse_failed": False, "retry_calls": 0, "runs": [] }
    seeded, unseeded = { "id": "a", "seed_span": [ 0, 3 ], "lists": [ empty ] }, { "id": "b", "seed_span": None, "lists": [ empty ] }
    for order in ( [ seeded, unseeded ], [ unseeded, seeded ] ):
        with pytest.raises( ValueError, match="mixes pairs" ): jc.group_rows( order, keys, 1 )


def test_an_injection_pair_is_in_its_kind_row_and_in_the_injection_row_that_follows_seeded_positive():
    assert jc.groups_of( { "kind": "delete", "seeded_positive": True, "injection": False } ) == [ "delete" ]
    assert jc.groups_of( { "kind": "delete", "seeded_positive": True, "injection": True } ) == [ "delete", "injection (removed claim)" ]
    assert jc.groups_of( { "kind": "paraphrase", "seeded_positive": False, "injection": True } ) == [ "paraphrase", "injection (kept claim)" ]


# ---- rebuilding and counting -----------------------------------------------------------------

def test_wrong_on_is_a_miss_for_a_seeded_pair_and_a_flag_for_an_unseeded_one( run ):
    results, _, _ = jc.rebuild( run[ "pairs" ], configs()[ "haiku" ][ 0 ], run[ "ledger" ] )
    by_id      = { r[ "id" ]: r for r in results }
    assert [ jc.wrong_on( by_id[ i ], 0 ) for i in ( "p0", "p1", "p2" ) ] == [ False, False, False ], "every removal is caught"
    assert [ jc.wrong_on( by_id[ i ], 0 ) for i in ( "p3", "p4", "p5" ) ] == [ False, False, True ], "only the pair that lost a claim with no seed is a false alarm"


def test_group_rows_count_wrong_verdicts_per_group_on_the_worse_list( run ):
    results, _, _ = jc.rebuild( run[ "pairs" ], configs()[ "haiku" ][ 0 ], run[ "ledger" ] )
    rows       = { r[ "group" ]: r for r in jc.group_rows( results, run[ "keys" ], 2 ) }
    assert list( rows ) == [ "delete", "weaken", "relocate", "paraphrase", "injection (removed claim)", "injection (kept claim)" ]
    assert ( rows[ "delete" ][ "n" ], rows[ "delete" ][ "wrong" ], rows[ "delete" ][ "expected" ] ) == ( 2, 0, "flagged" )
    assert ( rows[ "paraphrase" ][ "n" ], rows[ "paraphrase" ][ "wrong" ], rows[ "paraphrase" ][ "expected" ] ) == ( 2, 1, "not flagged" )
    assert ( rows[ "injection (removed claim)" ][ "n" ], rows[ "injection (kept claim)" ][ "wrong" ] ) == ( 1, 1 )
    assert rows[ "paraphrase" ][ "per_list" ] == [ 1, 1 ] and rows[ "paraphrase" ][ "rate" ] == 0.5


def test_a_removed_claim_group_reports_the_one_sided_upper_bound_and_a_kept_claim_group_the_interval_upper_end( run ):
    results, _, _ = jc.rebuild( run[ "pairs" ], configs()[ "haiku" ][ 0 ], run[ "ledger" ] )
    rows       = { r[ "group" ]: r for r in jc.group_rows( results, run[ "keys" ], 2 ) }
    assert rows[ "delete" ][ "bound" ] == pytest.approx( hr.upper_bound( 0, 2 ) ) and rows[ "delete" ][ "bound" ] == pytest.approx( 0.7764, abs=1e-4 )
    assert rows[ "paraphrase" ][ "bound" ] == pytest.approx( hr.interval( 1, 2 )[ 1 ] ) and rows[ "paraphrase" ][ "bound" ] == pytest.approx( 0.9874, abs=1e-4 )


def test_the_worse_extractor_list_is_the_one_reported_and_a_tie_names_the_lower_slot():
    seeded = { "id": "a", "seed_span": [ 0, 3 ], "lists": [ { "claims": [], "flags": [], "flag_words": [], "discards": [], "parse_failed": False, "retry_calls": 0, "runs": [] }, { "claims": [], "flags": [], "flag_words": [], "discards": [], "parse_failed": False, "retry_calls": 0, "runs": [] } ] }
    keys   = { "a": { "kind": "delete", "seeded_positive": True, "injection": False } }
    assert jc.group_rows( [ seeded ], keys, 2 )[ 0 ][ "worst_list" ] == 0
    assert jc.group_rows( [ seeded ], keys, 2 )[ 0 ][ "per_list" ] == [ 1, 1 ]
    only_second = { **seeded, "lists": [ { "claims": [ { "start": 0, "end": 3, "text": "x", "quote": "x" } ], "flags": [], "flag_words": [], "discards": [], "parse_failed": False, "retry_calls": 0, "runs": [ [ { "verdict": "absent" } ] ] }, { "claims": [], "flags": [], "flag_words": [], "discards": [], "parse_failed": False, "retry_calls": 0, "runs": [] } ] }
    assert jc.group_rows( [ only_second ], keys, 2 )[ 0 ][ "per_list" ] == [ 0, 1 ] and jc.group_rows( [ only_second ], keys, 2 )[ 0 ][ "worst_list" ] == 1


def test_a_result_without_a_key_is_refused( run ):
    results, _, _ = jc.rebuild( run[ "pairs" ], configs()[ "haiku" ][ 0 ], run[ "ledger" ] )
    with pytest.raises( ValueError, match="p0 has no key" ): jc.group_rows( results, { k: v for k, v in run[ "keys" ].items() if k != "p0" }, 2 )


def test_call_counts_split_extractor_calls_from_each_judges_calls( run ):
    counts = jc.call_counts( run[ "ledger" ], { "haiku": f"{HAIKU}+{ESC}", "sonnet": f"{SONNET}+{ESC}", "jev": "jev-m@0.1-0.9+esc-m" }, run[ "pairs" ] )
    assert counts == { "extract": 12, "judge": { "haiku": 36, "sonnet": 36, "jev": 0 } }, "6 pairs x 2 lists extracted once and shared; 6 x 2 x 3 judge runs each"
    assert jc.call_counts( run[ "ledger" ], { "bare": SONNET }, run[ "pairs" ] )[ "judge" ] == { "bare": 0 }, "the key carries the whole judge+escalation string, so a bare judge id matches nothing"


def test_rebuild_makes_no_model_call_and_a_missing_row_raises_instead_of_calling_one( run ):
    results, report, _ = jc.rebuild( run[ "pairs" ], configs()[ "haiku" ][ 0 ], run[ "ledger" ] )
    assert len( results ) == 6 and report[ "pairs" ] == 6
    with pytest.raises( jc.LedgerIncomplete, match="ledger is incomplete" ):
        jc.rebuild( run[ "pairs" ], hn.HarnessConfig( EXT, "other-judge", ESC, WRI, 2, 3 ), run[ "ledger" ] )


def test_a_missing_row_is_found_anywhere_in_an_error_chain_and_other_errors_pass_through( run ):
    missing = jc.LedgerIncomplete( "x" )
    wrapped = ValueError( "outer" )
    wrapped.__cause__ = missing
    context = ValueError( "outer" )
    context.__context__ = missing
    assert jc.caused_by_missing_row( missing ) and jc.caused_by_missing_row( wrapped ) and jc.caused_by_missing_row( context )
    assert not jc.caused_by_missing_row( ValueError( "plain" ) )
    with pytest.raises( ValueError, match="must not grade its own rewrite" ):
        jc.rebuild( run[ "pairs" ], hn.HarnessConfig( EXT, WRI, ESC, WRI, 2, 3 ), run[ "ledger" ] )


def test_each_judges_seconds_are_copied_from_the_elapsed_file_and_are_none_when_it_has_no_entry( run ):
    out = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], configs(), elapsed={ "haiku": 12.5 } )
    assert out[ "judges" ][ "haiku" ][ "seconds" ] == 12.5 and out[ "judges" ][ "sonnet" ][ "seconds" ] is None
    assert jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], configs() )[ "judges" ][ "haiku" ][ "seconds" ] is None


def test_build_comparison_marks_an_incomplete_judge_and_never_gives_it_figures( run ):
    judges = { **configs( sonnet=False ), "other": ( hn.HarnessConfig( EXT, "other-judge", ESC, WRI, 2, 3 ), None ) }
    out    = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], judges )
    assert set( out[ "judges" ][ "other" ] ) == { "incomplete" } and "ledger is incomplete" in out[ "judges" ][ "other" ][ "incomplete" ]
    assert out[ "judges" ][ "haiku" ][ "headline" ][ "pairs" ] == 6 and out[ "split" ] == "dev" and out[ "pairs" ] == 6
    assert out[ "calls" ][ "judge" ] == { "haiku": 36, "other": 0 }


def test_a_ledger_that_also_holds_another_splits_calls_counts_only_this_splits_pairs( run ):
    foreign = dict( run[ "pairs" ][ 0 ], id="gate-1", old=OLD + " (gate pair)" )
    asyncio.run( hn.run_all( [ foreign ], configs()[ "haiku" ][ 0 ], run[ "ledger" ], query_fn=FakeModel() ) )
    models = { "haiku": f"{HAIKU}+{ESC}" }
    assert jc.call_counts( run[ "ledger" ], models, run[ "pairs" ] ) == { "extract": 12, "judge": { "haiku": 36 } }
    assert jc.call_counts( run[ "ledger" ], models, [ foreign ] ) == { "extract": 2, "judge": { "haiku": 6 } }
    assert jc.call_counts( run[ "ledger" ], models, run[ "pairs" ] + [ foreign ] ) == { "extract": 14, "judge": { "haiku": 42 } }


def test_a_ledger_made_with_more_judge_runs_than_the_configuration_says_is_incomplete_not_a_subset_passed_as_whole( run ):
    more = ( hn.HarnessConfig( EXT, HAIKU, ESC, WRI, 2, 5 ), None )
    asyncio.run( hn.run_all( run[ "pairs" ], more[ 0 ], run[ "ledger" ], query_fn=FakeModel() ) )
    out = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], { "haiku": configs()[ "haiku" ], "sonnet": configs()[ "sonnet" ] } )
    assert "incomplete" in out[ "judges" ][ "haiku" ] and "60 judge calls" in out[ "judges" ][ "haiku" ][ "incomplete" ] and "make 12 and 36" in out[ "judges" ][ "haiku" ][ "incomplete" ]
    assert "incomplete" not in out[ "judges" ][ "sonnet" ], "the other judge's rows are untouched"
    assert jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], { "haiku": more } )[ "judges" ][ "haiku" ][ "headline" ][ "pairs" ] == 6


def test_two_pairs_with_identical_texts_share_their_ledger_rows_and_are_not_reported_as_missing_ones( run ):
    twin   = dict( run[ "pairs" ][ 0 ], id="twin" )
    pairs  = [ run[ "pairs" ][ 0 ], twin ]
    keys   = { **run[ "keys" ], "twin": run[ "keys" ][ "p0" ] }
    out    = jc.build_comparison( "dev", pairs, keys, run[ "ledger" ], { "haiku": configs()[ "haiku" ] } )
    assert "incomplete" not in out[ "judges" ][ "haiku" ], out[ "judges" ][ "haiku" ]
    assert out[ "calls" ] == { "extract": 2, "judge": { "haiku": 6 } }, "one distinct text pair x 2 lists, and x 3 runs; the twin adds no rows"


def test_the_configuration_is_in_the_json_and_in_the_markdown_header( run ):
    out  = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], configs() )
    assert out[ "config" ] == { "haiku": { "extractor_lists": 2, "judge_runs": 3 }, "sonnet": { "extractor_lists": 2, "judge_runs": 3 } }
    assert "Configuration: haiku 2 extractor lists x 3 judge runs; sonnet 2 extractor lists x 3 judge runs." in jc.render_markdown( out )


def test_the_command_line_takes_the_run_configuration_and_defaults_to_two_lists_and_three_runs( run, tmp_path ):
    more = hn.HarnessConfig( EXT, HAIKU, ESC, WRI, 2, 5 )
    asyncio.run( hn.run_all( run[ "pairs" ], more, run[ "ledger" ], query_fn=FakeModel() ) )
    assert jc.main( argv( run, tmp_path, "--claude-judge-runs", "5", "--extractor-lists", "2", "--jev-judge-runs", "1" ) ) == 0
    data = json.loads( ( tmp_path / "c.json" ).read_text() )
    assert data[ "config" ][ "haiku" ] == { "extractor_lists": 2, "judge_runs": 5 } and data[ "config" ][ "jev" ] == { "extractor_lists": 2, "judge_runs": 1 }
    assert "incomplete" not in data[ "judges" ][ "haiku" ] and "incomplete" in data[ "judges" ][ "sonnet" ], "the same ledger read as 3 runs is not whole for sonnet"


def test_a_judge_with_no_seeded_pairs_shows_n_a_and_gets_no_chart_point( tmp_path ):
    unseeded = [ r for r in ROWS if r[ 3 ] is None ]
    pairs_path = tmp_path / "pairs.jsonl"
    keys_path  = tmp_path / "keys.jsonl"
    pairs_path.write_text( "\n".join( json.dumps( { "id": i, "old": OLD, "new": new, "linked_doc": doc } ) for i, new, doc, _, _, _ in unseeded ) + "\n" )
    keys_path.write_text( "\n".join( json.dumps( { "id": i, "seeded_positive": False, "x_span_in_old": "", "kind": kind, "injection": inj } ) for i, _, _, _, kind, inj in unseeded ) + "\n" )
    pairs  = lp.load_pairs( str( pairs_path ), str( keys_path ) )
    ledger = hn.Ledger( str( tmp_path / "l.jsonl" ) )
    asyncio.run( hn.run_all( pairs, configs()[ "haiku" ][ 0 ], ledger, query_fn=FakeModel() ) )
    text = jc.render_markdown( jc.build_comparison( "dev", pairs, jc.key_rows( str( keys_path ) ), ledger, { "haiku": configs()[ "haiku" ] } ) )
    assert "| haiku | 0 | 0 | n/a | n/a | 3 | 1 | 33.3% | 90.6% |" in text
    assert "No chart point for haiku: no seeded pairs." in text and "False-pass rate and 95% upper bound" not in text and "False-alarm rate and 95% upper end" in text


def test_a_judge_with_no_unseeded_pairs_shows_n_a_for_false_alarms_and_gets_no_alarm_chart_point( tmp_path ):
    seeded = [ r for r in ROWS if r[ 3 ] is not None ]
    pairs_path = tmp_path / "pairs.jsonl"
    keys_path  = tmp_path / "keys.jsonl"
    pairs_path.write_text( "\n".join( json.dumps( { "id": i, "old": OLD, "new": new, "linked_doc": doc } ) for i, new, doc, _, _, _ in seeded ) + "\n" )
    keys_path.write_text( "\n".join( json.dumps( { "id": i, "seeded_positive": True, "x_span_in_old": span, "kind": kind, "injection": inj } ) for i, _, _, span, kind, inj in seeded ) + "\n" )
    pairs  = lp.load_pairs( str( pairs_path ), str( keys_path ) )
    ledger = hn.Ledger( str( tmp_path / "l.jsonl" ) )
    asyncio.run( hn.run_all( pairs, configs()[ "haiku" ][ 0 ], ledger, query_fn=FakeModel() ) )
    text = jc.render_markdown( jc.build_comparison( "dev", pairs, jc.key_rows( str( keys_path ) ), ledger, { "haiku": configs()[ "haiku" ] } ) )
    assert "| haiku | 3 | 0 | 0.0% | 63.2% | 0 | 0 | n/a | n/a |" in text
    assert "No chart point for haiku: no unseeded pairs." in text and "False-alarm rate and 95% upper end" not in text and "False-pass rate and 95% upper bound" in text


# ---- rendering -------------------------------------------------------------------------------

def test_formatting_helpers():
    assert jc.pct( None ) == "n/a" and jc.pct( 0.0 ) == "0.0%" and jc.pct( 0.5 ) == "50.0%" and jc.pct( 0.12345 ) == "12.3%"
    assert jc.axis_top( [] ) == 0.05 and jc.axis_top( [ 0.0 ] ) == 0.05 and jc.axis_top( [ 0.06 ] ) == pytest.approx( 0.10 ) and jc.axis_top( [ 0.05 ] ) == pytest.approx( 0.05 )
    lists = [ { "slot": 0, "misses": 1 }, { "slot": 1, "misses": 3 }, { "slot": 2, "misses": 3 } ]
    assert jc.worst_list( { "lists": lists }, "misses" )[ "slot" ] == 1, "a tie names the lower slot"


def test_the_markdown_carries_each_figure_from_the_comparison_dict( run ):
    out  = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], configs(), elapsed={ "haiku": 90, "sonnet": 120 } )
    text = jc.render_markdown( out )
    assert text.startswith( "### dev split (6 pairs)" )
    assert "| haiku | 3 | 0 | 0.0% | 63.2% | 3 | 1 | 33.3% | 90.6% |" in text, "3 seeded pairs, none missed; 3 unseeded, one flagged"
    assert "| haiku | paraphrase | not flagged | 2 | 1 | 50.0% | 98.7% | 0 |" in text
    assert "Extractor calls (shared by every judge): 12." in text
    assert "| haiku | 36 | 0 | 0 | n/a | 90 |" in text and "| sonnet | 36 | 0 | 0 | n/a | 120 |" in text
    assert text.count( "```mermaid" ) == 5


def test_every_chart_number_is_a_number_from_the_comparison( run ):
    out    = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], configs() )
    text   = jc.render_markdown( out )
    charts = [ block.split( "```" )[ 0 ] for block in text.split( "```mermaid\n" )[ 1 : ] ]
    assert len( charts ) == 5
    first = charts[ 0 ]
    assert 'title "False-pass rate and 95% upper bound, dev split"' in first and 'x-axis ["haiku", "sonnet"]' in first
    assert "bar [0.0000, 0.0000]" in first and "line [0.6316, 0.6316]" in first, "rate 0 of 3, bound 63.2%, same for both judges"
    assert "bar [0.3333, 0.3333]" in charts[ 1 ] and "line [0.9057, 0.9057]" in charts[ 1 ]
    assert 'x-axis ["delete", "weaken", "injection (removed claim)"]' in charts[ 2 ] and charts[ 2 ].count( "    line [" ) == 2
    assert 'x-axis ["relocate", "paraphrase", "injection (kept claim)"]' in charts[ 3 ] and "line [0.0000, 0.5000, 1.0000]" in charts[ 3 ]
    assert 'y-axis "calls" 0 --> 36' in charts[ 4 ] and "bar [36, 36]" in charts[ 4 ]
    assert 'x-axis ["haiku", "sonnet"]' in charts[ 4 ], "the calls chart quotes its labels like the others"


def test_a_comparison_with_an_incomplete_judge_says_so_and_draws_only_the_complete_ones( run ):
    judges = { **configs( sonnet=False ), "other": ( hn.HarnessConfig( EXT, "other-judge", ESC, WRI, 2, 3 ), None ) }
    text   = jc.render_markdown( jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], run[ "ledger" ], judges ) )
    assert "**other: incomplete.**" in text and "| other |" not in text and 'x-axis ["haiku"]' in text


def test_a_comparison_with_no_complete_judge_has_no_charts_and_no_table_rows():
    text = jc.render_markdown( { "split": "gate", "pairs": 0, "config": { "jev": { "extractor_lists": 2, "judge_runs": 1 } }, "judges": { "jev": { "incomplete": "no rows" } }, "calls": { "extract": 0, "judge": { "jev": 0 } } } )
    assert "**jev: incomplete.** no rows" in text and "```mermaid" not in text and "| jev |" not in text


def test_a_group_chart_is_left_out_when_the_keys_have_no_pair_of_its_kinds( run ):
    only_delete = [ r for r in run[ "pairs" ] if r[ "id" ] == "p0" ]
    out         = jc.build_comparison( "dev", only_delete, run[ "keys" ], run[ "ledger" ], configs( sonnet=False ) )
    text        = jc.render_markdown( out )
    assert "False-pass rate by pair type" in text and "False-alarm rate by pair type" not in text


# ---- a ledger written by a real model ----------------------------------------------------------

FIXTURES = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "judge_comparison" )


def test_a_ledger_from_a_real_run_rebuilds_to_the_figures_the_harness_reported_and_to_pinned_literals( monkeypatch ):
    # The fixture ledger was written by the extractor before row ed2f9b4e (version extractor-a3bde07306, entries
    # without discards or flags). Its keys carry that version, so the rebuild is pinned to it; the new extractor has another.
    monkeypatch.setattr( hn.claim_extractor, "PROMPT_VERSION", "extractor-a3bde07306" )
    pairs  = json.load( open( os.path.join( FIXTURES, "pairs.json" ) ) )
    keys   = json.load( open( os.path.join( FIXTURES, "keys.json" ) ) )[ "keys" ]
    report = json.load( open( os.path.join( FIXTURES, "harness-report.json" ) ) )
    ledger = hn.Ledger( os.path.join( FIXTURES, "ledger.jsonl" ) )
    for p in pairs: p[ "seed_span" ] = tuple( p[ "seed_span" ] ) if p.get( "seed_span" ) else None
    config = hn.HarnessConfig( "claude-sonnet-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "tracked-docstrings", 2, 3 )
    out    = jc.build_comparison( "dev", [ dict( p, design=None ) for p in pairs ], { k[ "id" ]: { f: k[ f ] for f in jc.KEY_FIELDS } for k in keys }, ledger, { "sonnet": ( config, None ) } )
    judge  = out[ "judges" ][ "sonnet" ]
    assert "incomplete" not in judge, judge
    # the committed report predates the ed2f9b4e fields; compare the figures it does carry
    assert [ { k: l[ k ] for k in r } for l, r in zip( judge[ "headline" ][ "lists" ], report[ "lists" ] ) ] == report[ "lists" ] and judge[ "headline" ][ "escalations" ] == report[ "escalations" ] == 2
    assert [ ( l[ "positives" ], l[ "misses" ], l[ "unseeded" ], l[ "false_alarms" ] ) for l in judge[ "headline" ][ "lists" ] ] == [ ( 3, 0, 3, 0 ), ( 3, 0, 3, 0 ) ]
    assert out[ "calls" ] == { "extract": 12, "judge": { "sonnet": 36 } }, "49 ledger lines: one binding record, 12 extractor calls, 36 judge calls"
    groups = { g[ "group" ]: ( g[ "n" ], g[ "wrong" ] ) for g in judge[ "groups" ] }
    assert groups == { "delete": ( 3, 0 ), "paraphrase": ( 3, 0 ) }
    assert "| sonnet | 3 | 0 | 0.0% | 63.2% | 3 | 0 | 0.0% | 70.8% | 97.8% | 66.7% |" in jc.render_markdown( out ), "the real judge agreed with itself on 97.8% of claims and only 66.7% of the seeded ones"


# ---- Jev: passes the harness never ledgered, and the report that must square with them ---------

def jev_outage_post( fail_p5 ):
    """A Jev post that answers from the request, and returns a 500 for the 'ten minutes' claim of the p5 pair when asked."""
    import json as _json
    def post( url, headers, body, timeout ):
        request = _json.loads( body )
        claim   = request[ "questions" ][ next( iter( request[ "questions" ] ) ) ][ "instructions" ].lower()
        if fail_p5 and "ten minutes" in claim and "nothing else is promised" in _json.dumps( request[ "state" ] ).lower(): return 500, "boom"
        return 200, reply( haystack_noul( body ), model=JEV )
    return post


def jev_run( run, tmp_path, fail_p5 ):
    """Run the real harness runner with a real JevBackend over a fake post; return its ledger, backend, config, results and report."""
    backend = jev_judge.JevBackend( JEV, 0.1, 0.9, ESC, post_fn=jev_outage_post( fail_p5 ), sleep_fn=lambda s: None, environ=ENV, allow_design_text=True )
    config  = hn.HarnessConfig( EXT, JEV, ESC, WRI, 2, 1 )
    path    = tmp_path / ( "jev-out.jsonl" if fail_p5 else "jev-ok.jsonl" )
    shutil.copy( run[ "ledger" ].path, path )
    ledger  = hn.Ledger( str( path ) )
    results = asyncio.run( hn.run_all( run[ "pairs" ], config, ledger, query_fn=FakeModel(), judge_backend=backend ) )
    return ledger, backend, config, results, hr2.build_report( results, config, judge_prompt_version=backend.prompt_version, jev_run=True )


def test_a_jev_run_with_every_claim_answered_rebuilds_complete_and_its_report_squares( run, tmp_path ):
    ledger, backend, config, _, report = jev_run( run, tmp_path, False )
    out = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], ledger, { "jev": ( config, backend ) }, reports={ "jev": report } )
    assert report[ "judge_unanswered" ] == 0 and "incomplete" not in out[ "judges" ][ "jev" ] and out[ "judges" ][ "jev" ][ "headline" ][ "judge_unanswered" ] == 0


def test_the_probe_answers_every_missing_claim_unanswered_so_a_rebuilt_report_counts_them( run, tmp_path ):
    ledger, backend, config, _, run_report = jev_run( run, tmp_path, True )
    _, rebuilt, missing = jc.rebuild( run[ "pairs" ], config, ledger, backend )
    assert missing == [ 3, 3 ] and rebuilt[ "judge_unanswered" ] == 6, "the probe's rows carry no noul, so each of the 6 claims in the 2 missing passes counts as unanswered"
    assert run_report[ "judge_unanswered" ] == 2, "the run itself had one unanswered claim in each of those passes"


def test_a_jev_outage_leaves_passes_out_of_the_ledger_and_the_reason_counts_them( run, tmp_path ):
    ledger, backend, config, _, report = jev_run( run, tmp_path, True )
    assert report[ "judge_unanswered" ] == 2, "one unanswered claim in each of p5's two lists"
    out = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], ledger, { "jev": ( config, backend ) }, reports={ "jev": report } )
    judge = out[ "judges" ][ "jev" ]
    assert judge[ "missing_passes" ] == 2 and judge[ "missing_claims" ] == 6, "2 passes of 3 claims; only 1 claim in each went unanswered"
    assert judge[ "incomplete" ].startswith( "2 judge passes (pair, list, run) holding 6 claims have no ledger row" )
    assert "judge_unanswered" not in judge and set( judge ) == { "incomplete", "missing_passes", "missing_claims" }
    without = jc.build_comparison( "dev", run[ "pairs" ], run[ "keys" ], ledger, { "jev": ( config, backend ) } )
    assert without[ "judges" ][ "jev" ][ "incomplete" ] == judge[ "incomplete" ], "no report: still incomplete, still counted"


@pytest.mark.parametrize( "missing,reported,ok", [
    ( [],        0, True ),  ( [],        3, False ), ( [ 3, 3 ], 0, False ),
    ( [ 3, 3 ], 1, False ),  ( [ 3, 3 ], 2, True ),  ( [ 3, 3 ], 3, True ),  ( [ 3, 3 ], 6, True ),  ( [ 3, 3 ], 7, False ),
    ( [ 1 ],    1, True ),   ( [ 1 ],    2, False ),
] )
def test_the_unanswered_count_must_sit_between_the_missing_passes_and_the_claims_in_them( missing, reported, ok ):
    if ok: assert jc.check_unanswered( "jev", missing, reported ) is None
    else:
        with pytest.raises( jc.ReportMismatch, match=f"lacks {len( missing )} judge passes holding {sum( missing )} claims, but the harness report says {reported} claims" ): jc.check_unanswered( "jev", missing, reported )


def test_a_report_that_is_not_from_this_run_is_refused_field_by_field( run, tmp_path ):
    _, backend, _, _, report = jev_run( run, tmp_path, False )
    report = dict( report, claude_cli="/x", claude_cli_version="1.0" )
    binding = "claude_cli=/x|version=1.0"
    report[ "pairs_sha" ] = "sha"
    args = ( "jev", report, "sha", backend.prompt_version, JEV, binding )
    assert jc.check_report_binds( *args ) is None
    for field, bad in ( ( "pairs_sha", "other" ), ):
        with pytest.raises( jc.ReportMismatch, match="pairs_sha is 'other' in the report" ): jc.check_report_binds( "jev", dict( report, **{ field: bad } ), "sha", backend.prompt_version, JEV, binding )
    with pytest.raises( jc.ReportMismatch, match="judge prompt version" ): jc.check_report_binds( "jev", dict( report, prompt_versions={ "judge": "jev-other", "extractor": "e" } ), "sha", backend.prompt_version, JEV, binding )
    with pytest.raises( jc.ReportMismatch, match="judge model" ): jc.check_report_binds( "jev", dict( report, models=dict( report[ "models" ], judge="jev-9" ) ), "sha", backend.prompt_version, JEV, binding )
    with pytest.raises( jc.ReportMismatch, match="claude binary is 'claude_cli=/x\\|version=2.0'" ): jc.check_report_binds( "jev", dict( report, claude_cli_version="2.0" ), "sha", backend.prompt_version, JEV, binding )
    with pytest.raises( jc.ReportMismatch, match="claude binary is 'claude_cli=/other\\|version=1.0'" ): jc.check_report_binds( "jev", dict( report, claude_cli="/other" ), "sha", backend.prompt_version, JEV, binding )
    assert jc.check_report_binds( "jev", dict( report, claude_cli_version="2.0" ), "sha", backend.prompt_version, JEV, None ) is None, "an unbound ledger has no binary to compare"


def _jev_main_run( run, tmp_path, fail_p5, report_edit=None ):
    ledger, backend, _, _, report = jev_run( run, tmp_path, fail_p5 )
    import hashlib
    report = dict( report, pairs_sha=hashlib.sha256( open( run[ "pairs_path" ], "rb" ).read() ).hexdigest() )
    if report_edit: report = report_edit( report )
    report_path = tmp_path / "jev-report.json"
    report_path.write_text( json.dumps( report ) )
    args = argv( run, tmp_path )
    args[ args.index( "--ledger" ) + 1 ] = ledger.path
    return args, str( report_path )


def test_the_command_line_squares_the_jev_report_with_the_missing_passes_and_still_writes_the_incomplete_figures( run, tmp_path ):
    args, report = _jev_main_run( run, tmp_path, True )
    assert jc.main( args + [ "--jev-report", report ] ) == 0
    data = json.loads( ( tmp_path / "c.json" ).read_text() )
    assert data[ "judges" ][ "jev" ][ "missing_passes" ] == 2 and "incomplete" not in data[ "judges" ][ "haiku" ]
    assert "**jev: incomplete.** 2 judge passes" in ( tmp_path / "c.md" ).read_text()


def test_the_command_line_refuses_a_jev_report_that_does_not_square_and_writes_nothing( run, tmp_path, capsys ):
    args, report = _jev_main_run( run, tmp_path, True, report_edit=lambda r: dict( r, judge_unanswered=0 ) )
    assert jc.main( args + [ "--jev-report", report ] ) == 4
    err = capsys.readouterr().err
    assert "lacks 2 judge passes holding 6 claims, but the harness report says 0 claims" in err
    assert not ( tmp_path / "c.json" ).exists() and not ( tmp_path / "c.md" ).exists()


def test_the_command_line_refuses_a_stale_jev_report_before_squaring_it( run, tmp_path, capsys ):
    args, report = _jev_main_run( run, tmp_path, True, report_edit=lambda r: dict( r, pairs_sha="0" * 64 ) )
    assert jc.main( args + [ "--jev-report", report ] ) == 4
    assert "not from this run: pairs_sha is" in capsys.readouterr().err and not ( tmp_path / "c.json" ).exists()


def test_the_stand_in_for_the_jev_request_refuses_any_call():
    with pytest.raises( jc.LedgerIncomplete, match="a Jev call was needed" ): jc.refuse_post( "url", {}, "{}", 1 )
    with pytest.raises( jc.LedgerIncomplete, match="a model call was needed" ): asyncio.run( jc.refuse_model_call( "p", None ).__anext__() )


def test_the_command_line_without_a_jev_report_still_counts_the_missing_passes( run, tmp_path ):
    args, _ = _jev_main_run( run, tmp_path, True )
    assert jc.main( args ) == 0
    assert json.loads( ( tmp_path / "c.json" ).read_text() )[ "judges" ][ "jev" ][ "missing_claims" ] == 6


# ---- the command line ------------------------------------------------------------------------

def argv( run, out_dir, *extra, split="dev" ):
    out = [ "--pairs", run[ "pairs_path" ], "--keys", run[ "keys_path" ], "--ledger", str( run[ "tmp" ] / "ledger.jsonl" ), "--split", split,
            "--out-json", str( out_dir / "c.json" ), "--out-md", str( out_dir / "c.md" ), "--t-lo", "0.1", "--t-hi", "0.9",
            "--extractor-model", EXT, "--escalation-model", ESC, "--writer-model", WRI, "--haiku-model", HAIKU, "--sonnet-model", SONNET, "--jev-model", JEV ]
    return out + list( extra )


def test_the_command_line_writes_json_and_markdown_and_marks_jev_incomplete( run, tmp_path, capsys ):
    elapsed = tmp_path / "elapsed.json"
    elapsed.write_text( json.dumps( { "haiku": 5 } ) )
    assert jc.main( argv( run, tmp_path, "--elapsed", str( elapsed ) ) ) == 0
    data = json.loads( ( tmp_path / "c.json" ).read_text() )
    assert [ "haiku: ok", "sonnet: ok", "jev: incomplete" ] == capsys.readouterr().out.split( "\n" )[ : 3 ]
    assert data[ "judges" ][ "haiku" ][ "seconds" ] == 5 and "incomplete" in data[ "judges" ][ "jev" ] and len( data[ "pairs_sha" ] ) == 64
    assert data[ "config" ] == { "haiku": { "extractor_lists": 2, "judge_runs": 3 }, "sonnet": { "extractor_lists": 2, "judge_runs": 3 }, "jev": { "extractor_lists": 2, "judge_runs": 1 } }, "defaults: 2 lists; 3 runs for Claude, 1 for Jev"
    assert "**jev: incomplete.**" in ( tmp_path / "c.md" ).read_text()


def test_the_command_line_merges_ledgers_in_the_order_given( run, tmp_path ):
    half = tmp_path / "half.jsonl"
    lines = ( run[ "tmp" ] / "ledger.jsonl" ).read_text().splitlines()
    half.write_text( "\n".join( lines[ : len( lines ) // 2 ] ) + "\n" )
    rest = tmp_path / "rest.jsonl"
    rest.write_text( "\n".join( lines[ len( lines ) // 2 : ] ) + "\n" )
    args = argv( run, tmp_path )
    args[ args.index( "--ledger" ) + 1 ] = str( half )
    args.insert( args.index( "--ledger" ) + 2, str( rest ) )
    assert jc.main( args ) == 0
    assert "incomplete" not in json.loads( ( tmp_path / "c.json" ).read_text() )[ "judges" ][ "haiku" ]


def _bound_copy( run, tmp_path, name, binding ):
    """Copy the run's ledger into a file that records the given binding (or none)."""
    path = tmp_path / name
    if binding is not None: hn.Ledger( str( path ), binding=binding )
    with open( path, "a", encoding="utf-8" ) as out: out.write( ( run[ "tmp" ] / "ledger.jsonl" ).read_text() )
    return str( path )


def test_ledgers_bound_to_the_same_binary_merge_and_the_binding_is_written_to_the_json( run, tmp_path ):
    one = _bound_copy( run, tmp_path, "a.jsonl", "claude_cli=/x|version=1.0" )
    two = _bound_copy( run, tmp_path, "b.jsonl", "claude_cli=/x|version=1.0" )
    args = argv( run, tmp_path )
    i    = args.index( "--ledger" )
    args[ i + 1 : i + 2 ] = [ one, two ]
    assert jc.main( args ) == 0
    assert json.loads( ( tmp_path / "c.json" ).read_text() )[ "claude_cli_binding" ] == "claude_cli=/x|version=1.0"


def test_ledgers_bound_to_different_binaries_are_refused_and_both_are_named( run, tmp_path, capsys ):
    one = _bound_copy( run, tmp_path, "a.jsonl", "claude_cli=/x|version=1.0" )
    two = _bound_copy( run, tmp_path, "b.jsonl", "claude_cli=/y|version=2.0" )
    args = argv( run, tmp_path )
    i    = args.index( "--ledger" )
    args[ i + 1 : i + 2 ] = [ one, two ]
    assert jc.main( args ) == 2
    err = capsys.readouterr().err
    assert "different Claude Code binaries" in err and "version=1.0" in err and "version=2.0" in err
    assert not ( tmp_path / "c.json" ).exists()


def test_an_unbound_ledger_among_bound_ones_is_a_mix_and_all_unbound_is_not( run, tmp_path ):
    bound   = _bound_copy( run, tmp_path, "a.jsonl", "claude_cli=/x|version=1.0" )
    unbound = _bound_copy( run, tmp_path, "b.jsonl", None )
    args    = argv( run, tmp_path )
    i       = args.index( "--ledger" )
    args[ i + 1 : i + 2 ] = [ bound, unbound ]
    assert jc.main( args ) == 2
    args[ i + 1 : i + 3 ] = [ unbound, _bound_copy( run, tmp_path, "c.jsonl", None ) ]
    assert jc.main( args ) == 0
    assert json.loads( ( tmp_path / "c.json" ).read_text() )[ "claude_cli_binding" ] is None


def test_the_command_line_refuses_a_gate_split_without_the_frozen_sha_or_with_a_wrong_one( run, tmp_path, capsys ):
    assert jc.main( argv( run, tmp_path, split="gate" ) ) == 3
    assert "gate split needs --frozen-pairs-sha" in capsys.readouterr().err
    assert jc.main( argv( run, tmp_path, "--frozen-pairs-sha", "0000", split="gate" ) ) == 3
    import hashlib
    sha = hashlib.sha256( open( run[ "pairs_path" ], "rb" ).read() ).hexdigest()
    assert jc.main( argv( run, tmp_path, "--frozen-pairs-sha", sha, split="gate" ) ) == 0
    assert not ( tmp_path / "gate" ).exists()


def test_the_dev_split_refuses_a_path_that_names_the_gate_split( run, tmp_path, capsys ):
    gate = tmp_path / "gate"
    gate.mkdir()
    for name in ( "pairs.jsonl", ):
        ( gate / name ).write_text( open( run[ "pairs_path" ] ).read() )
    args = argv( run, tmp_path )
    args[ args.index( "--pairs" ) + 1 ] = str( gate / "pairs.jsonl" )
    assert jc.main( args ) == 2
    assert "gate split" in capsys.readouterr().err


def test_the_command_line_refuses_a_malformed_key_and_a_judge_that_is_the_writer( run, tmp_path, capsys ):
    bad = tmp_path / "badkeys.jsonl"
    bad.write_text( open( run[ "keys_path" ] ).read().replace( '"kind": "delete"', '"kind": "rewrite"' ) )
    args = argv( run, tmp_path )
    args[ args.index( "--keys" ) + 1 ] = str( bad )
    assert jc.main( args ) == 2 and "unknown kind" in capsys.readouterr().err
    args = argv( run, tmp_path )
    args[ args.index( "--writer-model" ) + 1 ] = HAIKU
    assert jc.main( args ) == 2 and "must not grade its own rewrite" in capsys.readouterr().err


# ---- mutation: each edit to the module must redden a named test ------------------------------

NODE    = "src/tests/unit/test_doc_lint_judge_comparison.py::"
MUTANTS = [
    ( 'return not harness_report.caught( claim_list, tuple( result[ "seed_span" ] ) )', 'return harness_report.caught( claim_list, tuple( result[ "seed_span" ] ) )', "test_wrong_on_is_a_miss_for_a_seeded_pair_and_a_flag_for_an_unseeded_one" ),
    ( '"injection (removed claim)" if key[ "seeded_positive" ] else "injection (kept claim)"', '"injection (kept claim)" if key[ "seeded_positive" ] else "injection (removed claim)"', "test_an_injection_pair_is_in_its_kind_row_and_in_the_injection_row_that_follows_seeded_positive" ),
    ( 'if key[ "injection" ]: names.append(', 'if False: names.append(', "test_an_injection_pair_is_in_its_kind_row_and_in_the_injection_row_that_follows_seeded_positive" ),
    ( "worst    = max( range( slots ), key=lambda s: ( per_list[ s ], -s ) )", "worst    = min( range( slots ), key=lambda s: ( per_list[ s ], -s ) )", "test_the_worse_extractor_list_is_the_one_reported_and_a_tie_names_the_lower_slot" ),
    ( 'if row[ "seeded_positive" ] != ( row[ "kind" ] in REMOVING_KINDS ):', "if False:", "test_a_key_whose_kind_and_seeded_positive_disagree_is_refused_so_a_group_never_mixes_error_types" ),
    ( 'if any( ( r[ "seed_span" ] is not None ) != seeded for r in group ): raise', "if False: raise", "test_a_group_that_mixes_seeded_and_unseeded_pairs_is_refused_whatever_order_they_arrive_in" ),
    ( "if not group: continue", "pass", "test_a_group_chart_is_left_out_when_the_keys_have_no_pair_of_its_kinds" ),
    ( "bound    = harness_report.upper_bound( wrong, len( group ) ) if seeded else harness_report.interval( wrong, len( group ) )[ 1 ]", "bound    = harness_report.upper_bound( wrong, len( group ) )", "test_a_removed_claim_group_reports_the_one_sided_upper_bound_and_a_kept_claim_group_the_interval_upper_end" ),
    ( "if ( old_hash, new_hash ) not in mine: continue", "pass", "test_a_ledger_that_also_holds_another_splits_calls_counts_only_this_splits_pairs" ),
    ( "if \"incomplete\" in judge or ( out[ \"calls\" ][ \"extract\" ], out[ \"calls\" ][ \"judge\" ][ name ] ) == ( want_extract, want_judge ): continue", "continue", "test_a_ledger_made_with_more_judge_runs_than_the_configuration_says_is_incomplete_not_a_subset_passed_as_whole" ),
    ( "if m[ \"positives\" ]: passes[ n ] =", "passes[ n ] =", "test_a_judge_with_no_seeded_pairs_shows_n_a_and_gets_no_chart_point" ),
    ( "if a[ \"unseeded\" ]:  alarms[ n ] =", "alarms[ n ] =", "test_a_judge_with_no_unseeded_pairs_shows_n_a_for_false_alarms_and_gets_no_alarm_chart_point" ),
    ( 'f"    x-axis [{\', \'.join( f\'\\"{g}\\"\' for g in groups )}]"', 'f"    x-axis [{\', \'.join( g.replace( \' \', \'_\' ) for g in groups )}]"', "test_every_chart_number_is_a_number_from_the_comparison" ),
    ( 'if stage == "judge" and model == field:', 'if stage == "judge" and model.startswith( field ):', "test_call_counts_split_extractor_calls_from_each_judges_calls" ),
    ( "if len( bindings ) > 1:", "if False:", "test_ledgers_bound_to_different_binaries_are_refused_and_both_are_named" ),
    ( "bindings = { l.recorded for l in ledgers }", "bindings = { ledgers[ 0 ].recorded }", "test_an_unbound_ledger_among_bound_ones_is_a_mix_and_all_unbound_is_not" ),
    ( 'comparison[ "claude_cli_binding" ] = ledger.recorded', 'comparison[ "claude_cli_binding" ] = None', "test_ledgers_bound_to_the_same_binary_merge_and_the_binding_is_written_to_the_json" ),
    ( "distinct = len( pair_hashes( pairs ) )", "distinct = len( pairs )", "test_two_pairs_with_identical_texts_share_their_ledger_rows_and_are_not_reported_as_missing_ones" ),
    ( '\\"{n}\\"\' for n in names )}]", f\'    y-axis "calls"', '{n}\' for n in names )}]", f\'    y-axis "calls"', "test_every_chart_number_is_a_number_from_the_comparison" ),
    ( 'parser.add_argument( "--jev-judge-runs", type=int, default=1,', 'parser.add_argument( "--jev-judge-runs", type=int, default=2,', "test_the_command_line_writes_json_and_markdown_and_marks_jev_incomplete" ),
    ( "len( missing ) <= reported <= held", "len( missing ) < reported <= held", "test_the_unanswered_count_must_sit_between_the_missing_passes_and_the_claims_in_them" ),
    ( "len( missing ) <= reported <= held", "len( missing ) <= reported < held", "test_the_unanswered_count_must_sit_between_the_missing_passes_and_the_claims_in_them" ),
    ( "if seen[ field ] != want[ field ]: raise", "if False: raise", "test_a_report_that_is_not_from_this_run_is_refused_field_by_field" ),
    ( "    if binding is not None:\n        seen[", "    if False:\n        seen[", "test_a_report_that_is_not_from_this_run_is_refused_field_by_field" ),
    ( "if reports and name in reports: check_unanswered(", "if False: check_unanswered(", "test_the_command_line_refuses_a_jev_report_that_does_not_square_and_writes_nothing" ),
    ( "        if missing:\n", "        if False:\n", "test_a_jev_outage_leaves_passes_out_of_the_ledger_and_the_reason_counts_them" ),
    ( "self.missing.append( len( claims ) )", "self.missing.append( 1 )", "test_a_jev_outage_leaves_passes_out_of_the_ledger_and_the_reason_counts_them" ),
    ( "if reports: check_report_binds(", "if False: check_report_binds(", "test_the_command_line_refuses_a_stale_jev_report_before_squaring_it" ),
    ( "report.get( 'claude_cli' )", "'/x'", "test_a_report_that_is_not_from_this_run_is_refused_field_by_field" ),
    ( 'claim_judge.Judgement( c, "uncertain", False, "no ledger row for this pass", None )', 'claim_judge.Judgement( c, "uncertain", False, "no ledger row for this pass", 0.5 )', "test_the_probe_answers_every_missing_claim_unanswered_so_a_rebuilt_report_counts_them" ),
    ( 'if stage == "extract": out[ "extract" ] += 1', 'if stage == "extract": out[ "extract" ] += 2', "test_call_counts_split_extractor_calls_from_each_judges_calls" ),
    ( "if caused_by_missing_row( e ): raise LedgerIncomplete(", "if True: raise LedgerIncomplete(", "test_a_missing_row_is_found_anywhere_in_an_error_chain_and_other_errors_pass_through" ),
    ( "error = error.__cause__ or error.__context__", "error = error.__cause__", "test_a_missing_row_is_found_anywhere_in_an_error_chain_and_other_errors_pass_through" ),
    ( "pct( alarms[ n ][ 1 ] if n in alarms else None )", "pct( alarms[ n ][ 0 ] if n in alarms else None )", "test_the_markdown_carries_each_figure_from_the_comparison_dict" ),
    ( "return max( 0.05, math.ceil( max( values + [ 0.0 ] ) / 0.05 ) * 0.05 )", "return max( 0.05, math.floor( max( values + [ 0.0 ] ) / 0.05 ) * 0.05 )", "test_formatting_helpers" ),
    ( "if gate and args.frozen_pairs_sha != sha:", "if False:", "test_the_command_line_refuses_a_gate_split_without_the_frozen_sha_or_with_a_wrong_one" ),
    ( "for other in ledgers[ 1 : ]: ledger.entries.update( other.entries )", "for other in []: ledger.entries.update( other.entries )", "test_the_command_line_merges_ledgers_in_the_order_given" ),
    ( "except LedgerIncomplete as e:", "except ZeroDivisionError as e:", "test_build_comparison_marks_an_incomplete_judge_and_never_gives_it_figures" ),
]


@pytest.mark.parametrize( "old,new,test", MUTANTS, ids=[ f"{i}-{m[ 2 ][ 5 : 45 ]}" for i, m in enumerate( MUTANTS ) ] )
def test_each_mutant_reddens_its_named_test( old, new, test ):
    node = NODE + test
    rc, out = _run( node, { "module": "judge_comparison", "old": old, "new": old } )
    assert rc == 0, f"the test must pass unmutated:\n{out}"
    rc, out = _run( node, { "module": "judge_comparison", "old": old, "new": new } )
    assert rc == 1 and f"FAILED {node}" in out, f"the mutant survived {node}:\n{out[ -1500 : ]}"
