"""
The analysis reads a rerun of an arm its ceiling stopped and lists the stopped run.

Cheech's ruling: a completed rerun stands in only for an arm that was stopped by its ceiling.
An arm stopped for model mismatch still stops the stage, rerun or not. The earlier attempts
are listed as <arm>-a<n> and counted in spend, but they are not in the verdict. The canary is unchanged.
"""
from lupin_mcp import reuse_stage1_analysis as an
from tests.unit.test_reuse_stage1_analysis import _arm, _question

IDS = { "a": 0.1, "b": 0.9 }


def stopped( attempt=1, stop="ceiling", spent=700, **over ):
    """Ensures: returns the record of a single1 that was stopped before it answered anything."""
    name = "s1-q1-single1" + ( f"-a{attempt}" if attempt > 1 else "" )
    rec  = _arm( "single1", IDS, state="incomplete", stop_reason=stop, run_name=name, attempt=attempt, answers=[], not_reached=list( IDS ), **over )
    rec[ "totals" ] = { **rec[ "totals" ], "spent_tokens": spent }
    return rec


def done( attempt=2, spent=300, **over ):
    """Ensures: returns the record of a single1 that completed and answered every id."""
    rec = _arm( "single1", IDS, run_name=f"s1-q1-single1-a{attempt}", attempt=attempt, **over )
    rec[ "totals" ] = { **rec[ "totals" ], "spent_tokens": spent }
    return rec


def test_a_completed_rerun_stands_in_for_an_arm_its_ceiling_stopped_and_the_stopped_run_is_listed_beside_it():
    by_name = an.read_stage( [ stopped(), done() ] )[ 1 ]
    assert sorted( by_name ) == [ "single1", "single1-a1" ]
    assert by_name[ "single1" ][ "run_name" ] == "s1-q1-single1-a2" and by_name[ "single1" ][ "attempt" ] == 2 and by_name[ "single1" ][ "superseded" ] is False
    assert by_name[ "single1" ][ "stands_in_for" ] == [ "s1-q1-single1" ]
    assert by_name[ "single1-a1" ][ "run_name" ] == "s1-q1-single1" and by_name[ "single1-a1" ][ "superseded" ] is True and by_name[ "single1-a1" ][ "stands_in_for" ] == []


def test_an_arm_run_once_is_read_as_before():
    by_name = an.read_stage( [ done( attempt=1 ) ] )[ 1 ]
    assert list( by_name ) == [ "single1" ] and by_name[ "single1" ][ "superseded" ] is False and by_name[ "single1" ][ "stands_in_for" ] == []


def test_the_stopped_run_is_counted_in_spend_and_not_in_the_verdict():
    stage = an.read_stage( [ stopped(), done() ] )
    assert an.stop_rules( stage )[ "spent_by_question" ][ 1 ] == 700 + 300
    assert "invalid" not in an.stop_rules( stage )[ "next_step" ]
    control = an.stop_rules( an.read_stage( [ stopped() ] ) )
    assert control[ "stop" ] is True and "invalid (stop reason ceiling)" in control[ "next_step" ]


def test_an_arm_stopped_for_a_wrong_model_still_stops_the_stage_whatever_reran_it():
    by_name = an.read_stage( [ stopped( stop="model_mismatch" ), done() ] )[ 1 ]
    assert sorted( by_name ) == [ "single1", "single1-a2" ] and by_name[ "single1" ][ "run_name" ] == "s1-q1-single1"
    assert not by_name[ "single1" ][ "superseded" ] and not by_name[ "single1-a2" ][ "superseded" ]
    assert an.stop_rules( an.read_stage( [ stopped( stop="model_mismatch" ), done() ] ) )[ "stop" ] is True


def test_a_ceiling_stopped_run_whose_rows_show_a_wrong_model_is_not_replaced():
    row   = { "error": an.MODEL_MISMATCH_ERROR, "model": "jev-other" }
    stage = an.read_stage( [ stopped( rows=[ row ] ), done() ] )
    assert stage[ 1 ][ "single1" ][ "run_name" ] == "s1-q1-single1" and stage[ 1 ][ "single1" ][ "served_model" ] == "jev-other"
    assert an.stop_rules( stage )[ "stop" ] is True


def test_a_run_stopped_for_any_other_reason_is_not_replaced():
    for stop in ( "ledger", "consecutive_422", "attempts" ):
        by_name = an.read_stage( [ stopped( stop=stop ), done() ] )[ 1 ]
        assert sorted( by_name ) == [ "single1", "single1-a2" ] and by_name[ "single1" ][ "run_name" ] == "s1-q1-single1", stop


def test_a_rerun_that_did_not_complete_replaces_nothing():
    by_name = an.read_stage( [ stopped(), stopped( attempt=2 ) ] )[ 1 ]
    assert sorted( by_name ) == [ "single1", "single1-a2" ] and not any( a[ "superseded" ] for a in by_name.values() )


