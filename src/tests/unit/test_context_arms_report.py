#!/usr/bin/env python3
"""
The context comparison report, on small hand-built replay runs.

Twelve asks, eight yes/no and four multiple choice. The correct flags are chosen so each discordant
count and each exact p value can be worked out by hand.
Q+A beats Q on eight yes/no asks. Q+O differs from Q on two asks, below the floor.
"""

import copy

import pytest

from cosa.research.preference_replay.context_arms_report import compare_arms, render_arm_report
from cosa.research.preference_replay.replay_loop import ENGINE_ARM

KINDS     = [ "yes_no" ] * 8 + [ "multiple_choice" ] * 4
IDS       = [ f"a{i}" for i in range( 12 ) ]
Q_FLAGS   = [ False ] * 8 + [ True, True, False, False ]
YES_FLAGS = [ True, True, True, False, False, False, False, False ] + [ False ] * 4
FLOOR     = 6


def _records( name, flags ):
    """
    Build the per-ask records of one arm.

    Requires:
        - flags holds one correct flag per ask

    Ensures:
        - returns records shaped as replay writes them, with the fields the report reads
    """
    return [ { "arm": name, "meta": { "notification_id": ask_id, "correct": flag, "response_type": kind } }
             for ask_id, kind, flag in zip( IDS, KINDS, flags ) ]


def _run( engine_flags, ids=None ):
    """
    Build one arm's replay run.

    Requires:
        - engine_flags holds one correct flag per ask

    Ensures:
        - returns a run with the engine records and an always-yes baseline
    """
    engine = _records( ENGINE_ARM, engine_flags )
    if ids is not None:
        for record, ask_id in zip( engine, ids ): record[ "meta" ][ "notification_id" ] = ask_id
    return { "records": { ENGINE_ARM: engine, "always_yes": _records( "always_yes", YES_FLAGS ) },
             "not_replayable": 0, "unrebuildable_cases": 0, "families": 3 }


def _runs():
    """
    Build three arm runs: Q, Q+A and Q+O.

    Ensures:
        - returns a dict of arm name to run
    """
    return { "Q": _run( Q_FLAGS ), "Q+A": _run( [ True ] * 8 + [ True, True, False, False ] ),
             "Q+O": _run( [ True, True ] + [ False ] * 6 + [ True, True, False, False ] ) }


def test_rows_follow_arm_order_and_count_each_type():
    runs = _runs()
    rows = compare_arms( { "Q+O": runs[ "Q+O" ], "Q": runs[ "Q" ], "Q+A": runs[ "Q+A" ] }, FLOOR )
    assert [ r[ "arm" ] for r in rows ] == [ "Q", "Q+A", "Q+O" ]
    q_row = rows[ 0 ]
    assert q_row[ "asks" ] == 12
    assert q_row[ "by_type" ] == { "multiple_choice": { "asks": 4, "correct": 2, "per_100": 50.0 }, "yes_no": { "asks": 8, "correct": 0, "per_100": 0.0 } }
    assert rows[ 1 ][ "by_type" ][ "yes_no" ] == { "asks": 8, "correct": 8, "per_100": 100.0 }


def test_q_has_no_pair_against_itself():
    assert compare_arms( _runs(), FLOOR )[ 0 ][ "vs_q" ] is None


def test_arm_against_q_counts_discordant_pairs_and_exact_p():
    pair = compare_arms( _runs(), FLOOR )[ 1 ][ "vs_q" ]
    assert ( pair[ "engine_only_right" ], pair[ "baseline_only_right" ] ) == ( 8, 0 )
    assert pair[ "mcnemar" ][ "p_value" ] == pytest.approx( 2 / 2 ** 8 )
    assert pair[ "verdict" ] == "engine better"


def test_arm_against_always_yes_counts_yes_no_asks_only():
    pair = compare_arms( _runs(), FLOOR )[ 1 ][ "vs_always_yes" ]
    assert pair[ "asks_replayed" ] == 8
    assert ( pair[ "engine_only_right" ], pair[ "baseline_only_right" ] ) == ( 5, 0 )
    assert pair[ "mcnemar" ][ "p_value" ] == pytest.approx( 2 / 2 ** 5 )


def test_arm_against_q_by_type_splits_the_pairs_and_q_has_none():
    rows = compare_arms( _runs(), FLOOR )
    assert rows[ 0 ][ "vs_q_by_type" ] == {}
    by_type = rows[ 1 ][ "vs_q_by_type" ]
    assert sorted( by_type ) == [ "multiple_choice", "yes_no" ]
    assert ( by_type[ "yes_no" ][ "engine_only_right" ], by_type[ "yes_no" ][ "baseline_only_right" ], by_type[ "yes_no" ][ "asks_replayed" ] ) == ( 8, 0, 8 )
    assert ( by_type[ "multiple_choice" ][ "engine_only_right" ], by_type[ "multiple_choice" ][ "baseline_only_right" ], by_type[ "multiple_choice" ][ "asks_replayed" ] ) == ( 0, 0, 4 )


def test_a_run_with_no_yes_no_ask_has_no_always_yes_pair():
    only_mc = { arm: dict( run, records={ k: [ r for r in v if r[ "meta" ][ "response_type" ] == "multiple_choice" ] for k, v in run[ "records" ].items() } )
                for arm, run in _runs().items() }
    rows = compare_arms( only_mc, FLOOR )
    assert all( row[ "vs_always_yes" ] is None for row in rows )
    assert sorted( rows[ 1 ][ "vs_q_by_type" ] ) == [ "multiple_choice" ]


