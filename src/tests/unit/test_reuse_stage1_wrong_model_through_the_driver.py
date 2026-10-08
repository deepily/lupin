"""
A response from another model, written by the real driver and read by the analysis.

The driver here is the real `run_arm` and `run_canary` on a stand-in transport that answers as
another model. Nothing reaches Jev and no real ledger is touched.
"""
import json

import pytest

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_stage1_analysis as an
from tests.unit.test_reuse_stage1_driver import ENTRIES, LIMIT, NEED, Standin

SERVED = "jev-9.9.9"


@pytest.fixture
def env( tmp_path ):
    """A driver environment on a scratch ledger whose stand-in answers as another model."""
    ledger = rl.AccountLedger.create( tmp_path / "ledger.jsonl", LIMIT, "test", "scratch" )
    made   = []

    def factory( budget, **kw ):
        made.append( Standin( budget, **{ "served": SERVED, **kw } ) )
        return made[ -1 ]

    return st.Stage1Env( root=tmp_path, data=tmp_path / "data", ledger=ledger, transport_factory=factory, entries_in_index=len( ENTRIES ) )


def read( env, name ):
    """Ensures: returns the results file of one run as the driver wrote it."""
    return json.loads( ( env.results_dir / f"{name}.json" ).read_text() )


def test_the_driver_writes_a_wrong_model_arm_with_the_stop_the_mismatch_row_and_the_name_served( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000 )
    rec = read( env, "s1-q1-single1" )
    bad = [ r for r in rec[ "rows" ] if r[ "error" ] == "ModelMismatch" ]
    assert rec[ "stop_reason" ] == "model_mismatch" and len( bad ) >= 1 and bad[ 0 ][ "model" ] == SERVED and rec[ "model" ] != SERVED


def test_the_analysis_reads_that_folder_as_invalid_and_stops_and_asks_naming_the_arm_and_both_models( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000 )
    rec = read( env, "s1-q1-single1" )
    rep = an.build_report( [ rec ], canaries=[] )
    assert rep[ "unclean_arms" ][ 0 ][ "status" ] == "invalid"
    assert rep[ "decision" ] == f"stop and ask: s1-q1-single1 was answered by {SERVED}, not {rec[ 'model' ]}; Rick decides whether another model is acceptable"
    assert rep[ "next_step" ].startswith( "stop and ask" )


def test_a_wrong_model_canary_is_tripped_by_name_by_the_driver_and_the_analysis_agrees( env ):
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    check  = an.check_canary( read( env, "s1-q1-canary" ), report )
    assert "model_mismatch" in report[ "tripped" ] and "model_mismatch" in check[ "tripped" ]
    assert check[ "agrees" ] and check[ "analysis_only" ] == [] and check[ "driver_only" ] == []


def test_the_command_over_a_wrong_model_canary_folder_stops_and_asks_and_prints_no_disagreement( env, capsys ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    assert an.main( [ str( env.results_dir ) ] ) == 0
    text = capsys.readouterr().out
    assert f"Decision: stop and ask: s1-q1-canary was answered by {SERVED}" in text and "driver agrees True; only here []; only driver []" in text


def test_the_wrong_model_trip_name_sits_after_usage_missing_and_before_incomplete():
    assert an.CANARY_TRIPS == ( "output_per_entry_over_60", "usage_over_reserve", "refusal", "usage_missing", "model_mismatch", "incomplete", "nothing_measured" )
