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


@pytest.mark.parametrize( "over", [ { "failed": [ "a" ] }, { "unasked": [ "a" ] }, { "not_reached": [ "a" ] }, { "state": "incomplete" } ] )
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


# --- a whole question, built by hand --------------------------------------------------------------------------------------

def _names( n, prefix="e" ): return [ f"{prefix}{k:03d}" for k in range( n ) ]


def _base( n_boundary=100, n_other=20 ):
    """Ensures: returns n_boundary entries at 0.5 and n_other far outside the band at 0.05."""
    return { **{ i: 0.5 for i in _names( n_boundary ) }, **{ i: 0.05 for i in _names( n_other, "o" ) } }


def _moved( base, shift=0.0, down=(), up=() ):
    """Ensures: returns base moved by shift, the ids in down at 0.49 and those in up at 0.51."""
    out = { i: round( min( 1.0, max( 0.0, o + shift ) ), 6 ) for i, o in base.items() }
    out.update( { i: 0.49 for i in down } ); out.update( { i: 0.51 for i in up } )
    return out


def _probe( question, probe_id, placement, neighbours, overlap, base ):
    """Ensures: returns a pack-of-200 probe arm in which the probe entry has the given overlap."""
    name = f"probe-{placement}-{'random' if neighbours == 'random' else 'near'}"
    rec  = _arm( name, { **base, probe_id: overlap }, question=question, size=200 )
    rec[ "probe" ] = { "id": probe_id, "placement": placement, "neighbours": neighbours }
    return rec


def _probes( question, probe_id, base, overlap=None ):
    """Ensures: returns the six probe arms, at the probe's single value unless overlap is given."""
    o = base[ probe_id ] if overlap is None else overlap
    return [ _probe( question, probe_id, p, n, o, base ) for p in an.PROBE_PLACEMENTS for n in an.PROBE_NEIGHBOURS ]


def _question( question=1, base=None, noise=0.0, packs=None, probes=True, probe_shift=0.0 ):
    """
    Build the arms of one question.

    Ensures:
        - returns single1, single2 moved by noise, one pack arm per size in packs, and six probes
        - packs maps a size to the keyword arguments of _moved
    """
    base = _base() if base is None else base
    recs = [ _arm( "single1", base, question=question ), _arm( "single2", _moved( base, noise ), question=question ) ]
    for size, kw in ( { 10: {}, 50: {}, 200: {} } if packs is None else packs ).items():
        recs.append( _arm( f"pack{size}", _moved( base, **kw ), question=question, size=size ) )
    if probes: recs += _probes( question, "e000", base, None if not probe_shift else base[ "e000" ] + probe_shift )
    return recs


# --- the noise floor -----------------------------------------------------------------------------------------------------

def test_a_noise_below_the_minimum_reads_as_the_minimum():
    nf = an.noise_floor( an.read_stage( _question( noise=0.001 ) ) )
    assert ( nf[ "measured" ], nf[ "floor" ], nf[ "state" ], nf[ "max" ] ) == ( 0.001, 0.02, "ok", 0.001 )


def test_a_noise_above_the_minimum_is_the_floor():
    nf = an.noise_floor( an.read_stage( _question( noise=0.03 ) ) )
    assert ( nf[ "measured" ], nf[ "floor" ] ) == ( 0.03, 0.03 )


def test_the_noise_floor_pools_the_differences_of_every_question_run():
    one = _question( 1, noise=0.0 ); two = _question( 2, noise=0.04 )
    nf  = an.noise_floor( an.read_stage( one + two ) )
    assert nf[ "n" ] == 240 and nf[ "measured" ] == 0.04                       # 120 entries a question; half the pooled differences are 0.04


def test_the_noise_floor_is_inconclusive_when_a_single_run_is_missing_or_not_clean():
    recs = [ r for r in _question() if r[ "arm" ] != "single2" ]
    assert an.noise_floor( an.read_stage( recs ) )[ "state" ] == "inconclusive"
    recs = _question(); recs[ 0 ][ "failed" ] = [ "e000" ]
    assert an.noise_floor( an.read_stage( recs ) )[ "state" ] == "inconclusive"


# --- pass 1: the per-entry difference ------------------------------------------------------------------------------------

def test_pass_one_holds_when_the_99th_percentile_difference_equals_the_floor_and_fails_just_above():
    ok  = an.pass_one( an.read_stage( _question( packs={ 10: { "shift": 0.02 } } ) ), 10, 0.02 )
    bad = an.pass_one( an.read_stage( _question( packs={ 10: { "shift": 0.020001 } } ) ), 10, 0.02 )
    assert ( ok[ "state" ], ok[ "p99" ] ) == ( "pass", 0.02 ) and bad[ "state" ] == "fail"


def test_pass_one_reads_the_99th_percentile_so_one_wild_entry_in_a_hundred_does_not_fail_it_but_the_maximum_shows_it():
    base = { i: 0.05 for i in _names( 100 ) }
    pack = _moved( base ); pack[ "e000" ] = 0.9
    recs = [ _arm( "single1", base ), _arm( "pack10", pack, size=10 ) ]
    r = an.pass_one( an.read_stage( recs ), 10, 0.02 )
    assert ( r[ "state" ], r[ "p99" ], r[ "max" ], r[ "n" ] ) == ( "pass", 0.0, 0.85, 100 )


def test_pass_one_pools_the_differences_of_the_questions():
    st = an.read_stage( _question( 1, packs={ 10: {} } ) + _question( 2, packs={ 10: { "shift": 0.05 } } ) )
    r  = an.pass_one( st, 10, 0.02 )
    assert ( r[ "n" ], r[ "p99" ], r[ "state" ] ) == ( 240, 0.05, "fail" )


def test_pass_one_is_invalid_when_the_pack_arm_was_stopped_and_inconclusive_when_it_is_partial_or_absent():
    inv = _question( packs={ 10: {} } ); inv[ 2 ][ "state" ], inv[ 2 ][ "stop_reason" ] = "incomplete", "ceiling"
    assert an.pass_one( an.read_stage( inv ), 10, 0.02 )[ "state" ] == "invalid"
    par = _question( packs={ 10: {} } ); par[ 2 ][ "failed" ] = [ "e001" ]
    assert an.pass_one( an.read_stage( par ), 10, 0.02 )[ "state" ] == "inconclusive"
    assert an.pass_one( an.read_stage( _question( packs={ 50: {} } ) ), 10, 0.02 )[ "state" ] == "inconclusive"


# --- pass 2: flips at the threshold on boundary entries --------------------------------------------------------------------

def test_pass_two_allows_the_noise_floors_flips_plus_one_and_fails_one_more():
    noise = _question( noise=0.0 )
    noise[ 1 ] = _arm( "single2", _moved( _base(), down=[ "e001", "e002" ] ) )                          # two flips between the singles
    three = an.pass_two( an.read_stage( noise[ :2 ] + [ _arm( "pack10", _moved( _base(), down=[ "e003", "e004", "e005" ] ), size=10 ) ] ), 10 )
    four  = an.pass_two( an.read_stage( noise[ :2 ] + [ _arm( "pack10", _moved( _base(), down=[ "e003", "e004", "e005", "e006" ] ), size=10 ) ] ), 10 )
    assert ( three[ "pack_flips" ], three[ "noise_flips" ], three[ "state" ] ) == ( 3, 2, "pass" )
    assert ( four[ "pack_flips" ], four[ "state" ] ) == ( 4, "fail" )


