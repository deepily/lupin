"""
The un-park ask endpoint, driven through a running server.

A manager seat asks the operator to approve un-parking a parked row; the server makes the card.
Venue: :8000 (scheduled). Writes task and notification rows in the test database, removed on teardown.
Requires the operator's account in the test database; the parked-row case answers 404 without it.
"""

# What the tests drive, in order of how far a request gets:
#   1. no credential: refused before the handler
#   2. a worker seat: refused 403 and no card is written
#   3. a manager seat, unknown row: 404
#   4. a manager seat, row not parked: 409 naming the state
#   5. a manager seat, parked row: 200, and the card in the database is bound to this row and this
#      move, asks yes or no with "no" as the default, and expires in about ten minutes
#   6. a second ask for the same row and park: 409 naming the waiting card, and no second card
#
# The manager signal is a session bridge file in the directory the server reads. That directory is
# shared with the container, and a fabricated bridge matches by its first eight characters, as in
# test_task_create_blocked_at_mint.py. A worker bridge carries no persona, so neither source of the
# manager check can say yes.
#
# Left out on purpose: the operator answering the card, and the push reaching a connected browser.
# The first is the transition's receipt check, which has its own tests.

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
import requests
from sqlalchemy import text

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import ApiKeyRepository, UserRepository
from cosa.rest.task_promotion_gate import UNPARK_ASK_TIMEOUT_SECONDS, unpark_ask_payload

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"

# The directory the server's manager check reads, the same one the fixture writes.
SESSION_DIR = Path.home() / ".claude" / "sessions"

REQUEST_TIMEOUT = 30


def _write_bridge( session_id, role ):
    """A minimal session bridge: the id and the role, and no persona, so only the role decides."""
    SESSION_DIR.mkdir( parents=True, exist_ok=True )
    path = SESSION_DIR / f"cc-test-unparkask-{session_id}.json"
    path.write_text( json.dumps( { "session_id": session_id, "stable_session_id": session_id, "role": role } ) )
    return path


@pytest.fixture
def manager_actor():
    """The 'persona + session id' string of a seat the server resolves as a manager."""
    sid  = uuid.uuid4().hex
    path = _write_bridge( sid, "manager" )
    yield f"mr_radio {sid[ :8 ]}"
    path.unlink( missing_ok=True )


@pytest.fixture
def worker_actor():
    """The same for a seat the server resolves as a worker."""
    sid  = uuid.uuid4().hex
    path = _write_bridge( sid, "worker" )
    yield f"worker {sid[ :8 ]}"
    path.unlink( missing_ok=True )


@pytest.fixture
def api_headers( clean_test_db ):
    """An API key for a service account made for this test, as request headers."""
    api_key  = "ck_live_" + secrets.token_urlsafe( 48 )
    key_hash = bcrypt.hashpw( api_key.encode( "utf-8" ), bcrypt.gensalt( rounds=12 ) ).decode( "utf-8" )
    email    = f"unparkask-{uuid.uuid4()}@test.com"
    with get_db() as session:
        user = UserRepository( session ).create_user( email=email, password_hash="dummy_hash", roles=[ "service_account" ] )
        user.email_verified = True
        user.is_active      = True
        key = ApiKeyRepository( session ).create_key( user_id=user.id, key_hash=key_hash, description="unpark-ask live test" )
        key_id, user_id = key.id, user.id
    yield { "X-API-Key": api_key }
    with get_db() as session:
        ApiKeyRepository( session ).delete( key_id )
        UserRepository( session ).delete( user_id )


@pytest.fixture
def parked_row( seeded_task_rows, api_headers ):
    """A row parked through the API, with a chase an hour out. Its id is a string."""
    persona = f"unpark-{uuid.uuid4().hex[ :10 ]}"
    row     = seeded_task_rows.create( persona, "Unpark ask live subject", created_by="unparkask live" )
    chase   = datetime.now( timezone.utc ) + timedelta( hours=1 )
    parked  = requests.post(
        f"{ENDPOINT}/{row[ 'id' ]}/transition",
        json    = { "to_status": "parked", "actor": "unparkask live", "authority": "standing",
                    "next_chase_ts": chase.isoformat(), "park_reason": "Waiting on the operator's answer" },
        headers = api_headers,
        timeout = REQUEST_TIMEOUT,
    )
    assert parked.status_code == 200, f"parking the fixture row failed: {parked.status_code} {parked.text}"
    return row[ "id" ]