def test_the_third_attempt_stands_in_for_two_stopped_ones():
    by_name = an.read_stage( [ stopped(), stopped( attempt=2, spent=200 ), done( attempt=3 ) ] )[ 1 ]
    assert sorted( by_name ) == [ "single1", "single1-a1", "single1-a2" ] and by_name[ "single1" ][ "run_name" ] == "s1-q1-single1-a3"
    assert by_name[ "single1" ][ "stands_in_for" ] == [ "s1-q1-single1", "s1-q1-single1-a2" ]
    assert by_name[ "single1-a1" ][ "superseded" ] and by_name[ "single1-a2" ][ "superseded" ] and not by_name[ "single1" ][ "superseded" ]


def test_a_rerun_with_no_first_attempt_on_file_replaces_nothing():
    assert list( an.read_stage( [ done() ] )[ 1 ] ) == [ "single1-a2" ]


def test_the_canary_is_unchanged_a_rerun_never_stands_in_for_it():
    first = _arm( "canary", IDS, state="incomplete", stop_reason="ceiling", run_name="s1-q1-canary", size=10 )
    again = _arm( "canary", IDS, run_name="s1-q1-canary-a2", attempt=2, size=10 )
    by_name = an.read_stage( [ first, again ] )[ 1 ]
    assert sorted( by_name ) == [ "canary", "canary-a2" ] and not any( a[ "superseded" ] for a in by_name.values() )


def test_the_report_names_the_stopped_run_its_spend_and_the_run_that_replaced_it():
    report = an.build_report( [ stopped(), done() ], [] )
    assert report[ "superseded_arms" ] == [ { "run_name": "s1-q1-single1", "question": 1, "arm": "single1", "attempt": 1, "stop_reason": "ceiling",
                                              "spent_tokens": 700, "replaced_by": "s1-q1-single1-a2" } ]
    assert report[ "unclean_arms" ] == [] and not report[ "decision" ].startswith( "stop and ask: an arm is invalid" )
    assert "superseded: s1-q1-single1 (stop reason ceiling, 700 tokens) replaced by s1-q1-single1-a2" in an.render( report ).splitlines()


def test_a_report_with_no_rerun_lists_no_superseded_arm():
    report = an.build_report( [ done( attempt=1 ) ], [] )
    assert report[ "superseded_arms" ] == [] and "superseded" not in an.render( report )


def test_an_id_asked_twice_in_the_stopped_run_does_not_stop_the_decision():
    twice  = stopped( entry_ids=[ "a", "a", "b" ] )
    report = an.build_report( [ twice, done() ], [] )
    assert report[ "duplicate_ids" ] == [] and not report[ "decision" ].startswith( "stop and ask: an arm asks the same id twice" )


def test_a_rerun_probe_arm_counts_once_and_its_stopped_run_does_not_clash_with_it():
    recs     = _question()
    probe    = next( r for r in recs if r[ "arm" ] == "probe-first-random" )
    stopped  = { **probe, "state": "incomplete", "stop_reason": "ceiling", "answers": [], "not_reached": list( probe[ "entry_ids" ] ) }
    rerun    = { **probe, "run_name": probe[ "run_name" ] + "-a2", "attempt": 2 }
    result   = an.pass_three( an.read_stage( [ r for r in recs if r is not probe ] + [ stopped, rerun ] ), 0.02 )
    assert result == an.pass_three( an.read_stage( recs ), 0.02 ) and result[ "placements" ] == 6


def test_a_rerun_on_other_entries_does_not_stand_in_and_the_stopped_arm_still_stops_the_stage():
    other   = _arm( "single1", { "x": 0.3, "y": 0.8 }, run_name="s1-q1-single1-a2", attempt=2 )
    by_name = an.read_stage( [ stopped(), other ] )[ 1 ]
    assert sorted( by_name ) == [ "single1", "single1-a2" ] and by_name[ "single1" ][ "run_name" ] == "s1-q1-single1"
    assert not any( a[ "superseded" ] for a in by_name.values() )
    assert an.stop_rules( an.read_stage( [ stopped(), other ] ) )[ "stop" ] is True


def test_a_rerun_on_the_same_entries_in_another_order_does_not_stand_in():
    reordered = done( entry_ids=[ "b", "a" ] )
    assert sorted( an.read_stage( [ stopped(), reordered ] )[ 1 ] ) == [ "single1", "single1-a2" ]


def test_a_third_attempt_on_other_entries_than_the_second_does_not_stand_in():
    other = _arm( "single1", { "x": 0.3, "y": 0.8 }, run_name="s1-q1-single1-a3", attempt=3 )
    assert sorted( an.read_stage( [ stopped(), stopped( attempt=2 ), other ] )[ 1 ] ) == [ "single1", "single1-a2", "single1-a3" ]