def test_pass_two_counts_flips_only_on_boundary_entries():
    recs = [ _arm( "single1", _base() ), _arm( "single2", _base() ), _arm( "pack10", _moved( _base(), up=[ "o000", "o001", "o002" ] ), size=10 ) ]
    r = an.pass_two( an.read_stage( recs ), 10 )
    assert ( r[ "pack_flips" ], r[ "noise_flips" ], r[ "state" ] ) == ( 0, 0, "pass" )


def test_pass_two_pools_the_flips_of_the_questions():
    q1 = _question( 1, packs={ 10: { "down": [ "e001" ] } } ); q2 = _question( 2, packs={ 10: { "down": [ "e001", "e002" ] } } )
    r  = an.pass_two( an.read_stage( q1 + q2 ), 10 )
    assert ( r[ "pack_flips" ], r[ "boundary" ] ) == ( 3, 200 )


def test_pass_two_is_invalid_or_inconclusive_with_its_arms():
    inv = _question( packs={ 10: {} } ); inv[ 2 ][ "state" ], inv[ 2 ][ "stop_reason" ] = "incomplete", "ledger"
    assert an.pass_two( an.read_stage( inv ), 10 )[ "state" ] == "invalid"
    assert an.pass_two( an.read_stage( _question( packs={ 50: {} } ) ), 10 )[ "state" ] == "inconclusive"


# --- pass 3: the probe entry ---------------------------------------------------------------------------------------------

def test_pass_three_holds_when_all_six_placements_are_within_the_floor_and_fails_when_one_is_not():
    ok  = an.pass_three( an.read_stage( _question( probe_shift=0.02 ) ), 0.02 )
    bad = an.pass_three( an.read_stage( _question( probe_shift=0.020001 ) ), 0.02 )
    assert ( ok[ "state" ], ok[ "placements" ], ok[ "worst" ] ) == ( "pass", 6, 0.02 ) and bad[ "state" ] == "fail"


def test_pass_three_is_inconclusive_when_a_placement_is_missing_or_the_probe_has_no_single_value():
    recs = _question(); recs.pop()
    assert an.pass_three( an.read_stage( recs ), 0.02 )[ "state" ] == "inconclusive"
    assert an.pass_three( an.read_stage( _question( probes=False ) ), 0.02 )[ "state" ] == "inconclusive"
    recs = _question(); recs[ 0 ] = _arm( "single1", { k: v for k, v in _base().items() if k != "e000" } )
    assert an.pass_three( an.read_stage( recs ), 0.02 )[ "state" ] == "inconclusive"


def test_pass_three_is_invalid_when_a_probe_arm_was_stopped():
    recs = _question(); recs[ -1 ][ "state" ], recs[ -1 ][ "stop_reason" ] = "incomplete", "ceiling"
    assert an.pass_three( an.read_stage( recs ), 0.02 )[ "state" ] == "invalid"


def test_pass_three_wants_each_of_the_six_placements_exactly_once_per_question():
    recs = _question(); recs[ -1 ] = _probe( 1, "e000", "first", "random", 0.5, _base() )
    recs[ -1 ][ "arm" ], recs[ -1 ][ "run_name" ] = "probe-extra", "s1-q1-probe-extra"
    st = an.read_stage( recs )
    with pytest.raises( ValueError, match="placement .* given twice" ):
        an.pass_three( st, 0.02 )
    recs[ -1 ][ "arm" ] = "probe-first-random"
    with pytest.raises( ValueError, match="given twice" ):
        an.read_stage( recs )


def test_pass_three_pools_the_questions_and_reports_the_worst_difference():
    r = an.pass_three( an.read_stage( _question( 1 ) + _question( 2, probe_shift=0.01 ) ), 0.02 )
    assert ( r[ "placements" ], r[ "worst" ], r[ "state" ] ) == ( 12, 0.01, "pass" )


# --- all the passes, and the default pack size ---------------------------------------------------------------------------

def test_with_every_pass_met_the_default_is_the_largest_size_and_the_verdict_names_it():
    rep = an.evaluate( an.read_stage( _question() ) )
    assert ( rep[ "sizes" ][ 10 ][ "state" ], rep[ "sizes" ][ 50 ][ "state" ], rep[ "sizes" ][ 200 ][ "state" ] ) == ( "pass", "pass", "pass" )
    assert ( rep[ "default_size" ], rep[ "decision" ] ) == ( 200, "default pack size 200" )
    assert rep[ "boundary_pooled" ] == 100 and rep[ "boundary_by_question" ] == { 1: 100 }


def test_the_default_is_the_largest_size_that_passes_even_when_a_larger_one_fails():
    rep = an.evaluate( an.read_stage( _question( packs={ 10: {}, 50: {}, 200: { "shift": 0.1 } } ) ) )
    assert ( rep[ "sizes" ][ 200 ][ "state" ], rep[ "default_size" ] ) == ( "fail", 50 )


def test_a_failed_probe_fails_only_the_size_the_probe_was_run_at():
    rep = an.evaluate( an.read_stage( _question( probe_shift=0.1 ) ) )
    assert ( rep[ "sizes" ][ 10 ][ "state" ], rep[ "sizes" ][ 50 ][ "state" ], rep[ "sizes" ][ 200 ][ "state" ] ) == ( "pass", "pass", "fail" )
    assert rep[ "default_size" ] == 50


def test_fewer_than_ninety_pooled_boundary_entries_turn_a_pass_into_inconclusive_never_a_pass():
    rep = an.evaluate( an.read_stage( _question( base=_base( 89 ) ) ) )
    assert rep[ "boundary_pooled" ] == 89
    assert all( rep[ "sizes" ][ s ][ "state" ] == "inconclusive" for s in an.PACK_SIZES )
    assert ( rep[ "default_size" ], rep[ "decision" ] ) == ( None, "inconclusive" )
    assert an.evaluate( an.read_stage( _question( base=_base( 90 ) ) ) )[ "default_size" ] == 200


def test_a_fail_still_reads_fail_when_the_boundary_count_is_short():
    rep = an.evaluate( an.read_stage( _question( base=_base( 89 ), packs={ 10: { "shift": 0.1 }, 50: {}, 200: {} } ) ) )
    assert rep[ "sizes" ][ 10 ][ "state" ] == "fail" and rep[ "sizes" ][ 50 ][ "state" ] == "inconclusive"


def test_when_no_size_passes_the_decision_is_to_stop_and_ask():
    rep = an.evaluate( an.read_stage( _question( packs={ 10: { "shift": 0.1 }, 50: { "shift": 0.1 }, 200: { "shift": 0.1 } } ) ) )
    assert ( rep[ "default_size" ], rep[ "decision" ] ) == ( None, "stop and ask: no pack size passes" )


def test_an_invalid_arm_anywhere_means_stop_and_ask_even_if_another_size_passes():
    recs = _question(); recs[ 4 ][ "state" ], recs[ 4 ][ "stop_reason" ] = "incomplete", "ceiling"          # pack200
    rep = an.evaluate( an.read_stage( recs ) )
    assert rep[ "sizes" ][ 200 ][ "state" ] == "invalid" and rep[ "decision" ] == "stop and ask: an arm is invalid"


def test_an_unfinished_size_beside_a_pass_names_the_pass_and_lists_the_unresolved_size():
    recs = [ r for r in _question() if r[ "arm" ] != "pack200" ]
    rep = an.evaluate( an.read_stage( recs ) )
    assert ( rep[ "default_size" ], rep[ "unresolved_larger" ] ) == ( 50, [ 200 ] )


def test_a_noise_floor_that_cannot_be_measured_makes_every_size_inconclusive():
    rep = an.evaluate( an.read_stage( [ r for r in _question() if r[ "arm" ] != "single2" ] ) )
    assert all( rep[ "sizes" ][ s ][ "state" ] == "inconclusive" for s in an.PACK_SIZES ) and rep[ "decision" ] == "inconclusive"


