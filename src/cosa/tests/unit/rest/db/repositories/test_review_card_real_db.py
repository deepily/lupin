"""
Real-Postgres proof that a review card's answer is a ruling and not a case.

A throwaway database is built by `alembic upgrade head`. A marked card is answered through the real answer door
and the real database. Then the rows are counted: one ruling, no case, no forecast, no extractor input.
The module skips when Postgres is unreachable.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import tests.helpers.template_database as td
from cosa.agents.prediction_engine.principle_status import CONTESTED, derive_statuses
from cosa.agents.principle_learner import review_cards as rc
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.db.vector_store_models import PredictionDecision
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.postgres_models import Notification, PredictionLog, PreferenceEvidence, PreferencePrinciple, User
from tests.helpers.notifications_endpoint_harness import ConfigStub, Spy

_THROWAWAY_DB = f"review_card_{os.getpid()}"
VERSION       = "ext"


@pytest.fixture( scope="module" )
def database_url():
    """Yield a throwaway database URL at head; drop it at teardown; skip if Postgres is down."""
    server = make_url( td.clone_server_url() )
    plain  = server.render_as_string( hide_password=False )
    try:
        td.drop_database( plain, _THROWAWAY_DB )
        td.create_from_template( plain, _THROWAWAY_DB )
    except OperationalError as error:
        pytest.skip( f"Postgres unreachable, skipping the real-database review card test: {error}" )
    url = server.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    try:
        command.upgrade( build_alembic_config( database_url=url ), "head" )
    except BaseException:
        td.drop_database( plain, _THROWAWAY_DB )
        raise
    yield url
    engine = create_engine( plain, isolation_level="AUTOCOMMIT" )
    with engine.connect() as conn:
        conn.execute( text( td.terminate_sessions_sql( td.uses_template() ) ), { "n": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    engine.dispose()


@pytest.fixture
def door( database_url, monkeypatch ):
    """Yield the client, a session factory and the owner id; the router and database are real."""
    import lupin_app.main as main_module
    import cosa.rest.routers.notifications as notif
    engine  = create_engine( database_url )
    factory = sessionmaker( bind=engine )
    monkeypatch.setattr( "cosa.rest.db.database.SessionLocal", factory )
    monkeypatch.setattr( main_module, "config_mgr", ConfigStub(), raising=False )
    monkeypatch.setattr( main_module, "app_debug", False, raising=False )
    monkeypatch.setattr( main_module, "app_verbose", False, raising=False )
    ws = Spy( "ws", lenient=True )
    ws.user_sessions, ws.active_connections, ws.user_to_email = {}, {}, {}
    monkeypatch.setattr( main_module, "websocket_manager", ws, raising=False )
    monkeypatch.setattr( notif, "pending_responses", {} )
    owner = uuid.uuid4()
    with factory() as setup:
        setup.add( User( id=owner, email=f"card-{owner.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                         is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
        setup.commit()
    app = FastAPI()
    app.include_router( notif.router )
    app.dependency_overrides[ require_api_key_or_jwt ]        = lambda: str( owner )
    app.dependency_overrides[ authenticated_account_email ]   = lambda: None
    app.dependency_overrides[ notif.get_websocket_manager ]   = lambda: ws
    yield TestClient( app, raise_server_exceptions=False ), factory, owner
    engine.dispose()


def _contested_principle( setup, owner ):
    """Insert a principle with one supporting and one contradicting extractor row, and return it."""
    principle = PreferencePrinciple( id=uuid.uuid4(), owner_id=str( owner ), kind="decision", dimension="ask.x", statement="Approve with a link.",
                                     scope="global", embedding=None, encoder_version="enc", extractor_version=VERSION )
    setup.add( principle )
    setup.flush()
    base = datetime.now( timezone.utc ) - timedelta( hours=3 )
    for relation, minutes in ( ( "supports", 0 ), ( "contradicts", 5 ) ):
        setup.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=principle.id, notification_id=uuid.uuid4(), field_key="answer", relation=relation,
                                       condition=None, answered_at=base + timedelta( minutes=minutes ), extracted_at=base + timedelta( minutes=minutes + 1 ),
                                       extractor_version=VERSION, source="extractor" ) )
    setup.commit()
    return principle


def _counts( factory ):
    """Count the rows a wrongly learned answer would leave behind."""
    with factory() as check:
        return { "decisions": check.query( PredictionDecision ).count(), "forecasts": check.query( PredictionLog ).count(),
                 "extractor": check.query( PreferenceEvidence ).filter_by( source="extractor" ).count(),
                 "rulings": check.query( PreferenceEvidence ).filter_by( source="review_card" ).count() }


def test_answering_a_marked_card_through_the_real_door_writes_one_ruling_and_no_case_or_forecast( door ):
    """The door stores the answer and one ruling; cases, forecasts and extractor input stay put."""
    client, factory, owner = door
    with factory() as setup:
        principle = _contested_principle( setup, owner )
        principle_id = principle.id
        questions, extras = rc.build_card( [ { "principle_id": str( principle.id ), "statement": principle.statement, "answer_a": "a", "answer_b": "b" } ] )
        card = uuid.uuid4()
        setup.add( Notification( id=card, sender_id="claude.code@lupin.deepily.ai#ab12cd34", recipient_id=owner, message="Which should win?", title="Review",
                                 type="task", priority="low", created_at=datetime.now( timezone.utc ), response_requested=True, response_type="multiple_choice",
                                 response_options={ "questions": questions, **extras }, state="delivered" ) )
        setup.commit()
    # Positive control: the case store counts a row when one is written, so a zero below is not a broken count.
    with factory() as control:
        control.add( PredictionDecision( id=str( uuid.uuid4() ), question="control", decision_value="yes" ) )
        control.commit()
    before = _counts( factory )
    assert before == { "decisions": 1, "forecasts": 0, "extractor": 2, "rulings": 0 }
    reply = client.post( "/api/notify/response", json={ "notification_id": str( card ), "response_value": json.dumps( { "answers": { "P1": rc.OPTION_ONE } } ) } )
    assert reply.status_code == 200, reply.text
    after = _counts( factory )
    assert after == { "decisions": 1, "forecasts": 0, "extractor": 2, "rulings": 1 }, "one ruling; no case, no forecast, no extractor input"
    with factory() as check:
        ruling     = check.query( PreferenceEvidence ).filter_by( source="review_card" ).one()
        principles = check.query( PreferencePrinciple ).all()
        evidence   = check.query( PreferenceEvidence ).all()
        stored     = check.get( Notification, card )
        assert ruling.principle_id == principle_id and ruling.relation == "supports" and stored.response_value[ "source" ] == "ui"
        statuses   = derive_statuses( principles, evidence, datetime.now( timezone.utc ), VERSION, lambda nid: None )
        assert statuses[ principle_id ][ "status" ] != CONTESTED and statuses[ principle_id ][ "ruled" ] is True
