"""
One cohort, three counts: the replay, the admin report and a direct SQL count agree.

A throwaway Postgres holds a hand-written yes/no cohort. It has three windows and five rows no count may
include: a test override, an unscored row, two legacy rows and a multiple-choice row. Every flag is a
literal written here and never computed by the comparator. A stored flag that disagrees with the comparator
therefore shows up as a disagreement.

Three things must then agree. They are the admin report and a direct SQL count with the audit's window
instants written out. The third is the replay, run with an extra baseline arm that scores what the log
predicted. The replay's denominator is the asks it replayed plus the asks it could not replay.
"""

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.cohorts import WINDOW_NAMES, cohort_asks, scored_rows, window_of
from cosa.research.preference_replay.replay_loop import replay
from cosa.rest.auth_middleware import get_current_user
from cosa.rest.db.vector_store_models import EMBEDDING_DIM, PredictionDecision
from cosa.rest.postgres_models import Base, Notification, PredictionLog, User
from cosa.rest.routers.system import router

SHA    = "0" * 64
SENDER = "claude.code@lupin.deepily.ai#00000001"

# key, window instant, predicted, actual, stored match, has a stored vector, kind. Written by hand.
# The yes/no cohort: before 2 asks (1 right), undetermined 2 (1 right), after 3 (3 right); one of the seven has no vector.
_ROWS = [
    ( "y1", "2026-11-03T12:00:00+00:00", "yes", "yes",                          True,  True,  "counted" ),
    ( "y2", "2026-11-03T13:00:00+00:00", "yes", "no",                           False, True,  "counted" ),
    ( "y3", "2026-11-08T12:00:00+00:00", "no",  "no",                           True,  True,  "counted" ),
    ( "y4", "2026-11-08T13:00:00+00:00", "no",  "yes",                          False, False, "counted" ),
    ( "y5", "2026-11-12T12:00:00+00:00", "yes", "yes [comment: after review]",  True,  True,  "counted" ),
    ( "y6", "2026-11-12T13:00:00+00:00", "no",  "no",                           True,  True,  "counted" ),
    ( "y7", "2026-11-12T14:00:00+00:00", "yes", "yes",                          True,  True,  "counted" ),
    ( "x1", "2026-11-12T15:00:00+00:00", "yes", "yes",                          True,  True,  "test_override" ),
    ( "x2", "2026-11-12T16:00:00+00:00", "yes", None,                           None,  True,  "unscored" ),
    ( "x3", "2026-11-12T17:00:00+00:00", "yes", "yes",                          True,  True,  "legacy_confidence" ),
    ( "x4", "2026-11-12T18:00:00+00:00", "yes", "yes",                          True,  True,  "multiple_choice" ),
    ( "x5", "2026-11-12T19:00:00+00:00", "yes", "yes",                          True,  True,  "legacy_similarity" ),
]
LITERAL_ALL    = { "asks": 7, "right": 5 }
LITERAL_WINDOW = { "before": { "asks": 2, "right": 1 }, "undetermined": { "asks": 2, "right": 1 }, "after": { "asks": 3, "right": 3 } }

# The audit's window instants, written out as the audit query writes them.
_DIRECT_SQL = """
    SELECT CASE WHEN predicted_at <= '2026-11-04 15:54:58.965194+00' THEN 'before'
                WHEN predicted_at <  '2026-11-11 14:59:54.960998+00' THEN 'undetermined' ELSE 'after' END AS win,
           count(*) AS asks, count(*) FILTER ( WHERE accuracy_match IS TRUE ) AS right
      FROM prediction_log
     WHERE response_type = 'yes_no' AND accuracy_match IS NOT NULL
       AND coalesce( forecast_source, '' ) <> 'test_override' AND prediction_confidence <= 1.0
       AND coalesce( ( accuracy_detail->>'similarity' )::float, 0 ) <= 1.0 AND coalesce( ( accuracy_detail->>'avg_similarity' )::float, 0 ) <= 1.0
     GROUP BY 1 ORDER BY 1
"""


@pytest.fixture( scope="session" )
def cohort_tables( pg_engine ):
    """Create the three ledger tables beside the vector tables of the throwaway database."""
    Base.metadata.create_all( bind=pg_engine, tables=[ User.__table__, Notification.__table__, PredictionLog.__table__ ], checkfirst=True )
    return pg_engine


@pytest.fixture
def accuracy_session( cohort_tables, db_session ):
    """A rolled-back session on the throwaway database, with the ledger tables present."""
    return db_session