# --- the rules that stop the stage ---------------------------------------------------------------------------------------

def _spend( question, tokens, arm="single1" ):
    """Ensures: returns a tiny clean arm of the question that settled the given tokens."""
    rec = _arm( arm, { "a": 0.1 }, question=question ); rec[ "totals" ][ "spent_tokens" ] = tokens
    return rec


def _with_boundary( question, n ):
    """Ensures: returns a clean single1 arm holding n boundary entries."""
    return _arm( "single1", { f"q{question}b{k:03d}": 0.5 for k in range( n ) }, question=question )


def test_spend_above_fifteen_million_after_question_one_stops_the_stage_and_exactly_fifteen_million_does_not():
    over  = an.stop_rules( an.read_stage( [ _spend( 1, 8_000_000 ), _spend( 1, 7_000_001, "single2" ) ] ), check_arms=False )
    exact = an.stop_rules( an.read_stage( [ _spend( 1, 8_000_000 ), _spend( 1, 7_000_000, "single2" ) ] ), check_arms=False )
    assert ( over[ "stop" ], over[ "findings" ][ 0 ][ "rule" ] ) == ( True, "spend_after_question_1" )
    assert exact[ "stop" ] is False and exact[ "spent_by_question" ] == { 1: 15_000_000 }


def test_the_spend_of_an_arm_without_a_settled_figure_is_its_reported_tokens():
    rec = _spend( 1, None ); rec[ "totals" ][ "tokens_in" ], rec[ "totals" ][ "tokens_out" ] = 15_000_000, 1
    assert an.stop_rules( an.read_stage( [ rec ] ), check_arms=False )[ "stop" ] is True


def test_fewer_than_fifty_pooled_boundary_entries_after_question_two_stops_before_question_three():
    short = an.stop_rules( an.read_stage( [ _with_boundary( 1, 20 ), _with_boundary( 2, 29 ) ] ), check_arms=False )
    ok    = an.stop_rules( an.read_stage( [ _with_boundary( 1, 20 ), _with_boundary( 2, 30 ) ] ), check_arms=False )
    assert ( short[ "stop" ], short[ "pooled_boundary" ], short[ "next_step" ] ) == ( True, 49, "stop and ask: under 50 pooled boundary entries after question 2" )
    assert ( ok[ "stop" ], ok[ "next_step" ] ) == ( False, "run question 3" )


def test_the_fifty_rule_is_read_only_after_question_two_and_before_question_three():
    one = an.stop_rules( an.read_stage( [ _with_boundary( 1, 3 ) ] ), check_arms=False )
    assert one[ "stop" ] is False and one[ "next_step" ] == "run question 2"
    three = an.stop_rules( an.read_stage( [ _with_boundary( 1, 3 ), _with_boundary( 2, 3 ), _with_boundary( 3, 90 ) ] ), check_arms=False )
    assert three[ "stop" ] is False and three[ "next_step" ] == "evaluate"


def test_after_question_three_fewer_than_ninety_allows_the_reserve_question_and_ninety_does_not_need_it():
    short = an.stop_rules( an.read_stage( [ _with_boundary( 1, 30 ), _with_boundary( 2, 30 ), _with_boundary( 3, 29 ) ] ), check_arms=False )
    ok    = an.stop_rules( an.read_stage( [ _with_boundary( 1, 30 ), _with_boundary( 2, 30 ), _with_boundary( 3, 30 ) ] ), check_arms=False )
    assert ( short[ "pooled_boundary" ], short[ "next_step" ] ) == ( 89, "run the reserve question" )
    assert ( ok[ "pooled_boundary" ], ok[ "next_step" ] ) == ( 90, "evaluate" )


def test_after_the_reserve_question_fewer_than_ninety_is_inconclusive_and_nothing_more_is_run():
    st = an.read_stage( [ _with_boundary( 1, 20 ), _with_boundary( 2, 20 ), _with_boundary( 3, 20 ), _with_boundary( 4, 20 ) ] )
    r  = an.stop_rules( st, check_arms=False )
    assert ( r[ "pooled_boundary" ], r[ "next_step" ] ) == ( 80, "evaluate: inconclusive, under 90 pooled boundary entries" )


def test_a_single_run_that_is_not_clean_gives_no_boundary_count_and_the_rule_says_so():
    bad = _with_boundary( 2, 49 ); bad[ "failed" ] = [ "x" ]
    r   = an.stop_rules( an.read_stage( [ _with_boundary( 1, 20 ), bad ] ), check_arms=False )
    assert r[ "next_step" ] == "stop and ask: question 2's single run 1 is not clean" and r[ "stop" ] is True


def test_the_stage_total_above_seventy_one_million_is_reported_as_a_breach():
    r = an.stop_rules( an.read_stage( [ _spend( 1, 71_000_001 ) ] ), check_arms=False )
    assert any( f[ "rule" ] == "stage_ceiling" for f in r[ "findings" ] ) and r[ "stop" ] is True
    ok = an.stop_rules( an.read_stage( [ _spend( 1, 14_000_000 ), _spend( 2, 57_000_000 ) ] ), check_arms=False )
    assert not any( f[ "rule" ] == "stage_ceiling" for f in ok[ "findings" ] ) and ok[ "spent_total" ] == 71_000_000


# --- the canary ----------------------------------------------------------------------------------------------------------

def _canary( rows, totals=None, tripped=None ):
    """Ensures: returns ( arm record, canary record ) for rows given as request dicts."""
    arm = _arm( "canary", { f"c{k}": 0.1 for k in range( 10 ) }, size=10, rows=rows )
    if totals: arm[ "totals" ].update( totals )
    return arm, { "format": "stage1-canary-1", "question": 1, "run_name": "s1-q1-canary", "tripped": [] if tripped is None else tripped, "approved": None }


def _row( tokens_out=420, tokens_in=1000, reserve=4000, size=10, status="answered", http_status=None, attempts=1 ):
    return { "request_hash": "h", "size": size, "status": status, "attempts": attempts, "tokens_in": tokens_in, "tokens_out": tokens_out,
             "reserve_tokens": reserve, "http_status": http_status }


def test_sixty_output_tokens_an_entry_is_fine_and_more_trips_the_canary():
    ok  = an.check_canary( *_canary( [ _row( tokens_out=600 ) ] ) )
    bad = an.check_canary( *_canary( [ _row( tokens_out=601 ) ] ) )
    assert ok[ "tripped" ] == [] and bad[ "tripped" ] == [ "output_per_entry_over_60" ]
    assert bad[ "output_per_entry" ] == [ 60.1 ]


def test_usage_equal_to_the_reserve_is_fine_and_one_over_trips_the_canary():
    ok  = an.check_canary( *_canary( [ _row( tokens_in=3400, tokens_out=600, reserve=4000 ) ] ) )
    bad = an.check_canary( *_canary( [ _row( tokens_in=3401, tokens_out=600, reserve=4000 ) ] ) )
    assert ok[ "tripped" ] == [] and bad[ "tripped" ] == [ "usage_over_reserve" ]


def test_any_refusal_trips_the_canary_by_status_by_http_422_or_by_the_total():
    for rows, totals in ( ( [ _row( status="refused" ) ], None ), ( [ _row( http_status=422 ) ], None ), ( [ _row() ], { "refused_422": 1 } ) ):
        assert an.check_canary( *_canary( rows, totals ) )[ "tripped" ] == [ "refusal" ], rows


