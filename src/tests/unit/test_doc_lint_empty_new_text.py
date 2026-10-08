"""
A pair with empty new text skips the judge, and the readers of its result know it.

Store id e19f2d9d-73af-4c5e-8628-76bfb7ef86ae. dart_pairs writes such a pair when a member's doc block
was removed and no comment was left. Six model runs would only learn what an empty text already says.
The runner records every claim absent with the reason `new text empty`, makes no judge call, and marks
the result. Four readers of a result could treat "absent, no judge run" like "absent, by the judge".
One test each pins them here, as ruled in io/tmp/2026.10.07-cheech-rio-empty-new-text-ruling.md.

Seams driven for real: harness_runner.run_all over the fake model of test_doc_lint_harness, then
harness_report.build_report, judge_comparison.build_comparison and group_rows over its results.
"""

import asyncio

import pytest

from cosa.repo.doc_lint import harness_report as hr
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import judge_comparison as jc
from test_doc_lint_harness import CONFIG, FakeModel, L1, L2, L3, OLD, pair

REASON = "new text empty"


def _results( pairs, tmp_path, model=None, config=CONFIG ):
    model = model or FakeModel()
    return asyncio.run( hn.run_all( pairs, config, hn.Ledger( str( tmp_path / "l" ) ), query_fn=model ) ), model


@pytest.mark.parametrize( "new", [ "", "  \n\t " ] )
def test_a_pair_with_an_empty_new_text_makes_no_judge_call_and_every_claim_is_absent_with_the_reason( tmp_path, new ):
    results, model = _results( [ pair( "p", new ) ], tmp_path )
    result = results[ 0 ]
    assert [ k for k, _ in model.calls ].count( "judge" ) == 0 and [ k for k, _ in model.calls ].count( "extract" ) == 2
    assert result[ "judge_skipped" ] == REASON
    for lst in result[ "lists" ]:
        assert [ c[ "text" ] for c in lst[ "claims" ] ] == [ L1, L2, L3 ]
        assert len( lst[ "runs" ] ) == CONFIG.judge_runs
        assert all( row[ "verdict" ] == "absent" and row[ "reason" ] == REASON and row[ "escalated" ] is False for run in lst[ "runs" ] for row in run )
    assert result[ "timing" ][ "stages" ].get( "judge" ) is None


def test_the_skipped_pair_leaves_no_judge_row_in_the_ledger_and_a_second_run_costs_nothing( tmp_path ):
    ledger = hn.Ledger( str( tmp_path / "l" ) )
    asyncio.run( hn.run_all( [ pair( "p", "" ) ], CONFIG, ledger, query_fn=FakeModel() ) )
    assert [ k for k in ledger.entries if k.startswith( "judge|" ) ] == []
    again = FakeModel()
    asyncio.run( hn.run_all( [ pair( "p", "" ) ], CONFIG, ledger, query_fn=again ) )
    assert again.calls == []


def test_control_a_pair_with_a_kept_new_text_is_still_judged_six_times_and_is_not_marked( tmp_path ):
    results, model = _results( [ pair( "p", OLD ) ], tmp_path )
    assert [ k for k, _ in model.calls ].count( "judge" ) == 6 and results[ 0 ][ "judge_skipped" ] is None
    assert { row[ "verdict" ] for lst in results[ 0 ][ "lists" ] for run in lst[ "runs" ] for row in run } == { "present" }


# ---- reader 1: judge_comparison's call-count check -------------------------------------------