@pytest.fixture
def made_cards():
    """Collects card ids a test caused; removes them from the database afterwards."""
    ids = [ ]
    yield ids
    if ids:
        with get_db() as session:
            for card_id in ids:
                session.execute( text( "DELETE FROM notifications WHERE id = :id" ), { "id": card_id } )


def _ask( api_headers, task_id, actor ):
    return requests.post( f"{ENDPOINT}/{task_id}/unpark-ask", json={ "actor": actor },
                          headers=api_headers, timeout=REQUEST_TIMEOUT )


def _cards_for( task_id ):
    """Every notification whose payload names this row, newest first, as plain dicts."""
    with get_db() as session:
        rows = session.execute( text(
            "SELECT id, recipient_id, response_requested, response_type, response_default, state, expires_at, payload "
            "FROM notifications WHERE payload->>'task_id' = :task ORDER BY created_at DESC"
        ), { "task": str( task_id ) } ).mappings().all()
        return [ dict( r ) for r in rows ]


def test_a_request_with_no_credential_is_refused_before_the_handler():
    response = requests.post( f"{ENDPOINT}/{uuid.uuid4()}/unpark-ask", json={ "actor": "mr_radio abcdef12" }, timeout=REQUEST_TIMEOUT )
    assert response.status_code in ( 401, 403 ), response.text


def test_a_worker_seat_is_refused_and_no_card_is_written( api_headers, parked_row, worker_actor ):
    response = _ask( api_headers, parked_row, worker_actor )
    assert response.status_code == 403, response.text
    assert "un-parking" in response.text, f"the refusal should name the move: {response.text}"
    assert _cards_for( parked_row ) == [ ]


def test_a_manager_asking_about_an_unknown_row_gets_404( api_headers, manager_actor ):
    response = _ask( api_headers, uuid.uuid4(), manager_actor )
    assert response.status_code == 404, response.text
    assert "not found" in response.text


def test_a_manager_asking_about_a_row_that_is_not_parked_gets_409_and_no_card( api_headers, seeded_task_rows, manager_actor ):
    row      = seeded_task_rows.create( f"unpark-{uuid.uuid4().hex[ :10 ]}", "Unpark ask live, not parked", created_by="unparkask live" )
    response = _ask( api_headers, row[ "id" ], manager_actor )
    assert response.status_code == 409, response.text
    assert "not parked" in response.text
    assert _cards_for( row[ "id" ] ) == [ ]


def test_a_manager_asking_about_a_parked_row_makes_one_card_bound_to_that_row( api_headers, parked_row, manager_actor, made_cards ):
    before   = datetime.now( timezone.utc )
    response = _ask( api_headers, parked_row, manager_actor )
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    body = response.json()
    made_cards.append( body[ "card_id" ] )

    assert body[ "task_id" ] == parked_row
    assert isinstance( body[ "pushed" ], bool )
    expires = datetime.fromisoformat( body[ "expires_at" ] )
    assert before + timedelta( seconds=UNPARK_ASK_TIMEOUT_SECONDS - 60 ) < expires < before + timedelta( seconds=UNPARK_ASK_TIMEOUT_SECONDS + 120 )

    cards = _cards_for( parked_row )
    assert len( cards ) == 1, f"expected one card for this row, found {len( cards )}"
    card = cards[ 0 ]
    assert str( card[ "id" ] ) == body[ "card_id" ]
    assert card[ "payload" ] == unpark_ask_payload( parked_row ), "the card must carry the server's binding"
    assert card[ "response_requested" ] is True
    assert card[ "response_type" ] == "yes_no"
    assert card[ "response_default" ] == "no", "an unanswered card must not approve"
    assert card[ "state" ] in ( "created", "delivered" )


def test_a_second_ask_for_the_same_row_and_park_is_refused_and_makes_no_second_card( api_headers, parked_row, manager_actor, made_cards ):
    first = _ask( api_headers, parked_row, manager_actor )
    assert first.status_code == 200, f"{first.status_code} {first.text}"
    made_cards.append( first.json()[ "card_id" ] )

    second = _ask( api_headers, parked_row, manager_actor )
    assert second.status_code == 409, second.text
    assert first.json()[ "card_id" ] in second.text, "the refusal should name the card that is waiting"
    assert len( _cards_for( parked_row ) ) == 1
