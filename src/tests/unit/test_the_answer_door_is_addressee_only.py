"""
The answer door lets only the card's addressee answer it.

The defect: `POST /api/notify/response` asked for a credential and recorded who answered.
It let any valid login or API key answer any card, so a Yes landed on Rick's card from
another signed-in login. Rick's ruling was "Fix: addressee only".

The rule: the caller's user id must be the notification's `recipient_id`. The id is the
login's user, or the user owning the API key. Otherwise the door answers 403 and writes
nothing. The check runs after the 404 and before the state checks, so a stranger learns
nothing about the card's state.

These tests go through HTTP with TestClient over the real router. The real credential
dependencies run, and only their validators are mocked. The store is a small fake.
It really changes state. So "nothing was written" is read from the row itself, not
inferred from a mock's call count.

Runs on :7999: no server, no network, no persistent state.
"""

import sys
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.notifications as N


ADDRESSEE = "1234abcd-1234-4678-9234-567812abcdef"   # hex letters, so upper-casing it changes the spelling
STRANGER  = "87654321-4321-8765-4321-876543218765"
CARD_ID   = "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"
VALID_KEY = "ck_live_" + "a" * 64

JWT_HEADERS  = { "Authorization": "Bearer header.payload.signature" }
KEY_HEADERS  = { "X-API-Key": VALID_KEY }
BOTH_HEADERS = { **JWT_HEADERS, **KEY_HEADERS }


class Row:
    """A notification row; only `update_response` changes it, the way the real repository does."""

    def __init__( self, state="delivered", expires_at=None, recipient_id=ADDRESSEE ):
        self.state          = state
        self.expires_at     = expires_at
        self.recipient_id   = recipient_id
        self.job_id         = None
        self.sender_id      = "claude.code@x#abcd1234"
        self.sender_persona = "tiberius"
        self.response_value = None


class Store:
    """The repository stand-in: one row, and a list of every write attempted on it."""

    def __init__( self, row ):
        self.row    = row
        self.writes = []

    def get_by_id( self, notification_id ):
        return self.row

    def update_response( self, notification_id, response_dict ):
        self.writes.append( response_dict )
        self.row.state          = "responded"
        self.row.response_value = response_dict
        return True


def _ctx_db():
    gd = MagicMock()
    gd.return_value.__enter__.return_value = Mock()
    return gd


def _fake_main( main ):
    pkg = Mock(); pkg.main = main
    return { "lupin_app": pkg, "lupin_app.main": main }


@pytest.fixture
def ws():
    ws = Mock()
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": True } )
    return ws


