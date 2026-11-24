"""
Real-Postgres proof that an answer's angle-bracket text is stored as typed.

Cards are answered through the real answer door and the real database. The cases are a yes/no comment, a multiple-choice write-in and free text.
The stored row is then read back. The module skips when Postgres is unreachable.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from alembic import command

import tests.helpers.template_database as td
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.postgres_models import Notification, User
from tests.helpers.notifications_endpoint_harness import ConfigStub, Spy

_THROWAWAY_DB = f"answer_text_{os.getpid()}"


@pytest.fixture( scope="module" )
def database_url():
    """Yield a throwaway database URL at head; drop it at teardown; skip if Postgres is down."""
    server = make_url( td.clone_server_url() )
    plain  = server.render_as_string( hide_password=False )
    try:
        td.drop_database( plain, _THROWAWAY_DB )
        td.create_from_template( plain, _THROWAWAY_DB )
    except OperationalError as error:
        pytest.skip( f"Postgres unreachable, skipping the real-database answer text test: {error}" )
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
        setup.add( User( id=owner, email=f"text-{owner.hex[:8]}@test.local", password_hash="x", email_verified=True, is_active=True,
                         is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ) ) )
        setup.commit()
    app = FastAPI()
    app.include_router( notif.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: str( owner )
    app.dependency_overrides[ authenticated_account_email ] = lambda: None
    app.dependency_overrides[ notif.get_websocket_manager ] = lambda: ws
    yield TestClient( app, raise_server_exceptions=False ), factory, owner
    engine.dispose()


def _card( factory, owner, response_type ):
    """Insert one open card of the given type and return its id."""
    card = uuid.uuid4()
    with factory() as setup:
        setup.add( Notification( id=card, sender_id="claude.code@lupin.deepily.ai#ab12cd34", recipient_id=owner, message="Which?", title="Ask",
                                 type="task", priority="low", created_at=datetime.now( timezone.utc ), response_requested=True,
                                 response_type=response_type, state="delivered" ) )
        setup.commit()
    return card


@pytest.mark.parametrize( "response_type, typed", [
    ( "yes_no",          "yes [comment: use <T> generics]" ),
    ( "yes_no",          "no [comment: a<b and c>d]" ),
    ( "multiple_choice", json.dumps( { "answers": { "Plan": "keep <b> but add retries" } } ) ),
    ( "open_ended",      "use <T> generics" ),
] )
def test_an_answer_with_angle_brackets_is_stored_as_typed( door, response_type, typed ):
    """The stored value equals what was sent, through the real endpoint and the real database."""
    client, factory, owner = door
    card  = _card( factory, owner, response_type )
    reply = client.post( "/api/notify/response", json={ "notification_id": str( card ), "response_value": typed } )
    assert reply.status_code == 200, reply.text
    with factory() as check:
        assert check.get( Notification, card ).response_value[ "value" ] == typed
