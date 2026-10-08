"""
Tests of the analysis of the live packing measurement: the rules that read its result.

They are written before any result exists. Every number the plan fixes is pinned to its literal,
so a changed constant fails a named test. The arms are built by hand with known answers.
One test reads real answers that the live check wrote to the cache, through the real reader.
"""
import json
import math
import pathlib

import pytest

from lupin_mcp import reuse_stage1_analysis as an

REAL = pathlib.Path( __file__ ).parent / "fixtures" / "stage1-real-single-answers-sample.json"


def _probs( overlap, extend=0.0 ):
    """Ensures: returns a valid three-way answer whose reuse plus extend is overlap."""
    return { "reuse": round( overlap - extend, 6 ), "extend": extend, "unrelated": round( 1.0 - overlap, 6 ) }


NO_NAME = object()


def _arm( arm, overlaps, question=1, size=1, state="complete", stop_reason=None, run_name=None, **over ):
    """Ensures: returns one arm record in the stage1-arm-1 format answering every id in overlaps."""
    rec = { "format": "stage1-arm-1", "question": question, "need": "a need", "arm": arm, "run_name": None if run_name is NO_NAME else run_name or f"s1-q{question}-{arm}",
            "run_index": 1, "size": size, "model": "jev-test", "template_hash": "abc", "started_at": "t0", "ended_at": "t1",
            "state": state, "stop_reason": stop_reason, "ceiling_tokens": 1000, "attempt_limit": 8000,
            "entry_ids": list( overlaps ), "answers": [ { "id": i, "probabilities": _probs( o ) } for i, o in overlaps.items() ],
            "failed": [], "not_reached": [], "unasked": [], "cache_hits": 0, "rows": [],
            "totals": { "requests": 0, "calls": 0, "attempts_answered": 0, "attempts_failed": 0, "tokens_in": 0, "tokens_out": 0,
                        "usage_missing": 0, "refused_422": 0, "stopped_by": None, "spent_tokens": 0, "reserved_tokens": 0, "ceiling_refusals": 0 },
            "transport_calls": [] }
    rec.update( over )
    return rec


# --- the numbers the plan fixes ------------------------------------------------------------------------------------------

def test_the_constants_are_the_literals_of_the_plan():
    assert an.FORMAT == "stage1-arm-1"
    assert an.BAND == ( 0.35, 0.65 )                          # 10.5: a boundary entry lies from 0.35 to 0.65
    assert an.MIN_BOUNDARY_POOLED == 90                       # 10.5: ninety pooled; fewer reads inconclusive
    assert an.STOP_BOUNDARY_AFTER_QUESTION_2 == 50            # 10.5: fewer than 50 after question 2 stops the stage
    assert an.STOP_SPEND_AFTER_QUESTION_1 == 15_000_000       # 10.5: question 1 above 15,000,000 tokens stops the stage
    assert an.STAGE_TOKENS == 71_000_000                      # 11.1: the stage ceiling
    assert an.NOISE_FLOOR_MIN == 0.02                         # 10.5: the policy's own sum_tolerance
    assert an.PERCENTILE == 0.99
    assert an.FLIP_ALLOWANCE == 1                             # 10.5: flips of a pack size no more than the noise floor's flips plus 1
    assert an.THRESHOLD == 0.5
    assert an.OUTPUT_PER_ENTRY_STOP == 60                     # 10.5, 10.6: above 60 per entry the stage stops and asks
    assert an.PACK_SIZES == ( 10, 50, 200 )
    assert an.PRICE_PER_MILLION == 0.042                      # 10.6: the pinned price, input and output at the same rate
    assert an.PROBE_PLACEMENTS == ( "first", "middle", "last" )
    assert an.PROBE_NEIGHBOURS == ( "random", "near_duplicate" )


# --- reading one arm -----------------------------------------------------------------------------------------------------

def test_an_arm_is_read_into_overlaps_rounded_to_six_places():
    rec = _arm( "single1", { "a": 0.5 } )
    rec[ "answers" ][ 0 ][ "probabilities" ] = { "reuse": 0.1234567, "extend": 0.2, "unrelated": 0.6765433 }
    assert an.read_arm( rec )[ "overlaps" ] == { "a": 0.323457 }


