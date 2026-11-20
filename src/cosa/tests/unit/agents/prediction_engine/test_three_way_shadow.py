"""
The three-way challenger in shadow on a live yes/no ask.

The loader and the engine run on in-memory SQLite through the real models and the real get_db.
Only its session factory is replaced. Ids carry a hex letter, because SQLite reads an all-digit id back as a number.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db  # noqa: F401  registers the SQLite type hooks, JSONB and Vector included
from cosa.agents.prediction_engine import three_way_shadow as shadow
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository
from cosa.rest.db.vector_store_models import PredictionDecision
from cosa.rest.postgres_models import Notification, PredictionLog

OWNER  = "b0000000-0000-4000-8000-00000000000a"
SENDER = "claude.code@lupin.deepily.ai#00000001"
T0     = datetime( 2026, 11, 1, 12, 0, tzinfo=timezone.utc )


def nid( n ): return uuid.UUID( f"a0000000-0000-4000-8000-{n:012x}" )


@pytest.fixture
def db( monkeypatch ):
    eng = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in ( Notification, PredictionLog, PredictionDecision ): model.__table__.create( eng )
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", lambda: Session( eng ) )
    yield eng
    eng.dispose()


def add_case( eng, n, value, vector, owner=OWNER, answered=True, source="human", logged_asked=True, rtype="yes_no", decision=True ):
    with Session( eng ) as s:
        s.add( Notification( id=nid( n ), recipient_id=uuid.UUID( OWNER ), sender_id=SENDER, title=f"t{n}", message=f"Should it proceed {n}?",
                             type="task", priority="low", response_requested=True, created_at=T0 + timedelta( minutes=n ) ) )
        s.add( PredictionLog( id=nid( 100 + n ), notification_id=nid( n ), response_type=rtype, category="permission",
                              prediction_confidence=0.5, prediction_strategy="s", similar_case_count=0,
                              asked_at=T0 + timedelta( minutes=n ) if logged_asked else None,
                              responded_at=T0 + timedelta( minutes=n, seconds=30 ) if answered else None ) )
        if decision:
            s.add( PredictionDecision( id=str( nid( n ) ), question=f"Should it proceed {n}?", category="permission", decision_value=value,
                                       ratification_state="not_required", data_origin="organic", response_type=rtype,
                                       question_embedding=vector, created_at="x", owner_user_id=owner, answer_source=source ) )
        s.commit()


def vec( x ): return [ x, 1.0 - x ] + [ 0.0 ] * 766


def test_live_cases_read_the_fields_the_challenger_needs_in_answer_order( db ):
    add_case( db, 2, "no", vec( 0.5 ), logged_asked=False )
    add_case( db, 1, "yes", vec( 0.25 ) )
    with Session( db ) as s: cases = shadow.live_cases( s, OWNER )
    assert [ c[ "id" ] for c in cases ] == [ str( nid( 1 ) ), str( nid( 2 ) ) ]
    first, second = cases
    assert first[ "decision_value" ] == "yes" and first[ "answer_source" ] == "human" and first[ "owner_user_id" ] == OWNER
    assert first[ "title" ] == "t1" and first[ "sender_id" ] == SENDER and first[ "category" ] == "permission"
    assert first[ "question_embedding" ][ :2 ] == pytest.approx( [ 0.25, 0.75 ] )
    assert first[ "asked_at" ].replace( tzinfo=None ) == ( T0 + timedelta( minutes=1 ) ).replace( tzinfo=None )
    assert second[ "asked_at" ] is not None, "an unstamped ask falls back to the notification's creation time"


def test_live_cases_leave_out_unanswered_other_owner_other_type_and_decisionless_asks( db ):
    add_case( db, 1, "yes", vec( 0.2 ), answered=False )
    add_case( db, 2, "yes", vec( 0.2 ), owner="someone-else" )
    add_case( db, 3, "yes", vec( 0.2 ), rtype="open_ended" )
    add_case( db, 4, "yes", vec( 0.2 ), decision=False )
    add_case( db, 5, "yes", None )
    add_case( db, 6, "no", vec( 0.2 ) )
    with Session( db ) as s: cases = shadow.live_cases( s, OWNER )
    assert [ c[ "id" ] for c in cases ] == [ str( nid( 5 ) ), str( nid( 6 ) ) ]
    assert cases[ 0 ][ "question_embedding" ] is None


def test_stance_of_and_unavailable_shapes():
    forecast = { "value": "no", "qualifier": "q", "confidence": 0.6, "probabilities": { "yes": 0.2, "no": 0.6, "neither": 0.2 },
                 "neighbour_ids": [ "a", "b" ], "levels": {} }
    assert shadow.stance_of( forecast ) == { "value": "no", "qualifier": "q", "confidence": 0.6,
                                             "probabilities": forecast[ "probabilities" ], "neighbours": 2 }
    assert shadow.unavailable( "no_embedding" ) == { "status": "no_embedding" }
    assert shadow.unavailable( "error", "KeyError" ) == { "status": "error", "error_class": "KeyError" }


def test_set_three_way_shadow_writes_one_column_and_reports_a_missing_row( db ):
    add_case( db, 1, "yes", vec( 0.2 ), answered=False )
    with Session( db ) as s:
        repo = PredictionLogRepository( s )
        assert repo.set_three_way_shadow( str( nid( 1 ) ), { "value": "yes" } ) is True
        assert repo.set_three_way_shadow( str( nid( 9 ) ), { "value": "yes" } ) is False
        s.commit()
    with Session( db ) as s:
        row = s.query( PredictionLog ).one()
        assert row.three_way_shadow == { "value": "yes" } and row.prediction_strategy == "s" and row.predicted_value is None


class _Classifier:
    def classify( self, message, sender_id=None ): return "permission", 0.9


@pytest.fixture
def engine( monkeypatch ):
    PredictionEngine.reset()
    eng = PredictionEngine( debug=True )
    eng.classifier = _Classifier()
    monkeypatch.setattr( eng, "_generate_embedding", lambda text: vec( 0.25 ) )
    yield eng
    PredictionEngine.reset()


def ask_dict( n=9, **over ):
    base = { "message": f"Should it proceed {n}?", "response_type": "yes_no", "sender_id": SENDER, "recipient_id": OWNER, "title": f"t{n}" }
    base.update( over )
    return base


def stored( eng ):
    with Session( eng ) as s: return s.query( PredictionLog ).filter( PredictionLog.notification_id == nid( 9 ) ).one().three_way_shadow


def test_the_switch_is_off_by_default_and_nothing_is_read_or_written( db, engine, monkeypatch ):
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    assert engine.three_way_enabled is False
    monkeypatch.setattr( shadow, "live_cases", lambda *a: pytest.fail( "read with the switch off" ) )
    monkeypatch.setattr( engine, "_generate_embedding", lambda t: pytest.fail( "embedded with the switch off" ) )
    assert engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict() ) is None
    assert stored( db ) is None


def test_an_ask_that_is_not_yes_no_is_left_alone_even_with_the_switch_on( db, engine ):
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    assert engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict( response_type="open_ended" ) ) is None
    assert stored( db ) is None


def test_with_the_switch_on_the_stance_is_stored_beside_the_forecast_row_and_nothing_else_changes( db, engine ):
    for n in range( 1, 6 ): add_case( db, n, "no", vec( 0.25 ) )
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    with Session( db ) as s: before = { c.name: getattr( s.query( PredictionLog ).filter( PredictionLog.notification_id == nid( 9 ) ).one(), c.name ) for c in PredictionLog.__table__.columns }
    got = engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict(), asked_at=T0 + timedelta( days=1 ) )
    assert got[ "value" ] == "no", "five identical earlier 'no' answers must carry the stance"
    assert got[ "neighbours" ] == 5 and sum( got[ "probabilities" ].values() ) == pytest.approx( 1.0 )
    assert stored( db ) == got
    with Session( db ) as s: after = { c.name: getattr( s.query( PredictionLog ).filter( PredictionLog.notification_id == nid( 9 ) ).one(), c.name ) for c in PredictionLog.__table__.columns }
    after.pop( "three_way_shadow" ); before.pop( "three_way_shadow" )
    assert after == before


def test_an_ask_without_a_stamp_uses_now( db, engine ):
    add_case( db, 1, "no", vec( 0.25 ) )
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    assert engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict() )[ "neighbours" ] == 1


def test_no_embedding_is_stored_as_a_named_status( db, engine, monkeypatch ):
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    monkeypatch.setattr( engine, "_generate_embedding", lambda t: None )
    assert engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict() ) == { "status": "no_embedding" }
    assert stored( db ) == { "status": "no_embedding" }


def test_a_failure_in_the_challenger_is_stored_with_its_class_and_never_raised( db, engine, monkeypatch ):
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    monkeypatch.setattr( shadow, "live_cases", lambda *a: ( _ for _ in () ).throw( KeyError( "x" ) ) )
    assert engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict() ) == { "status": "error", "error_class": "KeyError" }
    assert stored( db ) == { "status": "error", "error_class": "KeyError" }


def test_a_failed_write_is_swallowed_and_the_stance_still_returned( db, engine, monkeypatch ):
    add_case( db, 9, "yes", vec( 0.25 ), answered=False )
    engine.three_way_enabled = True
    monkeypatch.setattr( PredictionLogRepository, "set_three_way_shadow", lambda self, n, s: ( _ for _ in () ).throw( RuntimeError( "db" ) ) )
    got = engine.record_three_way_shadow( str( nid( 9 ) ), ask_dict() )
    assert got[ "value" ] == "yes" and stored( db ) is None