def test_the_trips_come_in_a_fixed_order_and_a_row_never_sent_is_skipped():
    r = an.check_canary( *_canary( [ _row( tokens_out=700, tokens_in=9000, status="refused" ), _row( tokens_in=None, tokens_out=None, reserve=None, status="not_reached", attempts=0 ) ] ) )
    assert r[ "tripped" ] == [ "output_per_entry_over_60", "usage_over_reserve", "refusal" ]


def test_an_answered_row_without_usage_cannot_be_checked_and_is_listed_for_a_human():
    r = an.check_canary( *_canary( [ _row( tokens_in=None, tokens_out=None ) ] ) )
    assert r[ "tripped" ] == [ "usage_missing" ] and r[ "unverifiable" ] == 1


def test_a_disagreement_with_the_drivers_own_list_is_reported_both_ways():
    r = an.check_canary( *_canary( [ _row( tokens_out=700 ) ], tripped=[ "refusal" ] ) )
    assert ( r[ "agrees" ], r[ "analysis_only" ], r[ "driver_only" ] ) == ( False, [ "output_per_entry_over_60" ], [ "refusal" ] )
    assert an.check_canary( *_canary( [ _row() ] ) )[ "agrees" ] is True


def test_the_canary_reports_its_failed_unasked_and_unreached_counts():
    arm, can = _canary( [ _row() ] ); arm[ "failed" ], arm[ "unasked" ], arm[ "not_reached" ] = [ "a" ], [ "b", "c" ], []
    r = an.check_canary( arm, can )
    assert ( r[ "failed" ], r[ "unasked" ], r[ "not_reached" ] ) == ( 1, 2, 0 )


# --- the page arm --------------------------------------------------------------------------------------------------------

def _pages( s1, s2, pack ):
    return [ _arm( "page-single1", s1 ), _arm( "page-single2", s2 ), _arm( "page-pack", pack, size=200 ) ]


def test_pages_chosen_the_same_after_packing_pass_and_the_differences_are_reported():
    base = { "p1": 0.9, "p2": 0.6, "p3": 0.1 }
    r = an.analyze_pages( an.read_stage( _pages( base, _moved( base, 0.01 ), _moved( base, 0.03 ) ) ) )[ 1 ]
    assert r[ "state" ] == "pass" and r[ "chosen_single1" ] == [ "p1", "p2" ] and r[ "chosen_pack" ] == [ "p1", "p2" ]
    assert ( r[ "pack_p99" ], r[ "pack_max" ], r[ "noise_p99" ], r[ "noise_max" ] ) == ( 0.03, 0.03, 0.01, 0.01 )


def test_a_changed_set_of_chosen_pages_is_a_fail_for_packing_the_page_asks():
    base = { "p1": 0.9, "p2": 0.31, "p3": 0.1 }
    r = an.analyze_pages( an.read_stage( _pages( base, base, _moved( base, -0.02 ) ) ) )[ 1 ]
    assert r[ "state" ] == "fail" and r[ "set_changed_by_packing" ] is True and r[ "chosen_pack" ] == [ "p1" ]


def test_a_set_that_changes_between_the_two_single_runs_is_reported_as_noise_not_as_a_fail():
    base = { "p1": 0.9, "p2": 0.31 }
    r = an.analyze_pages( an.read_stage( _pages( base, _moved( base, -0.02 ), base ) ) )[ 1 ]
    assert r[ "state" ] == "pass" and r[ "set_changed_by_noise" ] is True


def test_the_chosen_pages_are_the_floor_and_the_cap_of_the_tool_itself():
    from lupin_mcp import reuse_tools as rt
    base = { f"p{k:02d}": 0.9 - k / 100 for k in range( rt.MAX_PAGES + 3 ) }
    r = an.analyze_pages( an.read_stage( _pages( base, base, base ) ) )[ 1 ]
    assert len( r[ "chosen_single1" ] ) == rt.MAX_PAGES


def test_the_page_arm_is_inconclusive_or_invalid_with_its_arms_and_absent_questions_are_skipped():
    recs = _pages( { "p1": 0.9 }, { "p1": 0.9 }, { "p1": 0.9 } ); recs[ 2 ][ "failed" ] = [ "p1" ]
    assert an.analyze_pages( an.read_stage( recs ) )[ 1 ][ "state" ] == "inconclusive"
    recs = _pages( { "p1": 0.9 }, { "p1": 0.9 }, { "p1": 0.9 } ); recs[ 2 ][ "state" ], recs[ 2 ][ "stop_reason" ] = "incomplete", "ceiling"
    assert an.analyze_pages( an.read_stage( recs ) )[ 1 ][ "state" ] == "invalid"
    assert an.analyze_pages( an.read_stage( _question() ) ) == {}
    assert an.analyze_pages( an.read_stage( _pages( { "p1": 0.9 }, { "p1": 0.9 }, { "p1": 0.9 } )[ :2 ] ) )[ 1 ][ "state" ] == "inconclusive"


# --- cases a mutation showed unguarded -----------------------------------------------------------------------------------

def test_exactly_ninety_pooled_after_the_reserve_question_is_enough_to_evaluate():
    r = an.stop_rules( an.read_stage( [ _with_boundary( 1, 30 ), _with_boundary( 2, 30 ), _with_boundary( 3, 30 ), _arm( "single1", { "far": 0.05 }, question=4 ) ] ), check_arms=False )
    assert ( r[ "pooled_boundary" ], r[ "next_step" ] ) == ( 90, "evaluate" )


def test_a_question_whose_single_run_is_not_clean_adds_nothing_to_the_pooled_count():
    bad = _with_boundary( 2, 49 ); bad[ "failed" ] = [ "x" ]
    assert an.stop_rules( an.read_stage( [ _with_boundary( 1, 20 ), bad ] ), check_arms=False )[ "pooled_boundary" ] == 20
    recs = _question() + [ dict( r, question=2, run_name=f"s1-q2-{r[ 'arm' ]}" ) for r in _question() if r[ "arm" ] == "single1" ]
    recs[ -1 ][ "failed" ] = [ "e000" ]
    assert an.evaluate( an.read_stage( recs ) )[ "boundary_by_question" ] == { 1: 100 }


def test_a_stopped_arm_outranks_a_failed_pass_when_the_size_is_named():
    recs = _question( packs={ 10: {}, 50: {}, 200: { "shift": 0.1 } } ); recs[ -1 ][ "state" ], recs[ -1 ][ "stop_reason" ] = "incomplete", "ceiling"
    rep = an.evaluate( an.read_stage( recs ) )
    assert rep[ "sizes" ][ 200 ][ "pass_one" ][ "state" ] == "fail" and rep[ "sizes" ][ 200 ][ "pass_three" ][ "state" ] == "invalid"
    assert rep[ "sizes" ][ 200 ][ "state" ] == "invalid"


def test_an_empty_stage_has_no_noise_floor_and_no_decision_to_make():
    assert an.noise_floor( {} )[ "state" ] == "inconclusive"
    assert an.evaluate( {} )[ "decision" ] == "inconclusive"


def test_a_stopped_single_run_makes_every_size_invalid_and_the_decision_a_stop():
    recs = _question(); recs[ 1 ][ "state" ], recs[ 1 ][ "stop_reason" ] = "incomplete", "ledger"
    rep = an.evaluate( an.read_stage( recs ) )
    assert rep[ "noise_floor" ][ "state" ] == "invalid" and all( rep[ "sizes" ][ s ][ "state" ] == "invalid" for s in an.PACK_SIZES )
    assert rep[ "decision" ] == "stop and ask: an arm is invalid"


