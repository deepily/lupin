"""
Real-Postgres proof of the two reads behind un-parking a row on a card.

The unit tests compile these queries to SQL on a mock. This file runs them against a real
schema that alembic builds on a throwaway database. The JSONB path comparisons are measured
on the planner and not on a string.

What it proves:
    1. The single-use read finds a card named by a parked-to-queued event, ignores the same
       card named on another move, and ignores a card no event names.
    2. The live-card read returns the newest unanswered card for this row and this park.
       It leaves out an answered card, an expired one and one older than the park.
       It also leaves out a card made for another row, one of another kind and one that asks nothing.

Venue: the integration tier. It skips when Postgres is unreachable.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from cosa.rest.db.auto_migrate import build_alembic_config
import tests.helpers.template_database as td
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.postgres_models import Notification, TaskEvent, TaskItem, User
from cosa.rest.task_promotion_gate import unpark_ask_payload

_THROWAWAY_DB = f"unpark_card_reads_{os.getpid()}"


def _server_url():
    return make_url( td.clone_server_url() )


def _maintenance_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def live_session():
    """A throwaway database at the newest schema, yielded as a Session and dropped afterwards."""
    server_url = _server_url()
    try:
        td.drop_database( server_url.render_as_string( hide_password=False ), _THROWAWAY_DB )
        td.create_from_template( server_url.render_as_string( hide_password=False ), _THROWAWAY_DB )
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable, skipping the un-park card reads: {e}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    try:
        command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )
    except BaseException:
        td.drop_database( server_url.render_as_string( hide_password=False ), _THROWAWAY_DB )
        raise

    engine  = create_engine( throwaway_url )
    session = sessionmaker( bind=engine )()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text(
                "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ), { "db": _THROWAWAY_DB } )
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
        eng.dispose()


def _make_user( session ):
    uid = uuid.uuid4()
    session.add( User(
        id=uid, email=f"unpark-{uid.hex[:8]}@test.local", password_hash="x", email_verified=True,
        is_active=True, is_protected=False, roles={ "roles": [ "user" ] }, created_at=datetime.now( timezone.utc ),
    ) )
    session.flush()
    return uid


def _make_task( session ):
    item = TaskItem(
        item_class="task", title="a parked row", project="lupin", owner_persona="sam", accountable_manager="mr radio",
        created_by="itest seed", status="queued", priority="P5", correlation_key="epic:unassigned",
    )
    session.add( item )
    session.flush()
    return item


def _event( session, item, transition, receipt_refs ):
    session.add( TaskEvent(
        item_id=item.id, ts=datetime.now( timezone.utc ), actor="mr radio d54262de",
        transition=transition, authority="standing", receipt_refs=receipt_refs,
    ) )
    session.flush()


def test_the_single_use_read_finds_a_card_only_when_an_un_park_event_names_it( live_session ):
    session = live_session
    repo    = TaskRepository( session )
    item    = _make_task( session )
    used, other_move, other_key, unnamed = ( uuid.uuid4() for _ in range( 4 ) )

    _event( session, item, "->queued", None )
    _event( session, item, "parked->queued", { "approval_card": str( used ) } )
    _event( session, item, "queued->in_progress", { "approval_card": str( other_move ) } )
    _event( session, item, "parked->queued", { "commit": "abcdef1" } )
    session.commit()

    assert repo.approval_card_ids_used( used ) == { str( used ) }
    assert repo.approval_card_ids_used( other_move ) == set(), "a card named on another move must not count as used"
    assert repo.approval_card_ids_used( other_key ) == set()
    assert repo.approval_card_ids_used( unnamed ) == set()


def _card( session, recipient_id, *, payload, created_ago, state="delivered", expires_in=timedelta( minutes=10 ),
           response_requested=True ):
    now = datetime.now( timezone.utc )
    cid = uuid.uuid4()
    session.add( Notification(
        id=cid, sender_id="claude.code@lupin.deepily.ai#promotion-gate", recipient_id=recipient_id,
        message="Allow the un-park?", type="custom", priority="high", state=state,
        response_requested=response_requested, response_type="yes_no", expires_at=now + expires_in,
        payload=payload, created_at=now - created_ago,
    ) )
    session.flush()
    return cid


def test_the_live_card_read_returns_the_newest_waiting_card_and_excludes_each_other_kind_by_id( live_session ):
    session = live_session
    cards   = NotificationRepository( session )
    rid     = _make_user( session )
    row     = uuid.uuid4()
    other   = uuid.uuid4()
    now     = datetime.now( timezone.utc )
    parked  = now - timedelta( hours=1 )
    mine    = unpark_ask_payload( row )

    older_live = _card( session, rid, payload=mine, created_ago=timedelta( minutes=30 ), state="created" )
    newest     = _card( session, rid, payload=mine, created_ago=timedelta( minutes=5 ) )
    excluded   = {
        "answered"      : _card( session, rid, payload=mine, created_ago=timedelta( minutes=4 ), state="responded" ),
        "expired state" : _card( session, rid, payload=mine, created_ago=timedelta( minutes=4 ), state="expired" ),
        "past expiry"   : _card( session, rid, payload=mine, created_ago=timedelta( minutes=4 ), expires_in=-timedelta( minutes=1 ) ),
        "before park"   : _card( session, rid, payload=mine, created_ago=timedelta( hours=2 ) ),
        "other row"     : _card( session, rid, payload=unpark_ask_payload( other ), created_ago=timedelta( minutes=3 ) ),
        "other kind"    : _card( session, rid, payload={ **mine, "kind": "something_else" }, created_ago=timedelta( minutes=3 ) ),
        "no payload"    : _card( session, rid, payload=None, created_ago=timedelta( minutes=3 ) ),
        "no question"   : _card( session, rid, payload=mine, created_ago=timedelta( minutes=3 ), response_requested=False ),
    }
    session.commit()

    found = cards.find_live_unpark_card( row, parked, now )
    assert found is not None and found.id == newest, "the newest waiting card for this row and park is the answer"
    assert found.id != older_live
    for kind, card_id in excluded.items():
        assert found.id != card_id, f"a card that is {kind} must not be returned"

    # Take the newest away and the older waiting one is next; take both and nothing is left.
    session.query( Notification ).filter( Notification.id == newest ).update( { "state": "responded" } )
    session.commit()
    assert cards.find_live_unpark_card( row, parked, now ).id == older_live
    session.query( Notification ).filter( Notification.id == older_live ).update( { "state": "responded" } )
    session.commit()
    assert cards.find_live_unpark_card( row, parked, now ) is None