def test_reader_one_a_ledger_with_a_skipped_pair_is_complete_not_short_of_judge_calls( tmp_path ):
    pairs  = [ pair( "kept", OLD ), pair( "empty", "" ) ]
    keys   = { i: { "seeded_positive": False, "kind": "paraphrase", "injection": False } for i in ( "kept", "empty" ) }
    ledger = hn.Ledger( str( tmp_path / "l" ) )
    judge  = ( hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m", 2, 3 ), None )
    asyncio.run( hn.run_all( pairs, judge[ 0 ], ledger, query_fn=FakeModel() ) )
    out = jc.build_comparison( "dev", pairs, keys, ledger, { "haiku": judge } )
    assert "incomplete" not in out[ "judges" ][ "haiku" ], out[ "judges" ][ "haiku" ]
    assert out[ "calls" ] == { "extract": 4, "judge": { "haiku": 6 } }


# ---- reader 2: agreement ----------------------------------------------------------------------

def test_reader_two_agreement_leaves_a_skipped_pair_out_and_says_how_many_and_that_the_version_moved( tmp_path ):
    both, _  = _results( [ pair( "kept", OLD ), pair( "empty", "" ) ], tmp_path )
    kept_only = hr.build_report( [ both[ 0 ] ], CONFIG )
    report    = hr.build_report( both, CONFIG )
    assert report[ "agreement_all" ][ "claims" ] == kept_only[ "agreement_all" ][ "claims" ] == 6
    assert report[ "agreement_all" ][ "excluded_pairs" ] == 1 and report[ "agreement_seeded" ][ "excluded_pairs" ] == 1
    assert kept_only[ "agreement_all" ][ "excluded_pairs" ] == 0
    assert report[ "judge_skipped_pairs" ] == 1 and report[ "harness_version" ] == hn.HARNESS_VERSION
    assert "not comparable" in report[ "agreement_note" ]


# ---- reader 3: the Jev unanswered count -------------------------------------------------------

def test_reader_three_a_skipped_pair_is_not_counted_as_unanswered_on_a_jev_run( tmp_path ):
    results, _ = _results( [ pair( "empty", "" ) ], tmp_path )
    assert hr.build_report( results, CONFIG, jev_run=True )[ "judge_unanswered" ] == 0


# ---- reader 4: false alarms and group rows ----------------------------------------------------

def test_reader_four_an_unseeded_skipped_pair_is_in_neither_the_false_alarms_nor_the_hits( tmp_path ):
    results, _ = _results( [ pair( "kept", OLD ), pair( "empty", "" ) ], tmp_path )
    report = hr.build_report( results, CONFIG )
    assert report[ "lists" ][ 0 ][ "unseeded" ] == 1 and report[ "lists" ][ 0 ][ "false_alarms" ] == 0
    assert report[ "lists" ][ 0 ][ "unseeded_new_text_empty" ] == 1 and report[ "unseeded_new_text_empty" ] == 1
    keys = { i: { "seeded_positive": False, "kind": "paraphrase", "injection": False } for i in ( "kept", "empty" ) }
    row  = { r[ "group" ]: r for r in jc.group_rows( results, keys, 1 ) }
    assert row[ "paraphrase" ][ "n" ] == 1 and row[ "paraphrase" ][ "wrong" ] == 0 and row[ "paraphrase" ][ "new_text_empty" ] == 1


def test_the_markdown_names_the_pairs_left_out_of_agreement_and_of_the_group_rows_and_still_draws( tmp_path ):
    pairs  = [ pair( "kept", OLD ), pair( "empty", "" ), pair( "only_empty", "" ) ]
    pairs[ 2 ][ "old" ] = OLD + "\nA second old line."
    keys   = { "kept": { "seeded_positive": False, "kind": "paraphrase", "injection": False },
               "empty": { "seeded_positive": False, "kind": "paraphrase", "injection": False },
               "only_empty": { "seeded_positive": False, "kind": "relocate", "injection": False } }
    ledger = hn.Ledger( str( tmp_path / "l" ) )
    judge  = ( hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m", 2, 3 ), None )
    asyncio.run( hn.run_all( pairs, judge[ 0 ], ledger, query_fn=FakeModel() ) )
    out  = jc.build_comparison( "dev", pairs, keys, ledger, { "haiku": judge } )
    text = jc.render_markdown( out )
    assert "(2 pairs left out)" in text and "New text empty, in neither n nor wrong: haiku relocate 1; haiku paraphrase 1." in text
    assert [ g for g in out[ "judges" ][ "haiku" ][ "groups" ] if g[ "group" ] == "relocate" ][ 0 ][ "rate" ] is None


def test_the_harness_version_is_two_and_the_agreement_note_names_it( tmp_path ):
    results, _ = _results( [ pair( "kept", OLD ) ], tmp_path )
    report     = hr.build_report( results, CONFIG )
    assert hn.HARNESS_VERSION == 2 and report[ "harness_version" ] == 2
    assert "from harness version 2," in report[ "agreement_note" ]