def test_a_row_that_was_refused_without_usage_is_not_counted_unverifiable_but_an_answered_one_is():
    r = an.check_canary( *_canary( [ _row( tokens_in=None, tokens_out=None, status="refused" ), _row( tokens_in=None, tokens_out=None ) ] ) )
    assert r[ "unverifiable" ] == 1


def test_a_row_with_output_but_no_input_usage_is_skipped_rather_than_crashing_the_reserve_check():
    r = an.check_canary( *_canary( [ _row( tokens_in=None, tokens_out=600, reserve=1 ) ] ) )
    assert r[ "tripped" ] == [ "usage_missing" ] and r[ "output_per_entry" ] == [] and r[ "unverifiable" ] == 1


# --- the canary also trips on missing usage and on an unfinished arm, as the driver writes it ---------------------------------

def test_the_canary_trips_on_missing_usage_and_on_an_unfinished_arm_in_the_drivers_order():
    arm, can = _canary( [ _row( tokens_in=None, tokens_out=None ) ] ); arm[ "state" ] = "incomplete"
    assert an.check_canary( arm, can )[ "tripped" ] == [ "usage_missing", "incomplete" ]
    assert an.CANARY_TRIPS == ( "output_per_entry_over_60", "usage_over_reserve", "refusal", "usage_missing", "incomplete", "nothing_measured" )


@pytest.mark.parametrize( "over", [ { "failed": [ "a" ] }, { "unasked": [ "a" ] }, { "not_reached": [ "a" ] } ] )
def test_a_canary_arm_with_a_failed_unasked_or_unreached_entry_trips_incomplete(over):
    arm, can = _canary( [ _row() ] ); arm.update( over )
    assert an.check_canary( arm, can )[ "tripped" ] == [ "incomplete" ]


def test_the_drivers_five_names_agree_with_the_recomputed_ones():
    arm, can = _canary( [ _row() ], tripped=[] )
    assert an.check_canary( arm, can )[ "agrees" ] is True
    arm, can = _canary( [ _row( tokens_in=None, tokens_out=None ) ], tripped=[ "usage_missing" ] )
    assert an.check_canary( arm, can )[ "agrees" ] is True


# --- the other policy boundaries ------------------------------------------------------------------------------------------

def _with_probs( arm, probs ):
    """Ensures: returns an arm record answering each id with the given probabilities."""
    rec = _arm( arm, { i: 0.0 for i in probs } )
    rec[ "answers" ] = [ { "id": i, "probabilities": p } for i, p in probs.items() ]
    return rec


def test_the_other_boundaries_are_the_page_floor_and_the_confidence_bar_of_the_policy():
    assert ( an.FLOOR, an.CONFIDENCE_BAR ) == ( 0.3, 0.9 )


def test_flips_at_the_page_floor_are_counted_over_every_entry_for_the_pack_and_for_the_noise():
    s1 = _arm( "single1", { "x": 0.3, "y": 0.29, "z": 0.8 } )
    s2 = _arm( "single2", { "x": 0.29, "y": 0.29, "z": 0.8 } )
    pk = _arm( "pack10", { "x": 0.29, "y": 0.3, "z": 0.2 }, size=10 )
    r  = an.other_boundaries( an.read_stage( [ s1, s2, pk ] ), 10 )
    assert r[ 1 ][ "floor" ] == { "pack": 3, "noise": 1 }


def test_flips_at_the_confidence_bar_use_the_largest_probability_of_each_answer():
    hi, lo = { "reuse": 0.9, "extend": 0.0, "unrelated": 0.1 }, { "reuse": 0.89, "extend": 0.0, "unrelated": 0.11 }
    s1 = _with_probs( "single1", { "x": hi, "y": lo } ); s2 = _with_probs( "single2", { "x": hi, "y": lo } )
    pk = _with_probs( "pack10", { "x": lo, "y": hi } ); pk[ "size" ] = 10
    r  = an.other_boundaries( an.read_stage( [ s1, s2, pk ] ), 10 )
    assert r[ 1 ][ "confidence" ] == { "pack": 2, "noise": 0 }


def test_the_other_boundaries_are_none_for_a_question_whose_arms_are_not_clean_or_absent():
    s1 = _arm( "single1", { "x": 0.3 } ); s2 = _arm( "single2", { "x": 0.3 } )
    assert an.other_boundaries( an.read_stage( [ s1, s2 ] ), 10 ) == { 1: None }
    pk = _arm( "pack10", { "x": 0.3 }, size=10, failed=[ "x" ] )
    assert an.other_boundaries( an.read_stage( [ s1, s2, pk ] ), 10 ) == { 1: None }


# --- tokens, retries and cost ----------------------------------------------------------------------------------------------

def _sent( tin, tout, attempts=1 ):
    return { "request_hash": "h", "size": 10, "status": "answered", "attempts": attempts, "tokens_in": tin, "tokens_out": tout }


def test_request_statistics_count_only_requests_that_were_sent_and_their_mean_tokens():
    rows = [ _sent( 1000, 400 ), _sent( 2000, 600 ), { "request_hash": "n", "size": 10, "status": "not_reached", "attempts": 0, "tokens_in": None, "tokens_out": None } ]
    arm  = _arm( "pack10", { "a": 0.1 }, size=10, rows=rows, transport_calls=[ { "attempts": 1 }, { "attempts": 3 } ] )
    st   = an.request_stats( an.read_stage( [ arm ] ) )[ 1 ][ "pack10" ]
    assert ( st[ "requests_sent" ], st[ "tokens_in_per_request" ], st[ "tokens_out_per_request" ] ) == ( 2, 1500.0, 500.0 )
    assert ( st[ "retried_calls" ], st[ "extra_attempts" ], st[ "usage_missing" ] ) == ( 1, 2, 0 )
    assert st[ "tokens_out_per_entry" ] == 50.0 and st[ "retry_statuses" ] == "429 or 529, not told apart"


def test_request_statistics_count_a_sent_request_without_usage_as_missing_and_leave_it_out_of_the_means():
    arm = _arm( "pack10", { "a": 0.1 }, size=10, rows=[ _sent( 1000, 400 ), _sent( None, None ) ] )
    st  = an.request_stats( an.read_stage( [ arm ] ) )[ 1 ][ "pack10" ]
    assert ( st[ "requests_sent" ], st[ "usage_missing" ], st[ "tokens_in_per_request" ] ) == ( 2, 1, 1000.0 )


def test_an_arm_with_no_request_sent_has_no_means():
    st = an.request_stats( an.read_stage( [ _arm( "pack10", { "a": 0.1 }, size=10 ) ] ) )[ 1 ][ "pack10" ]
    assert ( st[ "requests_sent" ], st[ "tokens_in_per_request" ], st[ "tokens_out_per_entry" ] ) == ( 0, None, None )


def test_the_cost_of_a_search_is_the_default_pack_arm_plus_the_page_pack_at_the_pinned_price():
    pack = _arm( "pack200", { "a": 0.1 }, size=200 ); pack[ "totals" ][ "spent_tokens" ] = 1_000_000
    page = _arm( "page-pack", { "p": 0.1 }, size=200 ); page[ "totals" ][ "spent_tokens" ] = 100_000
    c    = an.cost_per_search( an.read_stage( [ pack, page ] ), 200 )
    assert c[ 1 ] == { "entry_tokens": 1_000_000, "page_tokens": 100_000, "dollars": 0.0462 }
    assert c[ "mean_dollars" ] == 0.0462


def test_the_cost_is_none_without_a_default_size_and_the_page_part_is_zero_when_there_is_no_page_arm():
    pack = _arm( "pack50", { "a": 0.1 }, size=50 ); pack[ "totals" ][ "spent_tokens" ] = 2_000_000
    st   = an.read_stage( [ pack ] )
    assert an.cost_per_search( st, None ) is None
    assert an.cost_per_search( st, 50 )[ 1 ] == { "entry_tokens": 2_000_000, "page_tokens": 0, "dollars": 0.084 }