def _vector( axis ):
    """A stored-band vector on one basis axis."""
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ axis ] = 20.0
    return vector


def _plant( session ):
    """Insert a user, then per row a notification, a prediction_log row and maybe a decision."""
    uid = uuid.uuid4()
    session.add( User( id=uid, email=f"cohort-{uid.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                       is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
    session.flush()
    # Inserted newest first, so a query with no ORDER BY would not come back oldest first by luck.
    for axis, ( key, instant, predicted, actual, match, has_vector, kind ) in reversed( list( enumerate( _ROWS ) ) ):
        predicted_at = datetime.fromisoformat( instant )
        nid          = uuid.uuid4()
        session.add( Notification( id=nid, sender_id=SENDER, recipient_id=uid, title=f"Worker {key}", message=f"Should worker {key} proceed?",
                                   type="task", priority="high", created_at=predicted_at - timedelta( seconds=45 ),
                                   sender_persona="cohort", response_requested=True, state="created" ) )
        session.flush()
        answer = { "actual_value": { "value": actual }, "responded_at": predicted_at + timedelta( seconds=5 ) } if actual is not None else {}
        session.add( PredictionLog(
            notification_id=nid, response_type="multiple_choice" if kind == "multiple_choice" else "yes_no", category="input",
            predicted_value={ "value": predicted }, prediction_confidence=1.7 if kind == "legacy_confidence" else 0.9,
            prediction_strategy="cbr_majority_vote", similar_case_count=3, accuracy_match=match,
            forecast_source="test_override" if kind == "test_override" else None, predicted_at=predicted_at,
            asked_at=predicted_at - timedelta( seconds=30 ),
            accuracy_detail={ "similarity": 2.0 } if kind == "legacy_similarity" else None, **answer ) )
        if has_vector:
            session.add( PredictionDecision( id=str( nid ), question=f"Should worker {key} proceed?", category="input", decision_value=actual or "yes",
                                             ratification_state="not_required", data_origin="organic", response_type="yes_no",
                                             question_embedding=_vector( axis + 1 ), created_at=instant, owner_user_id=str( uid ),
                                             answer_source="human" ) )
    session.flush()


def _admin_report( session, **params ):
    """Call the admin route with get_db pointing at the throwaway session."""
    app = FastAPI()
    app.include_router( router )
    app.dependency_overrides[ get_current_user ] = lambda: { "uid": "admin-1", "email": "admin@example.com", "roles": [ "admin" ] }

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    with patch( "cosa.rest.db.database.get_db", fake_get_db ):
        return TestClient( app ).get( "/api/prediction-engine/accuracy", params=params ).json()


@pytest.fixture
def engine():
    """The real engine, with embedding generation made to fail so a stored vector must be used."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


def _stored_vectors( session ):
    """The planted case rows' vectors by ask id, standing in for a side file."""
    return { row.id: list( row.question_embedding ) for row in session.query( PredictionDecision ).all() if row.question_embedding is not None }


def _logged_arm():
    """A baseline arm whose forecast is what the log recorded for the ask."""
    return { "logged": lambda ask, visible_rows: ask[ "logged_value" ] }


def _run( engine, session, window=None ):
    """Replay one cohort with the logged arm and count what that arm got right, replayed or not."""
    asks   = cohort_asks( session, "yes_no", window, vectors=_stored_vectors( session ) )
    run    = replay( asks, engine, SHA, baselines=_logged_arm() )
    right  = sum( 1 for record in run[ "records" ][ "logged" ] if record[ "meta" ][ "correct" ] )
    missed = sum( 1 for ask in asks if ask[ "id" ] in run[ "not_replayable_ids" ] and ask[ "logged_match" ] is True )
    return asks, run, right + missed


def test_replay_admin_report_and_direct_count_agree_on_the_whole_cohort( accuracy_session, engine ):
    _plant( accuracy_session )
    direct = accuracy_session.execute( text( _DIRECT_SQL ) ).all()
    assert sum( row.asks for row in direct ) == LITERAL_ALL[ "asks" ] and sum( row.right for row in direct ) == LITERAL_ALL[ "right" ]

    admin = _admin_report( accuracy_session, response_type="yes_no", window_days=3650 )
    assert ( admin[ "total_scored" ], admin[ "total_correct" ] ) == ( LITERAL_ALL[ "asks" ], LITERAL_ALL[ "right" ] )

    asks, run, logged_right = _run( engine, accuracy_session )
    assert len( asks ) == len( scored_rows( accuracy_session, "yes_no" ) ) == LITERAL_ALL[ "asks" ]
    assert run[ "not_replayable" ] == 1 and len( run[ "records" ][ "logged" ] ) == LITERAL_ALL[ "asks" ] - 1
    assert len( run[ "records" ][ "logged" ] ) + run[ "not_replayable" ] == admin[ "total_scored" ]
    assert logged_right == admin[ "total_correct" ]


def test_each_window_agrees_between_replay_and_direct_count( accuracy_session, engine ):
    _plant( accuracy_session )
    direct = { row.win: ( row.asks, row.right ) for row in accuracy_session.execute( text( _DIRECT_SQL ) ).all() }
    assert set( direct ) == set( WINDOW_NAMES )
    for name in WINDOW_NAMES:
        asks, run, logged_right = _run( engine, accuracy_session, name )
        literal = LITERAL_WINDOW[ name ]
        assert direct[ name ] == ( literal[ "asks" ], literal[ "right" ] ), name
        assert ( len( asks ), logged_right ) == direct[ name ], name


def test_the_excluded_rows_are_in_the_table_and_in_no_cohort( accuracy_session ):
    _plant( accuracy_session )
    in_table = accuracy_session.execute( text( "SELECT count(*) FROM prediction_log WHERE notification_id IN ( SELECT id FROM notifications WHERE title LIKE 'Worker x%' )" ) ).scalar()
    assert in_table == 5, "the five excluded rows must exist, or the exclusions are untested"
    cohort_ids = { ask[ "message" ] for ask in cohort_asks( accuracy_session, "yes_no", vectors=_stored_vectors( accuracy_session ) ) }
    assert not any( f"worker x{n} " in message for message in cohort_ids for n in range( 1, 6 ) )


def test_window_of_puts_each_planted_row_in_the_window_the_direct_count_puts_it_in( accuracy_session ):
    _plant( accuracy_session )
    by_python = { name: sum( 1 for row in scored_rows( accuracy_session, "yes_no" ) if window_of( row.predicted_at, "yes_no" ) == name ) for name in WINDOW_NAMES }
    assert by_python == { name: LITERAL_WINDOW[ name ][ "asks" ] for name in WINDOW_NAMES }


def test_window_of_follows_the_cutovers_for_each_response_type_and_refuses_another():
    """A cut-over instant belongs to the earlier window; a microsecond later, to the next."""
    from cosa.research.preference_replay.cohorts import CUTOVERS
    for response_type, ( first, second ) in CUTOVERS.items():
        tick = timedelta( microseconds=1 )
        assert [ window_of( moment, response_type ) for moment in ( first - tick, first, first + tick, second - tick, second ) ] == \
               [ "before", "before", "undetermined", "undetermined", "after" ]
    with pytest.raises( ValueError ):
        window_of( datetime( 2026, 11, 12, tzinfo=timezone.utc ), "open_ended" )


def test_an_unknown_window_name_is_refused( accuracy_session ):
    """A typo in a window name must not read as an empty cohort."""
    with pytest.raises( ValueError ):
        scored_rows( accuracy_session, "yes_no", "afterwards" )


def test_a_row_written_before_the_ledger_is_asked_at_its_notifications_creation_time( accuracy_session ):
    """With no asked_at stamp the ask time is the notification's own creation time."""
    _plant( accuracy_session )
    accuracy_session.query( PredictionLog ).update( { PredictionLog.asked_at: None } )
    asks = cohort_asks( accuracy_session, "yes_no", vectors=_stored_vectors( accuracy_session ) )
    assert all( ask[ "asked_at" ] == ask[ "responded_at" ] - timedelta( seconds=50 ) for ask in asks )


def test_a_row_with_a_ledger_stamp_is_asked_at_that_stamp( accuracy_session ):
    """The ledger's asked_at wins over the notification's creation time, 15 seconds earlier."""
    _plant( accuracy_session )
    asks = cohort_asks( accuracy_session, "yes_no", vectors=_stored_vectors( accuracy_session ) )
    assert all( ask[ "asked_at" ] == ask[ "responded_at" ] - timedelta( seconds=35 ) for ask in asks )


def test_the_cohort_comes_back_in_predicted_at_order( accuracy_session ):
    """The seven counted asks are listed oldest forecast first."""
    _plant( accuracy_session )
    titles = [ ask[ "title" ] for ask in cohort_asks( accuracy_session, "yes_no", vectors=_stored_vectors( accuracy_session ) ) ]
    assert titles == [ f"Worker y{n}" for n in range( 1, 8 ) ]
