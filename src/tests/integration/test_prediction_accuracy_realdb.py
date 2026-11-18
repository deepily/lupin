"""
Real-Postgres proof of the prediction accuracy summary and its admin route.

A throwaway database is built by `alembic upgrade head` and loaded with the committed fixture of
12 synthetic prediction_log rows. Three things must then agree. They are the route's numbers, a
direct SQL count over the same rows, and the literal counts written below. The database is
self-cleaning and pid-scoped, and the module skips when Postgres is unreachable.

The fixture: mixed types, three unscored rows (r04, r07, r10) and one test_override row (r08).
"""
import contextlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from alembic import command

import tests.helpers.template_database as td
from cosa.rest.auth_middleware import get_current_user
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import Notification, PredictionLog, User
from cosa.rest.routers.system import router

_THROWAWAY_DB = f"prediction_accuracy_{os.getpid()}"
_FIXTURE      = os.path.join( os.path.dirname( __file__ ), "..", "fixtures", "prediction_accuracy", "prediction_log_12_rows.json" )

# The literal counts, written by hand from the fixture: 12 rows, r08 is a test override, so 11 count.
# Unscored: r04, r07, r10. Answered ( actual_value present ): all but r04 and r10, so 9.
# Scored ( accuracy_match present ): 11 - 3 = 8. Correct: r01, r02, r05, r09, r12 = 5. Wrong: r03, r06, r11.
LITERAL = { "total_predictions": 11, "total_responded": 9, "total_scored": 8, "total_correct": 5, "accuracy_rate": 0.625 }
LITERAL_BY_TYPE = {
    "yes_no"           : { "count": 5, "responded": 4, "scored": 4, "correct": 3, "accuracy": 0.75 },
    "multiple_choice"  : { "count": 3, "responded": 3, "scored": 2, "correct": 1, "accuracy": 0.5 },
    "open_ended"       : { "count": 2, "responded": 1, "scored": 1, "correct": 1, "accuracy": 1.0 },
    "open_ended_batch" : { "count": 1, "responded": 1, "scored": 1, "correct": 0, "accuracy": 0.0 },
}


def _server_url():
    return make_url( td.clone_server_url() )


@pytest.fixture( scope="module" )
def accuracy_session():
    """Yield a Session on a throwaway DB at head; drop it at teardown, skip if Postgres is down."""
    server_url = _server_url()
    plain      = server_url.render_as_string( hide_password=False )
    try:
        td.drop_database( plain, _THROWAWAY_DB )
        td.create_from_template( plain, _THROWAWAY_DB )
    except OperationalError as error:
        pytest.skip( f"Postgres unreachable — skipping the real-DB accuracy test: {error}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    try:
        command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )
    except BaseException:
        td.drop_database( plain, _THROWAWAY_DB )
        raise

    engine  = create_engine( throwaway_url )
    session = sessionmaker( bind=engine )()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        eng = create_engine( plain, isolation_level="AUTOCOMMIT" )
        with eng.connect() as conn:
            conn.execute( text( td.terminate_sessions_sql( td.uses_template() ) ), { "n": _THROWAWAY_DB } )
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
        eng.dispose()


def _load_fixture( session ):
    """Insert the fixture: one user, one notification and one prediction_log row per fixture row."""
    with open( _FIXTURE ) as handle:
        rows = json.load( handle )[ "rows" ]
    assert len( rows ) == 12, "the committed fixture holds exactly 12 rows"
    uid = uuid.uuid4()
    session.add( User( id=uid, email=f"acc-{uid.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                       is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
    session.flush()
    predicted = datetime.now( timezone.utc ) - timedelta( days=1 )
    for row in rows:
        nid = uuid.uuid4()
        session.add( Notification( id=nid, sender_id="claude.code@lupin.deepily.ai#acc", recipient_id=uid, message=row[ "key" ],
                                   type="task", priority="high", created_at=predicted, sender_persona="acc",
                                   response_requested=True, state="created" ) )
        session.flush()
        # An unanswered row leaves actual_value unset, so it is a SQL NULL, as in production; a Python None
        # on a JSON column would be stored as the JSON value null and count as answered.
        answer = { "actual_value": { "value": "yes" } } if row[ "answered" ] else {}
        session.add( PredictionLog(
            notification_id       = nid,
            response_type         = row[ "response_type" ],
            category              = row[ "category" ],
            predicted_value       = { "value": "yes" },
            prediction_confidence = row[ "prediction_confidence" ],
            prediction_strategy   = row[ "prediction_strategy" ],
            similar_case_count    = 3,
            accuracy_match        = row[ "accuracy_match" ],
            forecast_source       = row[ "forecast_source" ],
            predicted_at          = predicted,
            **answer,
        ) )
    session.commit()


def _direct_sql( session ):
    """Count the same rows in plain SQL, with the summary's own definitions written out."""
    row = session.execute( text( """
        SELECT count(*)                                              AS total_predictions,
               count(actual_value)                                   AS total_responded,
               count(accuracy_match)                                 AS total_scored,
               count(*) FILTER ( WHERE accuracy_match IS TRUE )      AS total_correct
          FROM prediction_log
         WHERE coalesce( forecast_source, '' ) <> 'test_override'
    """ ) ).one()
    return dict( row._mapping )


def _route( session, **params ):
    """Call the route as an admin with get_db pointing at the throwaway session."""
    app = FastAPI()
    app.include_router( router )
    app.dependency_overrides[ get_current_user ] = lambda: { "uid": "admin-1", "email": "admin@example.com", "roles": [ "admin" ] }

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    with patch( "cosa.rest.db.database.get_db", fake_get_db ):
        return TestClient( app ).get( "/api/prediction-engine/accuracy", params=params )


def test_route_sql_and_literals_agree_on_the_twelve_row_cohort( accuracy_session ):
    _load_fixture( accuracy_session )
    direct = _direct_sql( accuracy_session )
    assert direct == { "total_predictions": 11, "total_responded": 9, "total_scored": 8, "total_correct": 5 }, direct

    response = _route( accuracy_session )
    assert response.status_code == 200
    body = response.json()
    for key in ( "total_predictions", "total_responded", "total_scored", "total_correct" ):
        assert body[ key ] == direct[ key ] == LITERAL[ key ], key
    assert body[ "accuracy_rate" ] == LITERAL[ "accuracy_rate" ] == round( direct[ "total_correct" ] / direct[ "total_scored" ], 4 )
    assert body[ "status" ] == "ok"
    assert body[ "by_response_type" ] == LITERAL_BY_TYPE


def test_the_test_override_row_is_in_the_table_but_in_no_count( accuracy_session ):
    in_table = accuracy_session.execute( text( "SELECT count(*) FROM prediction_log WHERE forecast_source = 'test_override'" ) ).scalar()
    assert in_table == 1, "the override row must exist, or the exclusion is untested"
    assert _route( accuracy_session ).json()[ "total_predictions" ] == 11


def test_filtering_to_one_type_matches_its_literal_row( accuracy_session ):
    body = _route( accuracy_session, response_type="multiple_choice" ).json()
    assert ( body[ "total_predictions" ], body[ "total_responded" ], body[ "total_scored" ], body[ "total_correct" ], body[ "accuracy_rate" ] ) == ( 3, 3, 2, 1, 0.5 )


def test_a_window_with_no_scored_rows_says_insufficient_data( accuracy_session ):
    body = _route( accuracy_session, category="no-such-category" ).json()
    assert ( body[ "status" ], body[ "accuracy_rate" ], body[ "total_scored" ] ) == ( "insufficient data", None, 0 )