# --- the old-shape arm, reported only -------------------------------------------------------------------------------------

def test_the_old_shape_report_compares_only_the_entries_that_were_cache_hits():
    s1  = _arm( "single1", { "a": 0.5, "b": 0.5, "c": 0.5, "d": 0.9 } )
    old = _arm( "old", { "a": 0.5, "b": 0.45, "c": 0.4 }, size=1, run_name=NO_NAME, state="incomplete" )
    r   = an.old_shape_report( an.read_stage( [ s1, old ] ) )[ 1 ]
    assert ( r[ "hits" ], r[ "p99" ], r[ "max" ], r[ "boundary_flips" ] ) == ( 3, 0.1, 0.1, 2 )
    assert r[ "note" ] == "reported only, no pass or fail"


def test_a_question_with_no_old_shape_arm_or_no_clean_single_run_is_left_out_of_the_old_shape_report():
    assert an.old_shape_report( an.read_stage( [ _arm( "single1", { "a": 0.5 } ) ] ) ) == {}
    s1 = _arm( "single1", { "a": 0.5 }, failed=[ "a" ] ); old = _arm( "old", { "a": 0.5 }, run_name=NO_NAME )
    assert an.old_shape_report( an.read_stage( [ s1, old ] ) ) == { 1: None }


def test_the_old_shape_arm_is_read_from_the_cache_through_the_real_request_builder(tmp_path):
    from lupin_mcp import reuse_tools as rt
    entries = [ { "id": "m.a", "sig": "()", "doc": "does a" }, { "id": "m.b", "sig": "()", "doc": "does b" }, { "id": "m.c", "sig": "()", "doc": "does c" } ]
    cache   = rt.JevCache( tmp_path )
    for rec, probs in ( ( entries[ 0 ], { "reuse": 0.8, "extend": 0.1, "unrelated": 0.1 } ), ( entries[ 1 ], { "reuse": 0.0, "extend": 0.0, "unrelated": 1.0 } ) ):
        body = rt.build_request( "a need", rt.entry_text( rec ) )
        cache.put( rt.request_hash( body ), { "answers": { "fit": { "choice": "x", "confidence": 1.0, "probabilities": probs, "type": "choice" } }, "model": "jev-1.13.0" } )
    rec = an.old_shape_arm( 2, tmp_path, "a need", entries )
    arm = an.read_arm( rec )
    assert ( rec[ "arm" ], rec[ "run_name" ], rec[ "question" ], rec[ "size" ], rec[ "cache_hits" ] ) == ( "old", None, 2, 1, 2 )
    assert rec[ "entry_ids" ] == [ "m.a", "m.b", "m.c" ] and arm[ "overlaps" ] == { "m.a": 0.9, "m.b": 0.0 }
    assert ( rec[ "state" ], rec[ "not_reached" ] ) == ( "incomplete", [ "m.c" ] ) and arm[ "status" ] == "inconclusive"


def test_the_old_shape_arm_is_complete_only_when_every_entry_was_a_hit_and_a_bad_answer_is_malformed(tmp_path):
    from lupin_mcp import reuse_tools as rt
    entries = [ { "id": "m.a", "sig": "()", "doc": "does a" } ]
    body = rt.build_request( "n", rt.entry_text( entries[ 0 ] ) )
    rt.JevCache( tmp_path ).put( rt.request_hash( body ), { "answers": {}, "model": "jev-1.13.0" } )
    rec = an.old_shape_arm( 1, tmp_path, "n", entries )
    assert rec[ "state" ] == "complete" and an.read_arm( rec )[ "malformed" ] == { "m.a": "not_a_mapping" }


def _extra_arms( question, overlaps, answers=None ):
    """Ensures: returns the canary and the three page arms of a question."""
    ids = list( overlaps )[ :10 ]
    can = _arm( "canary", { i: overlaps[ i ] for i in ids }, question=question, size=10 )
    pages = { "p1": 0.9, "p2": 0.6, "p3": 0.1 }
    return [ can ] + [ _arm( n, pages, question=question, size=s ) for n, s in ( ( "page-single1", 1 ), ( "page-single2", 1 ), ( "page-pack", 200 ) ) ]


def _complete( question=1, **kw ):
    """Ensures: returns the fifteen arms the plan runs for one question."""
    return _question( question, **kw ) + _extra_arms( question, _base() )


# --- the report ----------------------------------------------------------------------------------------------------------

def test_the_report_gathers_every_part_and_the_text_names_the_decision_and_the_next_step():
    rep = an.build_report( _question(), canaries=[] )
    assert set( rep ) >= { "decision", "next_step", "evaluate", "stop_rules", "pages", "other_boundaries", "request_stats", "cost", "old_shape", "canaries" }
    assert rep[ "decision" ] == "default pack size 200"
    text = an.render( rep )
    assert "default pack size 200" in text and rep[ "next_step" ] in text and "boundary entries pooled: 100" in text


def test_the_report_names_each_size_with_its_three_numbers_and_each_arm_that_was_not_clean():
    recs = _question(); recs[ 3 ][ "failed" ] = [ "e001" ]
    text = an.render( an.build_report( recs, canaries=[] ) )
    assert "pack 50" in text and "inconclusive" in text and "s1-q1-pack50" in text
    assert "s1-q1-pack10" not in text and "s1-q1-single1" not in text                       # only arms that are not clean are named


def test_a_canary_that_disagrees_with_the_driver_is_listed_in_the_report():
    arm, can = _canary( [ _row( tokens_out=700 ) ], tripped=[] )
    arm[ "question" ] = 1
    rep = an.build_report( _question(), canaries=[ ( arm, can ) ] )
    assert rep[ "canaries" ][ 0 ][ "agrees" ] is False
    assert "output_per_entry_over_60" in an.render( rep )


def test_real_answers_copied_into_three_questions_reach_the_ninety_and_a_default_through_every_function():
    fx   = json.loads( REAL.read_text() )
    recs = []
    for q in ( 1, 2, 3 ):
        ov = { r[ "id" ]: 0.0 for r in fx[ "answers" ] }
        for name, size in ( ( "single1", 1 ), ( "single2", 1 ), ( "pack10", 10 ), ( "pack50", 50 ), ( "pack200", 200 ) ):
            recs.append( _arm( name, ov, question=q, size=size, answers=fx[ "answers" ] ) )
        recs += [ dict( r, answers=fx[ "answers" ], entry_ids=[ a[ "id" ] for a in fx[ "answers" ] ] ) for r in _probes( q, fx[ "answers" ][ 0 ][ "id" ], ov ) ]
        recs += _extra_arms( q, ov, fx[ "answers" ] )
    rep = an.build_report( recs, canaries=[] )
    assert rep[ "evaluate" ][ "boundary_pooled" ] == 99 and rep[ "evaluate" ][ "boundary_by_question" ] == { 1: 33, 2: 33, 3: 33 }
    assert rep[ "decision" ] == "default pack size 200" and rep[ "next_step" ] == "evaluate"


def test_real_answers_of_one_question_alone_read_inconclusive_and_ask_for_question_two():
    fx   = json.loads( REAL.read_text() )
    ov   = { r[ "id" ]: 0.0 for r in fx[ "answers" ] }
    recs = [ _arm( n, ov, size=s, answers=fx[ "answers" ] ) for n, s in ( ( "single1", 1 ), ( "single2", 1 ), ( "pack10", 10 ), ( "pack50", 50 ), ( "pack200", 200 ) ) ]
    recs += _extra_arms( 1, ov, fx[ "answers" ] )
    rep  = an.build_report( recs, canaries=[] )
    assert rep[ "evaluate" ][ "boundary_pooled" ] == 33 and rep[ "next_step" ] == "run question 2"
    assert all( rep[ "evaluate" ][ "sizes" ][ s ][ "state" ] == "inconclusive" for s in an.PACK_SIZES )


