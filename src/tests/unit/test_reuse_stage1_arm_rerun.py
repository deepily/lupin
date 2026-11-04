"""
A stopped arm is run again under a new name with its own cache key; a finished arm is not.

The stopped run stays on the ledger and in its results file as incomplete. The rerun is `<arm>-a<n>`.
It has its own run index, so it reads none of the stopped run's answers. An arm that completed cannot be run again.
The driver here is the real `run_arm` on a stand-in transport.
"""
import json

import pytest

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as st
from tests.unit.test_reuse_stage1_driver import ENTRIES, LIMIT, NEED, Standin

TWO   = ENTRIES[ :2 ]
THREE = ENTRIES[ :3 ]


@pytest.fixture
def env( tmp_path ):
    """A driver environment on a scratch ledger; `made` collects the stand-ins it builds."""
    ledger = rl.AccountLedger.create( tmp_path / "ledger.jsonl", LIMIT, "test", "scratch" )
    made   = []

    def factory( budget, **kw ):
        made.append( Standin( budget, **{ **env.standin, **kw } ) )
        return made[ -1 ]

    env = st.Stage1Env( root=tmp_path, data=tmp_path / "data", ledger=ledger, transport_factory=factory, entries_in_index=len( ENTRIES ) )
    env.standin, env.made = {}, made
    return env


def sent( env ): return [ b for t in env.made for b in t.bodies ]


def result( env, name ): return json.loads( ( env.results_dir / f"{name}.json" ).read_text() )


def ledger_rows( env, name ):
    """Every ledger row written for one run name, in order."""
    rows = [ json.loads( line ) for line in env.ledger.path.read_text().splitlines() if line.strip() ]
    return [ r for r in rows if r.get( "run" ) == name ]


def stop_single1( env, entries=TWO ):
    """Ensures: returns the record of a single1 its ceiling stops before it sends."""
    return st.run_arm( env, 1, "single1", NEED, entries, 1 )


def test_a_stopped_arm_is_run_again_as_its_next_attempt_under_a_new_name( env ):
    first = stop_single1( env )
    assert first[ "state" ] == "incomplete" and first[ "stop_reason" ] == "ceiling"
    again = st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="the ceiling was set too low" )
    assert again[ "run_name" ] == "s1-q1-single1-a2" and again[ "attempt" ] == 2 and again[ "retry_reason" ] == "the ceiling was set too low"
    assert again[ "state" ] == "complete" and len( sent( env ) ) == 2


def test_the_stopped_run_stays_on_the_ledger_and_in_its_file_as_incomplete( env ):
    stop_single1( env )
    file_before, rows_before = ( env.results_dir / "s1-q1-single1.json" ).read_bytes(), ledger_rows( env, "s1-q1-single1" )
    assert rows_before and rows_before[ -1 ][ "kind" ] == "end"
    st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="again" )
    assert ( env.results_dir / "s1-q1-single1.json" ).read_bytes() == file_before and result( env, "s1-q1-single1" )[ "state" ] == "incomplete"
    assert ledger_rows( env, "s1-q1-single1" ) == rows_before
    assert [ r[ "kind" ] for r in ledger_rows( env, "s1-q1-single1-a2" ) ][ 0 ] == "begin"


def test_the_rerun_reads_none_of_the_stopped_runs_answers( env ):
    first = st.run_arm( env, 1, "single1", NEED, THREE, 500 )                    # the ceiling lets one question through, and its answer is cached
    assert first[ "stop_reason" ] == "ceiling" and len( first[ "answers" ] ) == 1 and len( sent( env ) ) == 1
    env.standin, before = {}, len( sent( env ) )
    again = st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt=2, reason="the transport died" )
    assert again[ "cache_hits" ] == 0 and len( sent( env ) ) - before == 3 and again[ "state" ] == "complete"
    assert again[ "run_index" ] != first[ "run_index" ]


def test_an_arm_that_completed_is_never_run_again( env ):
    st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000 )
    count, rows = len( sent( env ) ), env.ledger.path.read_bytes()
    with pytest.raises( st.DriverRefused, match="already complete" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="just to be sure" )
    assert len( sent( env ) ) == count and env.ledger.path.read_bytes() == rows and not ( env.results_dir / "s1-q1-single1-a2.json" ).exists()


def test_an_arm_is_not_run_a_third_time_once_its_second_attempt_completed( env ):
    stop_single1( env )
    st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="again" )
    with pytest.raises( st.DriverRefused, match="already complete" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=3, reason="once more" )
    assert not ( env.results_dir / "s1-q1-single1-a3.json" ).exists()


def test_an_arm_may_be_run_a_third_time_while_each_attempt_before_it_stopped( env ):
    stop_single1( env )
    st.run_arm( env, 1, "single1", NEED, TWO, 1, attempt=2, reason="still too low" )
    third = st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=3, reason="raised it" )
    assert third[ "run_name" ] == "s1-q1-single1-a3" and third[ "state" ] == "complete"


def test_an_arm_stopped_for_a_wrong_model_is_never_run_again_because_it_would_be_paid_for_twice( env ):
    env.standin = { "served": "jev-other" }
    assert st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000 )[ "stop_reason" ] == "model_mismatch"
    count, rows = len( sent( env ) ), env.ledger.path.read_bytes()
    with pytest.raises( st.DriverRefused, match="model_mismatch" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="try again" )
    assert len( sent( env ) ) == count and env.ledger.path.read_bytes() == rows and not ( env.results_dir / "s1-q1-single1-a2.json" ).exists()