@pytest.fixture
def client( ws ):
    app = FastAPI()
    app.include_router( N.router )
    app.dependency_overrides[ N.get_websocket_manager ] = lambda: ws
    with TestClient( app, raise_server_exceptions=False ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def world():
    """
    Yield a `put( row )` function that installs a store holding that row.

    Ensures:
        - the grace-period config read inside `_submit_response_sync` resolves to 300
        - the waiting SSE entry for CARD_ID is armed with a real event, so "the ask was
          never woken" is readable from the event itself
        - the validators the real credential dependencies call return the caller named by
          the test's `who` dict ({"key": id, "token": id}); nothing above them is mocked
    """
    who = { "key": ADDRESSEE, "token": ADDRESSEE }
    holder = {}
    main   = Mock( config_mgr=Mock( get=Mock( return_value=300 ) ) )

    def put( row ):
        holder[ "store" ] = Store( row )
        return holder[ "store" ]

    def repo_factory( session ):
        return holder[ "store" ]

    event = asyncio.Event()
    N.pending_responses[ CARD_ID ] = { "event": event }
    key_check   = AsyncMock( side_effect=lambda key: who[ "key" ] )
    token_check = AsyncMock( side_effect=lambda token: { "uid": who[ "token" ] } )
    email_read  = Mock( return_value={ "email": "someone@example.com" } )
    with patch.object( N, "get_db", _ctx_db() ), \
         patch.object( N, "NotificationRepository", side_effect=repo_factory ), \
         patch.dict( sys.modules, _fake_main( main ) ), \
         patch( "cosa.rest.middleware.api_key_auth.validate_api_key", new=key_check ), \
         patch( "cosa.rest.auth.verify_token", new=token_check ), \
         patch( "cosa.rest.jwt_service.decode_and_validate_token", new=email_read ), \
         patch( "builtins.print" ):
        yield Mock( put=put, who=who, event=event )
    N.pending_responses.pop( CARD_ID, None )


def _post( client, headers, value="yes", notification_id=CARD_ID ):
    return client.post( "/api/notify/response",
                        json={ "notification_id": notification_id, "response_value": value },
                        headers=headers )


def _nothing_was_written( store, world, ws ):
    """Every trace an accepted answer leaves, read off the row, the event and the broadcast."""
    assert store.writes == []
    assert store.row.state == "delivered" and store.row.response_value is None
    assert not world.event.is_set()
    ws.emit_to_user_or_listener_sync.assert_not_called()


# ---------------------------------------------------------------------------
# 1. A STRANGER IS REFUSED, WHICHEVER DOOR THEY CAME IN BY
# ---------------------------------------------------------------------------

def test_another_login_cannot_answer_the_card( client, world, ws ):
    """The case the fix exists for: a different login answers the card."""
    store = world.put( Row() )
    world.who[ "token" ] = STRANGER

    r = _post( client, JWT_HEADERS )

    assert r.status_code == 403, r.text
    _nothing_was_written( store, world, ws )


def test_another_users_api_key_cannot_answer_the_card( client, world, ws ):
    store = world.put( Row() )
    world.who[ "key" ] = STRANGER

    r = _post( client, KEY_HEADERS )

    assert r.status_code == 403, r.text
    _nothing_was_written( store, world, ws )


def test_the_key_is_what_counts_when_both_headers_are_sent( client, world, ws ):
    """The door tries the key first, so a stranger's key is not rescued by the addressee's token."""
    store = world.put( Row() )
    world.who[ "key" ]   = STRANGER
    world.who[ "token" ] = ADDRESSEE

    r = _post( client, BOTH_HEADERS )

    assert r.status_code == 403, r.text
    _nothing_was_written( store, world, ws )


def test_a_caller_id_that_is_not_a_uuid_is_not_the_addressee( client, world, ws ):
    store = world.put( Row() )
    world.who[ "token" ] = "login-user"

    r = _post( client, JWT_HEADERS )

    assert r.status_code == 403, r.text
    _nothing_was_written( store, world, ws )


# ---------------------------------------------------------------------------
# 2. THE ADDRESSEE STILL ANSWERS: THE CONTROL FOR EVERY REFUSAL ABOVE
# ---------------------------------------------------------------------------

def test_the_addressee_on_a_login_answers_the_same_card( client, world, ws ):
    store = world.put( Row() )

    r = _post( client, JWT_HEADERS )

    assert r.status_code == 200, r.text
    assert store.row.state == "responded" and len( store.writes ) == 1
    assert store.writes[ 0 ][ "answered_by" ][ "user_id" ] == ADDRESSEE
    assert world.event.is_set()


def test_the_addressee_on_an_api_key_answers_the_same_card( client, world, ws ):
    store = world.put( Row() )

    r = _post( client, KEY_HEADERS )

    assert r.status_code == 200, r.text
    assert store.writes[ 0 ][ "answered_by" ][ "method" ] == "api_key"


def test_the_ids_are_compared_as_uuids_not_as_spellings( client, world, ws ):
    """Upper case, and a recipient held as a UUID object, are still the same user."""
    store = world.put( Row( recipient_id=uuid.UUID( ADDRESSEE ) ) )
    world.who[ "token" ] = ADDRESSEE.upper()

    r = _post( client, JWT_HEADERS )

    assert r.status_code == 200, r.text
    assert len( store.writes ) == 1


# ---------------------------------------------------------------------------
# 3. THE ORDER OF THE CHECKS: 404 FIRST, THEN WHO, THEN STATE
# ---------------------------------------------------------------------------

def test_a_stranger_is_told_403_not_the_cards_state( client, world, ws ):
    """A stranger gets 403 on an answered or lapsed card, not the 400 the addressee gets."""
    long_ago = datetime.now( timezone.utc ) - timedelta( seconds=10000 )
    world.who[ "token" ] = STRANGER
    for row in ( Row( state="responded" ), Row( state="expired", expires_at=long_ago ) ):
        world.put( row )
        assert _post( client, JWT_HEADERS ).status_code == 403


def test_the_addressee_still_gets_the_state_refusals( client, world, ws ):
    """Control for the test above: the same two rows answer 400 to the right caller."""
    long_ago = datetime.now( timezone.utc ) - timedelta( seconds=10000 )
    for row in ( Row( state="responded" ), Row( state="expired", expires_at=long_ago ) ):
        world.put( row )
        assert _post( client, JWT_HEADERS ).status_code == 400


def test_a_missing_card_is_still_a_404_for_a_stranger( client, world, ws ):
    store = world.put( Row() )
    store.row = None
    world.who[ "token" ] = STRANGER

    assert _post( client, JWT_HEADERS ).status_code == 404


# ---------------------------------------------------------------------------
# 4. THE HELPER AND THE WORKER, DIRECTLY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "caller,recipient,expected", [
    ( ADDRESSEE,              ADDRESSEE,              True ),
    ( ADDRESSEE.upper(),      ADDRESSEE,              True ),
    ( ADDRESSEE,              uuid.UUID( ADDRESSEE ), True ),
    ( STRANGER,               ADDRESSEE,              False ),
    ( None,                   ADDRESSEE,              False ),
    ( "",                     ADDRESSEE,              False ),
    ( "not-a-uuid",           ADDRESSEE,              False ),
    ( ADDRESSEE,              None,                   False ),
    ( 12345,                  ADDRESSEE,              False ),
] )
def test_is_addressee_compares_parsed_uuids_and_never_raises( caller, recipient, expected ):
    assert N._is_addressee( caller, recipient ) is expected


def test_a_worker_call_with_no_who_answered_is_refused( world ):
    """Fail closed: `answered_by=None` means no caller, and no caller is not the addressee."""
    store = world.put( Row() )

    with pytest.raises( HTTPException ) as exc:
        N._submit_response_sync( CARD_ID, "yes", None )

    assert exc.value.status_code == 403 and store.writes == []