# --- the command line ----------------------------------------------------------------------------------------------------

def test_the_command_reads_a_folder_of_arm_files_and_canary_files_and_prints_the_report(tmp_path, capsys):
    for rec in _question():
        (tmp_path / f"{rec[ 'run_name' ]}.json").write_text( json.dumps( rec ) )
    arm, can = _canary( [ _row() ] )
    (tmp_path / "s1-q1-canary.canary.json").write_text( json.dumps( can ) )
    (tmp_path / "s1-q1-canary.json").write_text( json.dumps( arm ) )
    assert an.main( [ str( tmp_path ) ] ) == 0
    out = capsys.readouterr().out
    assert "default pack size 200" in out and "canary" in out


def test_the_command_with_an_empty_folder_says_there_is_nothing_to_read(tmp_path, capsys):
    assert an.main( [ str( tmp_path ) ] ) == 2
    assert "no arm files" in capsys.readouterr().out


# --- canary retries and the sixth trip -----------------------------------------------------------------------------------

def test_a_canary_that_sent_no_request_trips_nothing_measured():
    for rows in ( [], [ _row( tokens_in=None, tokens_out=None, reserve=None, status="not_reached", attempts=0 ) ] ):
        assert an.check_canary( *_canary( rows ) )[ "tripped" ] == [ "nothing_measured" ], rows
    assert an.check_canary( *_canary( [ _row() ] ) )[ "tripped" ] == []


def test_the_canary_attempts_of_one_question_are_read_side_by_side_by_attempt():
    first  = _arm( "canary", { "a": 0.1 }, size=10 )
    second = _arm( "canary", { "a": 0.1 }, size=10, run_name="s1-q1-canary-a2", attempt=2, retry_reason="refused" )
    st = an.read_stage( [ first, second ] )
    assert sorted( st[ 1 ] ) == [ "canary", "canary-a2" ]
    assert ( st[ 1 ][ "canary" ][ "attempt" ], st[ 1 ][ "canary-a2" ][ "attempt" ] ) == ( 1, 2 )
    assert st[ 1 ][ "canary-a2" ][ "retry_reason" ] == "refused" and st[ 1 ][ "canary" ][ "retry_reason" ] is None


def test_a_third_attempt_is_a_third_key_and_the_same_attempt_twice_is_refused():
    recs = [ _arm( "canary", { "a": 0.1 }, size=10, run_name=f"r{a}", attempt=a ) for a in ( 1, 2, 3 ) ]
    assert sorted( an.read_stage( recs )[ 1 ] ) == [ "canary", "canary-a2", "canary-a3" ]
    with pytest.raises( ValueError, match="given twice" ):
        an.read_stage( [ recs[ 1 ], dict( recs[ 1 ], run_name="other" ) ] )


def test_the_cost_skips_a_question_with_no_pack_arm_of_the_default_size_and_has_no_mean_without_any():
    a = _arm( "pack200", { "a": 0.1 }, size=200 ); a[ "totals" ][ "spent_tokens" ] = 1_000_000
    b = _arm( "pack50", { "a": 0.1 }, question=2, size=50 )
    c = an.cost_per_search( an.read_stage( [ a, b ] ), 200 )
    assert sorted( c, key=str ) == [ 1, "mean_dollars" ] and c[ "mean_dollars" ] == 0.042
    assert an.cost_per_search( an.read_stage( [ b ] ), 200 ) == { "mean_dollars": None }


def test_the_command_refuses_a_canary_file_with_no_arm_file_beside_it(tmp_path):
    (tmp_path / "s1-q1-single1.json").write_text( json.dumps( _arm( "single1", { "a": 0.1 } ) ) )
    (tmp_path / "s1-q1-canary.canary.json").write_text( json.dumps( { "tripped": [], "run_name": "s1-q1-canary" } ) )
    with pytest.raises( ValueError, match="no arm file" ):
        an.main( [ str( tmp_path ) ] )


def test_an_old_arm_that_shares_no_entry_with_single_run_one_has_no_percentile_and_no_maximum():
    s1  = _arm( "single1", { "a": 0.5 } ); old = _arm( "old", { "zzz": 0.5 }, run_name=NO_NAME )
    r   = an.old_shape_report( an.read_stage( [ s1, old ] ) )[ 1 ]
    assert ( r[ "hits" ], r[ "p99" ], r[ "max" ], r[ "boundary_flips" ] ) == ( 1, None, None, 0 )


# --- ruling R1: lost entries ---------------------------------------------------------------------------------------------

def _lossy( n, lost, arm="single1", **over ):
    """Ensures: returns an arm of n entries whose first `lost` ids failed with no answer."""
    ids  = [ f"e{k:05d}" for k in range( n ) ]
    rec  = _arm( arm, { i: 0.05 for i in ids }, **over )
    rec[ "answers" ] = rec[ "answers" ][ lost: ]
    rec[ "failed" ]  = ids[ :lost ]
    return rec


def test_the_lost_entry_limit_is_one_in_two_hundred_rounded_down():
    assert an.LOST_ONE_IN == 200
    assert [ an.lost_limit( n ) for n in ( 0, 1, 199, 200, 399, 400, 7705, 7800 ) ] == [ 0, 0, 0, 1, 1, 2, 38, 39 ]


def test_an_arm_of_7705_entries_may_lose_38_and_no_more_to_be_judged():
    ok  = an.read_arm( _lossy( 7705, 38 ) )
    bad = an.read_arm( _lossy( 7705, 39 ) )
    assert ( ok[ "status" ], len( ok[ "lost" ] ), ok[ "lost_limit" ] ) == ( "clean", 38, 38 )
    assert ( bad[ "status" ], len( bad[ "lost" ] ), bad[ "lost_limit" ] ) == ( "inconclusive", 39, 38 )


def test_a_lost_entry_is_one_failed_unasked_unreached_malformed_or_simply_without_an_answer_counted_once():
    rec = _arm( "single1", { f"e{k:03d}": 0.05 for k in range( 1000 ) } )
    rec[ "answers" ] = rec[ "answers" ][ 5: ]                                          # five ids have no answer: e000 to e004
    rec[ "failed" ], rec[ "unasked" ], rec[ "not_reached" ] = [ "e000", "e005" ], [ "e000", "e006" ], [ "e007" ]
    rec[ "answers" ][ 0 ][ "probabilities" ] = None                                    # e005 is malformed (it also sits in `failed`)
    a = an.read_arm( rec )
    assert a[ "lost" ] == [ "e000", "e001", "e002", "e003", "e004", "e005", "e006", "e007" ]
    assert a[ "lost_limit" ] == 5 and a[ "status" ] == "inconclusive"


def test_an_id_listed_as_lost_that_the_arm_never_asked_about_still_counts():
    rec = _arm( "single1", { "a": 0.05 }, failed=[ "ghost" ] )
    assert an.read_arm( rec )[ "lost" ] == [ "ghost" ]


def test_an_arm_that_ran_out_of_attempts_is_judged_by_its_lost_entries_not_by_the_stop():
    ok  = _lossy( 400, 2, state="incomplete", stop_reason="attempts" ); ok[ "not_reached" ] = ok.pop( "failed" ) and [ f"e{k:05d}" for k in range( 2 ) ]; ok[ "failed" ] = []
    bad = _lossy( 400, 3, state="incomplete", stop_reason="attempts" )
    assert an.read_arm( ok )[ "status" ] == "clean" and an.read_arm( bad )[ "status" ] == "inconclusive"