def test_only_an_arm_stopped_by_its_ceiling_is_run_again( env ):
    def boom( budget ): raise RuntimeError( "disk full" )
    good = env.transport_factory
    env.transport_factory = boom
    with pytest.raises( RuntimeError ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000 )
    assert result( env, "s1-q1-single1" )[ "state" ] == "error"
    env.transport_factory = good
    with pytest.raises( st.DriverRefused, match="only an arm stopped by its ceiling" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="the disk was cleared" )
    assert not ( env.results_dir / "s1-q1-single1-a2.json" ).exists()


def test_a_third_attempt_is_refused_when_the_second_stopped_for_any_reason_but_the_ceiling( env ):
    stop_single1( env, THREE )
    second = st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt=2, reason="again", attempt_limit=1 )
    assert second[ "stop_reason" ] == "attempts"
    with pytest.raises( st.DriverRefused, match="attempt 2 stopped for attempts" ): st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt=3, reason="once more" )


def test_an_arm_that_spent_its_attempts_is_not_run_again_either( env ):
    first = st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt_limit=1 )
    assert first[ "stop_reason" ] == "attempts" and first[ "state" ] == "incomplete"
    with pytest.raises( st.DriverRefused, match="stopped for attempts" ): st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt=2, reason="again" )


def test_a_gated_arm_is_rerun_the_same_way_once_the_canary_is_approved( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    st.approve_canary( env, 1, "maria", "read it" )
    ten = ENTRIES[ 10:20 ]                                                       # not the canary's ten, whose answers pack10 would read from the cache
    assert st.run_arm( env, 1, "pack10", NEED, ten, 1 )[ "state" ] == "incomplete"
    again = st.run_arm( env, 1, "pack10", NEED, ten, 1_000_000, attempt=2, reason="ceiling" )
    assert again[ "run_name" ] == "s1-q1-pack10-a2" and again[ "state" ] == "complete"


def test_a_rerun_still_needs_the_attempt_before_it_and_a_reason( env ):
    with pytest.raises( st.DriverRefused, match="no earlier attempt" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="r" )
    stop_single1( env )
    with pytest.raises( st.DriverRefused, match="reason" ): st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2 )
    assert sent( env ) == []


def test_the_rerun_indexes_are_these_numbers():
    assert { st.retry_index( arm, n ) for arm in st.ARMS for n in ( 2, 3 ) } == set( range( 15, 45 ) )
    assert [ st.retry_index( "canary", n ) for n in ( 2, 3 ) ] == [ 15, 16 ]
    assert [ st.retry_index( "pack10", n ) for n in ( 2, 3 ) ] == [ 17, 18 ] and [ st.retry_index( "single1", n ) for n in ( 2, 3 ) ] == [ 41, 42 ]
    assert [ st.retry_index( "single2", n ) for n in ( 2, 3 ) ] == [ 43, 44 ]


def test_every_arm_and_attempt_has_a_run_index_no_other_arm_shares():
    retries = { ( arm, n ): st.retry_index( arm, n ) for arm in st.ARMS for n in ( 2, 3 ) }
    assert len( set( retries.values() ) ) == len( retries ) == 2 * len( st.ARMS )                       # no two reruns share an index
    assert not set( retries.values() ) & { index for index, _ in st.ARMS.values() }                      # and none is any first attempt's
    assert ( st.retry_index( "canary", 2 ), st.retry_index( "canary", 3 ) ) == ( 15, 16 )               # the canary keeps the indexes it has run under
    assert st.retry_index( "single1", 1 ) == st.ARMS[ "single1" ][ 0 ] and st.retry_index( "pack10", 1 ) == 3


def test_two_arms_of_one_size_do_not_read_each_others_reruns( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    st.approve_canary( env, 1, "maria", "read it" )
    stop_single1( env )
    st.run_arm( env, 1, "single1", NEED, TWO, 1_000_000, attempt=2, reason="again" )
    st.run_arm( env, 1, "single2", NEED, TWO, 1 )
    again = st.run_arm( env, 1, "single2", NEED, TWO, 1_000_000, attempt=2, reason="again" )
    assert again[ "cache_hits" ] == 0 and result( env, "s1-q1-single1-a2" )[ "run_index" ] != again[ "run_index" ]


def test_a_rerun_asks_the_entries_of_the_stopped_run_and_no_others( env ):
    stop_single1( env, THREE )
    other = ENTRIES[ 3:6 ]
    with pytest.raises( st.DriverRefused, match="not the entries of attempt 1" ): st.run_arm( env, 1, "single1", NEED, other, 1_000_000, attempt=2, reason="again" )
    with pytest.raises( st.DriverRefused, match="not the entries of attempt 1" ): st.run_arm( env, 1, "single1", NEED, THREE[ :2 ], 1_000_000, attempt=2, reason="again" )
    assert sent( env ) == [] and not ( env.results_dir / "s1-q1-single1-a2.json" ).exists()


def test_the_same_entries_in_another_order_are_other_entries( env ):
    stop_single1( env, THREE )
    with pytest.raises( st.DriverRefused, match="not the entries of attempt 1" ): st.run_arm( env, 1, "single1", NEED, THREE[ ::-1 ], 1_000_000, attempt=2, reason="again" )


def test_a_third_attempt_asks_the_entries_of_every_attempt_before_it( env ):
    stop_single1( env, THREE )
    st.run_arm( env, 1, "single1", NEED, THREE, 1, attempt=2, reason="still too low" )
    with pytest.raises( st.DriverRefused, match="not the entries of attempt 2" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ 3:6 ], 1_000_000, attempt=3, reason="other ids" )
    assert st.run_arm( env, 1, "single1", NEED, THREE, 1_000_000, attempt=3, reason="same ids" )[ "state" ] == "complete"