def test_the_arm_keeps_the_question_arm_name_size_and_totals():
    a = an.read_arm( _arm( "pack50", { "a": 0.1 }, question=2, size=50 ) )
    assert ( a[ "question" ], a[ "arm" ], a[ "size" ], a[ "run_name" ] ) == ( 2, "pack50", 50, "s1-q2-pack50" )
    assert a[ "totals" ][ "spent_tokens" ] == 0


def test_a_record_of_another_format_is_refused():
    with pytest.raises( ValueError, match="stage1-arm-1" ):
        an.read_arm( _arm( "single1", { "a": 0.1 }, format="stage1-arm-2" ) )


def test_an_answer_for_an_id_the_arm_did_not_ask_is_refused():
    rec = _arm( "single1", { "a": 0.1 } ); rec[ "answers" ].append( { "id": "stranger", "probabilities": _probs( 0.2 ) } )
    with pytest.raises( ValueError, match="stranger" ):
        an.read_arm( rec )


def test_two_answers_for_one_id_are_refused():
    rec = _arm( "single1", { "a": 0.1 } ); rec[ "answers" ].append( rec[ "answers" ][ 0 ] )
    with pytest.raises( ValueError, match="twice" ):
        an.read_arm( rec )


def test_a_malformed_answer_is_listed_with_its_reason_and_has_no_overlap():
    rec = _arm( "single1", { "a": 0.1, "b": 0.2 } )
    rec[ "answers" ][ 1 ][ "probabilities" ] = { "reuse": 0.9, "extend": 0.9, "unrelated": 0.9 }
    a = an.read_arm( rec )
    assert a[ "overlaps" ] == { "a": 0.1 } and a[ "malformed" ] == { "b": "sum_not_one" }


def test_a_fully_answered_complete_arm_is_clean():
    assert an.read_arm( _arm( "single1", { "a": 0.1, "b": 0.7 } ) )[ "status" ] == "clean"


@pytest.mark.parametrize( "over", [ { "failed": [ "b" ] }, { "unasked": [ "b" ] }, { "not_reached": [ "b" ] } ] )
def test_an_arm_with_a_failed_unasked_or_unreached_entry_is_inconclusive_whatever_its_state(over):
    rec = _arm( "single1", { "a": 0.1, "b": 0.2 }, **over )
    rec[ "answers" ] = rec[ "answers" ][ :1 ]
    assert an.read_arm( rec )[ "status" ] == "inconclusive"


@pytest.mark.parametrize( "over", [ { "failed": [ "a" ] }, { "unasked": [ "a" ] }, { "not_reached": [ "a" ] },
                                    { "state": "incomplete" }, { "stop_reason": "attempts" } ] )
def test_an_arm_that_lists_a_problem_is_inconclusive_even_when_every_entry_has_an_answer(over):
    assert an.read_arm( _arm( "single1", { "a": 0.1 }, **over ) )[ "status" ] == "inconclusive"


def test_an_arm_with_a_malformed_answer_is_inconclusive():
    rec = _arm( "single1", { "a": 0.1 } ); rec[ "answers" ][ 0 ][ "probabilities" ] = None
    assert an.read_arm( rec )[ "status" ] == "inconclusive"


def test_an_arm_that_ran_out_of_attempts_is_inconclusive():
    rec = _arm( "single1", { "a": 0.1, "b": 0.2 }, state="incomplete", stop_reason="attempts", not_reached=[ "b" ] )
    rec[ "answers" ] = rec[ "answers" ][ :1 ]
    assert an.read_arm( rec )[ "status" ] == "inconclusive"


@pytest.mark.parametrize( "reason", [ "ceiling", "ledger", "consecutive_422", "error: ValueError" ] )
def test_an_arm_the_ceiling_the_ledger_or_a_refusal_stopped_is_invalid_never_a_pass(reason):
    rec = _arm( "pack50", { "a": 0.1 }, state="incomplete", stop_reason=reason )
    assert an.read_arm( rec )[ "status" ] == "invalid"


def test_an_arm_in_the_error_state_is_invalid():
    assert an.read_arm( _arm( "pack50", { "a": 0.1 }, state="error", stop_reason="error: OSError" ) )[ "status" ] == "invalid"


def test_an_arm_with_nothing_asked_and_nothing_answered_is_inconclusive_not_clean():
    assert an.read_arm( _arm( "single1", {} ) )[ "status" ] == "inconclusive"


# --- reading the stage ---------------------------------------------------------------------------------------------------