def test_pairs_below_the_floor_are_not_decisive_rather_than_no_effect():
    pair = compare_arms( _runs(), FLOOR )[ 2 ][ "vs_q" ]
    assert ( pair[ "engine_only_right" ], pair[ "baseline_only_right" ] ) == ( 2, 0 )
    assert pair[ "floor_met" ] is False and pair[ "verdict" ] == "not decisive"


def test_comparison_changes_no_input():
    runs = _runs()
    before = copy.deepcopy( runs )
    compare_arms( runs, FLOOR )
    assert runs == before


def test_unknown_arm_is_refused():
    with pytest.raises( ValueError, match="unknown arms" ):
        compare_arms( dict( _runs(), **{ "Q+Z": _run( Q_FLAGS ) } ), FLOOR )


def test_missing_q_is_refused():
    runs = _runs()
    del runs[ "Q" ]
    with pytest.raises( ValueError, match="Q arm is required" ):
        compare_arms( runs, FLOOR )


def test_an_arm_that_replayed_other_asks_is_refused():
    runs = _runs()
    runs[ "Q+A" ] = _run( Q_FLAGS, ids=[ "x" ] + IDS[ 1: ] )
    with pytest.raises( ValueError, match="arm Q\\+A replayed different asks from Q" ):
        compare_arms( runs, FLOOR )


def test_an_arm_that_replayed_the_same_asks_in_another_order_is_refused():
    runs = _runs()
    swapped = [ IDS[ 1 ], IDS[ 0 ] ] + IDS[ 2: ]
    runs[ "Q+A" ] = _run( [ True ] * 8 + [ True, True, False, False ], ids=swapped )
    assert sorted( swapped ) == sorted( IDS )
    with pytest.raises( ValueError, match="arm Q\\+A replayed different asks from Q" ):
        compare_arms( runs, FLOOR )


COVERAGE = { "Q": { "asks": 12, "with_section": 12, "no_context": 0, "arm_input_absent": 0 },
             "Q+A": { "asks": 12, "with_section": 10, "no_context": 0, "arm_input_absent": 2 },
             "Q+O": { "asks": 12, "with_section": 7, "no_context": 0, "arm_input_absent": 5 } }
RECONCILIATIONS = [ { "title": "The 7 that differ", "detail": "the export lacks their earlier rows" },
                    { "title": "The 45 missing", "detail": "5 newer than the export, 40 unexplained" } ]
PROVENANCE = { "commit": "abc1234", "vectors": "side file, model m at revision r" }


def test_report_holds_provenance_coverage_reconciliations_and_one_row_per_arm():
    text = render_arm_report( compare_arms( _runs(), FLOOR ), COVERAGE, RECONCILIATIONS, PROVENANCE )
    assert "- commit: abc1234" in text and "- vectors: side file, model m at revision r" in text
    assert "| Q+A | 12 | 10 | 0 | 2 |" in text
    assert "- **The 7 that differ**: the export lacks their earlier rows" in text
    assert "- **The 45 missing**: 5 newer than the export, 40 unexplained" in text
    assert "| multiple_choice correct per 100 (asks) | yes_no correct per 100 (asks) |" in text
    assert "| Q | 50.0 (4) | 0.0 (8) | - | - | - | - |" in text
    assert "| Q+A | 50.0 (4) | 100.0 (8) | 8 | 0 | 0.0078 | engine better | 5 | 0 | 0.0625 | not decisive |" in text
    assert "| Q+A | yes_no | 8 | 0 | 0.0078 | engine better |" in text
    assert "| Q+A | multiple_choice | 0 | 0 | 1.0000 | not decisive |" in text
    assert "| arm | answer type | arm only | Q only | p | verdict |" in text


def test_report_headers_are_exact_lines():
    lines = render_arm_report( compare_arms( _runs(), FLOOR ), COVERAGE, RECONCILIATIONS, PROVENANCE ).split( "\n" )
    assert lines[ 0 ] == "# Context comparison report"
    assert "| arm | asks | with its section | no context | arm input empty |" in lines
    results = lines.index( "## Results" ) + 2
    assert lines[ results ] == ( "| arm | multiple_choice correct per 100 (asks) | yes_no correct per 100 (asks) | vs Q: arm only | vs Q: Q only | vs Q: p |"
                                 " vs Q: verdict | vs always-yes (yes/no only): arm only | yes only | p | verdict |" )
    assert lines[ results + 1 ] == "|---|" + "---|" * 10


def test_report_marks_a_type_an_arm_did_not_replay():
    runs = _runs()
    only_yes = { arm: dict( run, records={ k: [ r for r in v if r[ "meta" ][ "response_type" ] == "yes_no" ] for k, v in run[ "records" ].items() } )
                 for arm, run in runs.items() }
    rows = compare_arms( only_yes, FLOOR )
    rows[ 1 ][ "by_type" ].pop( "yes_no" )
    rows[ 1 ][ "by_type" ][ "multiple_choice" ] = { "asks": 1, "correct": 1, "per_100": 100.0 }
    text = render_arm_report( rows, COVERAGE, RECONCILIATIONS, PROVENANCE )
    assert "| Q+A | 100.0 (1) | - |" in text


def test_report_is_the_same_text_for_the_same_inputs():
    rows = compare_arms( _runs(), FLOOR )
    assert render_arm_report( rows, COVERAGE, RECONCILIATIONS, PROVENANCE ) == render_arm_report( rows, COVERAGE, RECONCILIATIONS, PROVENANCE )