def test_an_incomplete_arm_with_no_named_stop_is_inconclusive_however_few_entries_were_lost():
    assert an.read_arm( _lossy( 400, 0, state="incomplete" ) )[ "status" ] == "inconclusive"


def test_a_ceiling_stop_is_invalid_even_when_nothing_was_lost():
    assert an.read_arm( _lossy( 400, 0, state="incomplete", stop_reason="ceiling" ) )[ "status" ] == "invalid"


def test_an_arm_with_nothing_answered_is_inconclusive_whatever_the_limit_says():
    assert an.read_arm( _lossy( 400, 400 ) )[ "status" ] == "inconclusive"
    assert an.read_arm( _arm( "single1", {} ) )[ "status" ] == "inconclusive"


def test_a_comparison_is_pairwise_over_the_entries_answered_in_both_arms():
    s1 = _lossy( 400, 1 )                                                                   # loses e00000
    pk = _lossy( 400, 0, arm="pack10", size=10 ); pk[ "answers" ] = pk[ "answers" ][ :-1 ]; pk[ "failed" ] = [ "e00399" ]       # loses e00399
    st = an.read_stage( [ s1, pk ] )
    assert an.pass_one( st, 10, 0.02 )[ "n" ] == 398 and st[ 1 ][ "single1" ][ "status" ] == st[ 1 ][ "pack10" ][ "status" ] == "clean"


def test_the_boundary_count_is_taken_after_the_lost_entries_are_dropped():
    base = { **{ f"b{k:03d}": 0.5 for k in range( 91 ) }, **{ f"o{k:03d}": 0.05 for k in range( 309 ) } }          # 400 entries, 91 on the boundary
    s1   = _arm( "single1", base ); s1[ "answers" ] = s1[ "answers" ][ 2: ]; s1[ "failed" ] = [ "b000", "b001" ]
    st   = an.read_stage( [ s1 ] )
    assert st[ 1 ][ "single1" ][ "status" ] == "clean" and len( an.boundary_ids( st[ 1 ][ "single1" ] ) ) == 89
    assert an.evaluate( st )[ "boundary_pooled" ] == 89


def test_the_report_prints_the_lost_count_and_the_limit_beside_each_other_for_every_arm():
    text = an.render( an.build_report( _complete(), canaries=[] ) )
    assert "s1-q1-single1: lost 0 of limit 0" in text and "s1-q1-pack200: lost 0 of limit 0" in text and "s1-q1-page-pack: lost 0 of limit 0" in text
    lossy = an.render( an.build_report( [ _lossy( 7705, 40, size=1, run_name="s1-q1-single1" ) ], canaries=[] ) )
    assert "s1-q1-single1: lost 40 of limit 38" in lossy


# --- ruling R2: pass 3 and a question with no probes -------------------------------------------------------------------------

def test_a_question_with_no_probe_arms_is_skipped_and_named_as_not_probed():
    r = an.pass_three( an.read_stage( _question( 1 ) + _question( 2, probes=False ) ), 0.02 )
    assert ( r[ "state" ], r[ "placements" ], r[ "not_probed" ] ) == ( "pass", 6, [ 2 ] )


def test_a_question_with_one_to_five_placements_makes_pass_three_inconclusive_even_beside_a_full_one():
    for kept in range( 1, 6 ):
        q2 = _question( 2, probes=False ) + _probes( 2, "e000", _base() )[ :kept ]
        r  = an.pass_three( an.read_stage( _question( 1 ) + q2 ), 0.02 )
        assert r[ "state" ] == "inconclusive", kept


def test_pass_three_reads_pass_only_when_at_least_one_question_has_all_six():
    assert an.pass_three( an.read_stage( _question( 1, probes=False ) + _question( 2, probes=False ) ), 0.02 )[ "state" ] == "inconclusive"
    assert an.pass_three( an.read_stage( _question( 1 ) ), 0.02 )[ "state" ] == "pass"


def test_beside_the_default_the_report_says_sizes_ten_and_fifty_carry_no_position_evidence():
    rep  = an.build_report( _complete(), canaries=[] )
    text = an.render( rep )
    assert rep[ "decision" ] == "default pack size 200" and "pass 3 was run at size 200 only" in text
    assert "sizes 10 and 50 carry no position evidence" in text


def test_the_report_names_the_questions_that_were_not_probed():
    text = an.render( an.build_report( _complete( 1 ) + _question( 2, probes=False ) + _extra_arms( 2, _base() ), canaries=[] ) )
    assert "not probed: question 2" in text


# --- ruling R3: the next step looks at the arms ------------------------------------------------------------------------------

ALL_ARMS = [ "single1", "canary", "single2", "pack10", "pack50", "pack200", "page-single1", "page-single2", "page-pack",
             "probe-first-random", "probe-first-near", "probe-middle-random", "probe-middle-near", "probe-last-random", "probe-last-near" ]


def test_the_arms_a_question_must_have_are_the_fifteen_the_plan_runs():
    assert list( an.REQUIRED_ARMS ) == ALL_ARMS


def test_with_only_single_run_one_present_the_next_step_names_the_remaining_arms_in_order():
    r = an.stop_rules( an.read_stage( [ _with_boundary( 1, 3 ) ] ) )
    assert r[ "stop" ] is False
    assert r[ "next_step" ] == "run question 1's remaining arms: " + ", ".join( ALL_ARMS[ 1: ] )


def test_a_whole_first_question_gives_run_question_two_and_a_whole_second_gives_run_question_three():
    one = an.stop_rules( an.read_stage( _complete( 1 ) ) )
    two = an.stop_rules( an.read_stage( _complete( 1 ) + _complete( 2 ) ) )
    assert one[ "next_step" ] == "run question 2" and two[ "next_step" ] in ( "run question 3", "stop and ask: under 50 pooled boundary entries after question 2" )


def test_the_first_question_with_arms_missing_is_named_even_when_a_later_question_has_started():
    recs = [ r for r in _complete( 1 ) if r[ "arm" ] != "pack200" ] + [ _with_boundary( 2, 3 ) ]
    r = an.stop_rules( an.read_stage( recs ) )
    assert r[ "next_step" ] == "run question 1's remaining arms: pack200"


def test_a_canary_retry_is_not_a_required_arm_and_does_not_stand_in_for_one():
    recs = [ r for r in _complete( 1 ) if r[ "arm" ] != "canary" ] + [ _arm( "canary", { "a": 0.1 }, size=10, run_name="s1-q1-canary-a2", attempt=2 ) ]
    assert an.stop_rules( an.read_stage( recs ) )[ "next_step" ] == "run question 1's remaining arms: canary"


def test_a_spend_stop_and_an_unclean_single_run_come_before_the_remaining_arms():
    spent = _spend( 1, 16_000_000 )
    assert an.stop_rules( an.read_stage( [ spent ] ) )[ "next_step" ] == "stop and ask: spend after question 1 above 15,000,000 tokens"
    bad = _with_boundary( 1, 3 ); bad[ "failed" ] = [ "x" ]
    assert an.stop_rules( an.read_stage( [ bad ] ) )[ "next_step" ] == "stop and ask: question 1's single run 1 is not clean"


def test_the_arm_check_can_be_left_off_to_read_the_rules_alone():
    assert an.stop_rules( an.read_stage( [ _with_boundary( 1, 3 ) ] ), check_arms=False )[ "next_step" ] == "run question 2"
