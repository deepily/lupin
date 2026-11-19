"""
The extractor replay over the synthetic 50-target export, through the one replay harness.

Everything here is synthetic. The model is a canned double and the embeddings are stand-in vectors,
so nothing reaches a live model, the embedding service or a GPU. The real-data half is in
test_local_data_extractor_replay.py and runs in the main checkout.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import extractor_replay as er
from cosa.research.preference_replay.replay_loop import ENGINE_ARM
from cosa.research.preference_replay.scratch_db import load_export, scratch_session, session_scope
from cosa.rest.postgres_models import Notification, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment

FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "episode_view", "synthetic-context-50.json" )
OWNER   = "00000000-0000-4000-8000-0000000000ab"
T0      = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )


@pytest.fixture( scope="module" )
def export():
    """
    Load the synthetic export once.

    Ensures:
        - returns the parsed JSON with targets and records
    """
    with open( FIXTURE, encoding="utf-8" ) as handle: return json.load( handle )


@pytest.fixture
def engine():
    """
    Give the real engine, with embedding made to fail so a stored vector must be used.

    Ensures:
        - yields a PredictionEngine; the singleton is reset before and after
    """
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


@pytest.fixture
def loaded( export ):
    """
    Give a scratch session with the export loaded.

    Ensures:
        - yields an open session over 160 notifications and empty principle tables
    """
    with scratch_session() as session:
        load_export( session, export )
        yield session


@pytest.fixture( scope="module" )
def instant( export ):
    """
    Run the zero-lag replay once for the tests that only read its result.

    Ensures:
        - yields ( session, result, engine ) with the session still open over the filled tables
        - the engine singleton is reset when the module's tests end
    """
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    with scratch_session() as session:
        load_export( session, export )
        yield session, er.run_replay( session, eng, timedelta( 0 ), query_fn=er.canned_model ), eng
    PredictionEngine.reset()


def _replay( session, engine, lag=timedelta( 0 ) ):
    """
    Run the replay with the canned model.

    Ensures:
        - returns run_replay's result
    """
    return er.run_replay( session, engine, lag, query_fn=er.canned_model )


def test_the_export_loads_every_notification_once_with_uuid_ids_and_aware_times( export, loaded ):
    assert loaded.query( Notification ).count() == 160
    row = loaded.query( Notification ).filter( Notification.responded_at.isnot( None ) ).first()
    assert isinstance( row.id, uuid.UUID ) and isinstance( row.recipient_id, uuid.UUID )
    assert er.aware_moment( row.created_at ).tzinfo is not None
    with scratch_session() as other:
        assert load_export( other, export ) == 160


def test_the_replay_runs_every_answered_ask_in_time_order_through_the_one_harness_and_fills_the_tables( instant ):
    out = instant[ 1 ]
    records = out[ "run" ][ "records" ]
    assert len( records[ ENGINE_ARM ] ) == 140 and len( records[ er.RECORDER_ARM ] ) == 140 and out[ "run" ][ "not_replayable" ] == 0
    times = [ r[ "asked_at" ] for r in out[ "seen" ] ]
    assert times == sorted( times ) and len( out[ "seen" ] ) == 140
    assert out[ "counts" ] == { "principles": 2, "evidence": 85 } and len( out[ "extractions" ] ) == 140
    assert { e[ "summary" ][ "status" ] for e in out[ "extractions" ] } == { "extracted" }
    assert out[ "leakage_checked" ] > 0


def test_a_second_run_over_a_fresh_copy_repeats_the_counts_and_the_principle_list( export, engine ):
    results = []
    for _ in range( 2 ):
        with scratch_session() as session:
            load_export( session, export )
            out = _replay( session, engine )
            results.append( ( out[ "counts" ], out[ "leakage_checked" ], er.principle_list( session ) ) )
    assert results[ 0 ] == results[ 1 ] and results[ 0 ][ 0 ] == { "principles": 2, "evidence": 85 }


def test_extracting_the_same_answers_again_in_the_same_tables_adds_nothing( instant ):
    session, first, engine = instant
    asks   = er.asks_from_session( session, engine )
    runner = er.ExtractorReplay( session, asks, timedelta( 0 ), query_fn=er.canned_model )
    runner.catch_up( T0 + timedelta( days=365 ) )
    assert { "principles": session.query( PreferencePrinciple ).count(), "evidence": session.query( PreferenceEvidence ).count() } == first[ "counts" ]
    assert len( runner.summaries ) == 140 and all( s[ "summary" ][ "evidence_written" ] == 0 for s in runner.summaries )


def test_evidence_is_extracted_exactly_the_lag_after_the_answer_and_no_arm_sees_it_early( loaded, engine ):
    lag = timedelta( minutes=20 )
    out = _replay( loaded, engine, lag )
    for evidence in loaded.query( PreferenceEvidence ):
        assert aware_moment( evidence.extracted_at ) - aware_moment( evidence.answered_at ) == lag
    assert out[ "counts" ] == { "principles": 2, "evidence": 85 }
    early = [ r for r in out[ "seen" ] if r[ "principles" ] ]
    assert len( early ) < len( out[ "seen" ] ) and out[ "leakage_checked" ] > 0


def test_the_first_ask_sees_no_principles_the_last_sees_some_and_a_lag_longer_than_the_run_hides_them_all_from_every_arm( export, engine, instant ):
    evidence_seen = [ sum( len( p[ "evidence" ] ) for p in r[ "principles" ] ) for r in instant[ 1 ][ "seen" ] ]
    assert evidence_seen[ 0 ] == 0 and evidence_seen[ -1 ] > 0
    with scratch_session() as session:
        load_export( session, export )
        slow = _replay( session, engine, timedelta( days=30 ) )
    assert all( r[ "principles" ] == [] for r in slow[ "seen" ] ) and slow[ "leakage_checked" ] == 0
    assert slow[ "counts" ] == instant[ 1 ][ "counts" ], "the tables still fill once the run ends"


def test_principles_reach_the_arms_with_a_derived_status_and_later_ones_are_established_across_sessions( instant ):
    seen_status = { p[ "status" ] for r in instant[ 1 ][ "seen" ] for p in r[ "principles" ] }
    assert seen_status == { "hypothesis", "established" }
    assert [ p[ "status" ] for p in er.principles_as_of( instant[ 0 ], OWNER, T0 + timedelta( days=365 ), "replay-model:extractor-v1" ) ] == [ "established", "established" ]


def test_an_arm_is_never_handed_a_history_answer_given_after_its_ask( instant ):
    out = instant[ 1 ]
    with_history = 0
    for record in out[ "seen" ]:
        for entry in record[ "episode" ][ "history" ]:
            with_history += 1
            if entry[ "status" ] == "answered": assert aware_moment( entry[ "answer_known_at" ] ) <= record[ "asked_at" ]
    assert with_history > 0 and all( "answer" not in r[ "episode" ] for r in out[ "seen" ] )


def _evidence_record( asked, answered, extracted ):
    """
    Build one recorded arm call holding a single evidence row.

    Ensures:
        - returns a dict shaped as make_recorder records it
    """
    return { "ask_id": "a1", "asked_at": asked, "episode": {}, "principles": [ { "evidence": [ { "notification_id": "n1", "answered_at": answered, "extracted_at": extracted } ] } ] }


def test_a_leak_is_named_whether_the_answer_or_the_extraction_came_after_the_ask_and_a_tie_is_allowed():
    ask = T0
    assert er.check_no_leakage( [ _evidence_record( ask, ask, ask ) ] ) == 1
    assert er.check_no_leakage( [ _evidence_record( ask, ask - timedelta( seconds=1 ), ask - timedelta( seconds=1 ) ) ] ) == 1
    with pytest.raises( er.LeakageError, match="answered" ):
        er.check_no_leakage( [ _evidence_record( ask, ask + timedelta( seconds=1 ), ask ) ] )
    with pytest.raises( er.LeakageError, match="extracted" ):
        er.check_no_leakage( [ _evidence_record( ask, ask, ask + timedelta( seconds=1 ) ) ] )
    assert er.check_no_leakage( [] ) == 0 and er.check_no_leakage( [ { "ask_id": "a", "asked_at": ask, "episode": {}, "principles": [] } ] ) == 0


def test_principles_as_of_keeps_only_evidence_usable_at_the_moment_and_skips_a_principle_with_none( loaded ):
    principle = PreferencePrinciple( id=uuid.uuid4(), owner_id=OWNER, kind="decision", dimension="d", statement="s", scope="global", encoder_version="e", extractor_version="x" )
    loaded.add( principle )
    loaded.flush()
    for name, answered, extracted in ( ( "early", T0, T0 ), ( "late_answer", T0 + timedelta( hours=2 ), T0 ), ( "late_extract", T0, T0 + timedelta( hours=2 ) ) ):
        loaded.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=uuid.uuid4(), field_key=name, relation="supports", answered_at=answered,
                                        extracted_at=extracted, extractor_version="x", source="extractor" ) )
    other = PreferencePrinciple( id=uuid.uuid4(), owner_id=OWNER, kind="decision", dimension="d2", statement="s2", scope="global", encoder_version="e", extractor_version="x" )
    loaded.add( other )
    loaded.flush()
    loaded.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=other.id, notification_id=uuid.uuid4(), field_key="x", relation="supports", answered_at=T0 + timedelta( hours=3 ),
                                    extracted_at=T0 + timedelta( hours=3 ), extractor_version="x", source="extractor" ) )
    loaded.commit()
    got = er.principles_as_of( loaded, OWNER, T0 + timedelta( hours=1 ), "x" )
    assert [ ( p[ "id" ], p[ "status" ], [ e[ "field_key" ] for e in p[ "evidence" ] ] ) for p in got ] == [ ( str( principle.id ), "hypothesis", [ "early" ] ) ]
    assert er.principles_as_of( loaded, OWNER, T0 - timedelta( hours=1 ), "x" ) == []
    assert len( er.principles_as_of( loaded, OWNER, T0 + timedelta( hours=4 ), "x" ) ) == 2
    assert er.principles_as_of( loaded, "someone-else", T0 + timedelta( hours=4 ), "x" ) == [] and er.principles_as_of( loaded, OWNER, T0 + timedelta( hours=4 ), "other" ) == []


def test_the_extractor_runs_for_an_answer_before_the_first_ask_that_could_know_it_and_not_before( loaded, engine ):
    asks   = er.asks_from_session( loaded, engine )
    runner = er.ExtractorReplay( loaded, asks, timedelta( minutes=10 ), query_fn=er.canned_model )
    first  = min( aware_moment( a[ "responded_at" ] ) for a in asks )
    runner.catch_up( first + timedelta( minutes=9 ) )
    assert runner.summaries == []
    runner.catch_up( first + timedelta( minutes=10 ) )
    assert len( runner.summaries ) >= 1 and runner.summaries[ 0 ][ "notification_id" ] in [ a[ "id" ] for a in asks ]
    assert len( runner.pending ) == len( asks ) - len( runner.summaries )


def test_asks_are_built_from_stored_answers_with_stand_in_vectors_and_the_answer_source_by_attribution( loaded, engine ):
    asks = er.asks_from_session( loaded, engine )
    assert len( asks ) == 140 and asks == sorted( asks, key=lambda a: ( a[ "asked_at" ], a[ "id" ] ) )
    assert all( a[ "answer_source" ] == "human" and len( a[ "question_embedding" ] ) == er.EMBEDDING_DIM for a in asks )
    row = loaded.query( Notification ).filter( Notification.responded_at.isnot( None ) ).first()
    row.response_value = { "value": "yes", "source": "ui" }
    row.response_requested = True
    loaded.commit()
    unknown = [ a for a in er.asks_from_session( loaded, engine ) if a[ "answer_source" ] == "unknown" ]
    assert [ a[ "id" ] for a in unknown ] == [ str( row.id ) ]
    row.response_value = None
    loaded.commit()
    assert len( er.asks_from_session( loaded, engine ) ) == 139


def test_the_stand_in_vector_is_stable_has_the_stored_width_and_a_different_text_can_move_it():
    one = er.stand_in_vector( "Approve it?" )
    assert one == er.stand_in_vector( "Approve it?" ) and len( one ) == er.EMBEDDING_DIM and sorted( one )[ -1 ] == er.VECTOR_SCALE and one.count( 0.0 ) == er.EMBEDDING_DIM - 1
    assert er.stand_in_vector( "a" ) != er.stand_in_vector( "b" )


def test_the_canned_model_gives_a_grounded_hypothesis_for_each_answer_and_none_for_a_bare_yes():
    import asyncio
    answers = [ { "field_key": "answer", "answer": "no", "bare_yes": False, "possibly_influenced": False },
                { "field_key": "budget", "answer": "yes", "bare_yes": True, "possibly_influenced": False } ]
    prompt  = "CARD\n{}\n\nANSWERS\n" + json.dumps( answers ) + "\n\nEXISTING PRINCIPLES\n[]"
    async def collect():
        return [ message async for message in er.canned_model( prompt, None ) ]
    text   = asyncio.run( collect() )[ 0 ].content[ 0 ].text
    fields = json.loads( text )[ "fields" ]
    assert [ ( f[ "field_key" ], len( f[ "hypotheses" ] ) ) for f in fields ] == [ ( "answer", 1 ), ( "budget", 0 ) ]
    assert fields[ 0 ][ "hypotheses" ][ 0 ][ "condition" ] == "no"


def test_the_principle_list_is_sorted_with_relation_counts( instant ):
    listing = er.principle_list( instant[ 0 ] )
    assert [ ( p[ "dimension" ], p[ "scope" ] ) for p in listing ] == [ ( "decision.answer", "global" ), ( "decision.approve", "global" ) ]
    assert sum( p[ "supports" ] for p in listing ) == 85 and all( p[ "contradicts" ] == 0 and p[ "refines" ] == 0 for p in listing )


def test_session_scope_commits_on_a_clean_exit():
    with scratch_session() as session:
        with session_scope( session ) as inner:
            inner.add( PreferencePrinciple( id=uuid.uuid4(), owner_id="o", kind="decision", dimension="d", statement="s", scope="global", encoder_version="e", extractor_version="x" ) )
        session.rollback()
        assert session.query( PreferencePrinciple ).count() == 1


def test_main_replays_an_export_with_the_canned_model_and_writes_the_principle_list( tmp_path, capsys ):
    out = tmp_path / "principles.json"
    assert er.main( [ "--export", FIXTURE, "--out", str( out ), "--dry-run" ] ) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ line.split( ":" )[ 0 ] for line in lines if line.startswith( "lag" ) ] == [ "lag 0s", "lag 300s" ]
    assert all( "'principles': 2, 'evidence': 85" in line for line in lines if line.startswith( "lag" ) )
    assert [ p[ "dimension" ] for p in json.loads( out.read_text() ) ] == [ "decision.answer", "decision.approve" ]


def test_main_passes_a_given_model_through_and_takes_each_lag_asked_for( tmp_path, capsys ):
    out = tmp_path / "principles.json"
    assert er.main( [ "--export", FIXTURE, "--out", str( out ), "--lag-seconds", "60" ], query_fn=er.canned_model ) == 0
    assert [ line.split( ":" )[ 0 ] for line in capsys.readouterr().out.splitlines() if line.startswith( "lag" ) ] == [ "lag 60s" ]