def test_the_stage_groups_arms_by_question_and_name():
    st = an.read_stage( [ _arm( "single1", { "a": 0.1 } ), _arm( "single2", { "a": 0.1 } ), _arm( "single1", { "a": 0.1 }, question=2 ) ] )
    assert sorted( st ) == [ 1, 2 ] and sorted( st[ 1 ] ) == [ "single1", "single2" ]


def test_the_same_run_name_twice_is_refused():
    with pytest.raises( ValueError, match="run name" ):
        an.read_stage( [ _arm( "single1", { "a": 0.1 } ), _arm( "single2", { "a": 0.1 }, run_name="s1-q1-single1" ) ] )


def test_arms_without_a_run_name_such_as_the_old_shape_one_may_repeat_across_questions():
    st = an.read_stage( [ _arm( "old", { "a": 0.1 }, run_name=NO_NAME ), _arm( "old", { "a": 0.1 }, question=2, run_name=NO_NAME ) ] )
    assert sorted( st ) == [ 1, 2 ]


def test_the_same_arm_twice_for_one_question_is_refused():
    with pytest.raises( ValueError, match="twice" ):
        an.read_stage( [ _arm( "single1", { "a": 0.1 } ), _arm( "single1", { "a": 0.1 }, run_name="other" ) ] )


# --- the percentile and the differences ----------------------------------------------------------------------------------

def test_the_percentile_is_the_nearest_rank_and_empty_gives_none():
    assert an.percentile( [] ) is None
    assert an.percentile( [ 0.5 ] ) == 0.5
    assert an.percentile( list( range( 1, 101 ) ) ) == 99                         # rank ceil( 0.99 * 100 ) = 99
    assert an.percentile( list( range( 1, 102 ) ) ) == 100                        # rank ceil( 0.99 * 101 ) = 100
    assert an.percentile( [ 3, 1, 2 ] ) == 3                                      # unsorted input; rank ceil( 2.97 ) = 3


def test_differences_cover_only_ids_answered_in_both_arms_and_are_absolute():
    a = an.read_arm( _arm( "single1", { "x": 0.5, "y": 0.2, "z": 0.9 } ) )
    b = an.read_arm( _arm( "single2", { "x": 0.45, "y": 0.3 } ) )
    assert an.differences( a, b ) == { "x": 0.05, "y": 0.1 }


def test_boundary_ids_include_both_ends_of_the_band():
    a = an.read_arm( _arm( "single1", { "lo": 0.35, "hi": 0.65, "under": 0.349999, "over": 0.650001, "mid": 0.5 } ) )
    assert an.boundary_ids( a ) == [ "hi", "lo", "mid" ]


def test_flips_count_ids_that_cross_the_cut_in_either_direction_and_the_cut_itself_counts_as_above():
    ref   = an.read_arm( _arm( "single1", { "a": 0.5, "b": 0.49, "c": 0.6, "d": 0.4 } ) )
    other = an.read_arm( _arm( "pack10", { "a": 0.49, "b": 0.5, "c": 0.7, "d": 0.45 } ) )
    assert an.flips( ref, other, [ "a", "b", "c", "d" ], 0.5 ) == [ "a", "b" ]


def test_flips_skip_ids_missing_from_either_arm():
    ref   = an.read_arm( _arm( "single1", { "a": 0.5, "b": 0.5 } ) )
    other = an.read_arm( _arm( "pack10", { "a": 0.1 } ) )
    assert an.flips( ref, other, [ "a", "b", "ghost" ], 0.5 ) == [ "a" ]


# --- the real answers ----------------------------------------------------------------------------------------------------

def test_real_answers_read_through_the_real_reader_give_the_counts_the_live_check_had():
    fx  = json.loads( REAL.read_text() )
    a   = an.read_arm( _arm( "single1", { r[ "id" ]: 0.0 for r in fx[ "answers" ] }, answers=fx[ "answers" ] ) )
    assert ( fx[ "total_answers" ], fx[ "in_band_035_065" ], fx[ "in_band_040_060" ] ) == ( 7705, 33, 15 )
    assert len( a[ "overlaps" ] ) == fx[ "sample" ][ "size" ] == 300 and a[ "malformed" ] == {}
    assert len( an.boundary_ids( a ) ) == 33                                                   # every in-band answer is in the sample
    assert sum( .40 <= o <= .60 for o in a[ "overlaps" ].values() ) == 15
    assert a[ "status" ] == "clean"
