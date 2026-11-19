"""
The extractor replay on the real 50-target context export (the `local_data` tier).

These tests read the owner's real context records from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent and each test skips by name.
The export is loaded into a throwaway in-memory copy and nothing is written back or committed.
The model is the canned double, so no live model is called.
This checks the plumbing on real rows, not what the real model would extract.
"""

import json
from datetime import timedelta

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import extractor_replay as er
from cosa.research.preference_replay.scratch_db import load_export, scratch_session
from cosa.utils.local_data_tier import require_local_file

CONTEXT_FILE_NAME = "2026.11.17-recent-predictions-sample-50-context.json"

pytestmark = pytest.mark.local_data


def _replayed( lag ):
    """
    Replay the real export once, in a fresh scratch copy.

    Ensures:
        - returns ( run_replay result, principle list )
        - skips by name when the export is absent
    """
    with open( require_local_file( CONTEXT_FILE_NAME ), encoding="utf-8" ) as handle: export = json.load( handle )
    PredictionEngine.reset()
    engine = PredictionEngine( debug=False )
    engine._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    try:
        with scratch_session() as session:
            load_export( session, export )
            out = er.run_replay( session, engine, lag, query_fn=er.canned_model )
            return out, er.principle_list( session )
    finally:
        PredictionEngine.reset()


def test_the_real_export_replays_fills_the_tables_and_no_arm_is_handed_a_later_row():
    out, listing = _replayed( timedelta( 0 ) )
    assert out[ "counts" ][ "principles" ] > 0 and out[ "counts" ][ "evidence" ] > 0 and listing
    assert out[ "leakage_checked" ] > 0 and len( out[ "seen" ] ) == len( out[ "run" ][ "records" ][ er.RECORDER_ARM ] ) > 0
    assert { e[ "summary" ][ "status" ] for e in out[ "extractions" ] } <= { "extracted", "skipped_not_attributed", "skipped_nothing_to_read", "skipped_no_input", "unparseable" }


def test_a_second_run_over_the_real_export_repeats_the_counts_and_the_list():
    first, first_list   = _replayed( timedelta( 0 ) )
    second, second_list = _replayed( timedelta( 0 ) )
    assert first[ "counts" ] == second[ "counts" ] and first_list == second_list and first[ "leakage_checked" ] == second[ "leakage_checked" ]
