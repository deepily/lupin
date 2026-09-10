"""
The answer door asks for a credential and records WHO answered (row e20e249a).

THE DEFECT. `POST /api/notify/response` declared one dependency, the websocket manager, so
any caller holding an ask's id could answer it, and the stored answer said nothing about who
had. A yes to Rick's promotion ask could not be told from anybody else's yes. Rick selected
"Fix who first (Recommended)" (event 13250 on d2b1b59a).

WHAT THIS FILE PINS, at the layer the defect entered — HTTP, through TestClient over the real
router, with the REAL credential dependencies and only their validators mocked:

  1. a caller with no credential, or a bad one, is refused before the store is touched
  2. an accepted answer carries the SERVER's answered_by { user_id, account_email, method },
     and a caller cannot forge it
  3. the stamp lands in every shape an answer can take (Mr. Radio's build condition 3)
  4. the in-memory entry the waiting ask reads carries it (condition 4, in its own test)
  5. both `responded` frames — live and re-attached — hand it to the asker

The gate that READS the stamp is pinned in
test_the_promotion_gate_counts_only_the_operators_login.py.

:7999-eligible — no server, no network, no persistent state; the DB and the token validators
are mocked.
"""

import sys
import json
import uuid
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.notifications as N


UID_STR        = "12345678-1234-5678-1234-567812345678"
VALID_KEY      = "ck_live_" + "a" * 64
OPERATOR_EMAIL = "operator@example.com"

JWT_HEADERS  = { "Authorization": "Bearer header.payload.signature" }
KEY_HEADERS  = { "X-API-Key": VALID_KEY }
BOTH_HEADERS = { **JWT_HEADERS, **KEY_HEADERS }

# What the server must record for each way in. Literals, not derived from `_answered_by`,
# so a change to that function cannot also move the expectation.
BY_LOGIN = { "user_id": "login-user", "account_email": OPERATOR_EMAIL, "method": "jwt" }
BY_KEY   = { "user_id": "svc-user",   "account_email": None,           "method": "api_key" }


def _ctx_db():
    """A get_db stand-in whose context yields a throwaway session."""
    gd = MagicMock()
    gd.return_value.__enter__.return_value = Mock()
    return gd


def _fake_main( main ):
    """sys.modules entries so `import lupin_app.main` inside the router finds `main`."""
    pkg = Mock(); pkg.main = main
    return { "lupin_app": pkg, "lupin_app.main": main }


def _frame( chunk ):
    """The JSON object inside one `data: …` SSE chunk."""
    return json.loads( chunk.split( "data: ", 1 )[ 1 ].strip() )


@pytest.fixture
def ws():
    ws = Mock()
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": True } )
    return ws


@pytest.fixture
def client( ws ):
    """The real notifications router over a real HTTP stack; only the websocket manager is swapped."""
    app = FastAPI()
    app.include_router( N.router )
    app.dependency_overrides[ N.get_websocket_manager ] = lambda: ws
    with TestClient( app, raise_server_exceptions=False ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def store():
    """
    The repository the door writes through, with a delivered notification waiting in it.

    Ensures:
        - yields the repository mock; `update_response` records what the door stored
        - the grace-period config read inside `_submit_response_sync` resolves
    """
    notif = Mock()
    notif.state          = "delivered"
    notif.recipient_id   = UID_STR
    notif.job_id         = None
    notif.sender_id      = "claude.code@x#abcd1234"
    notif.sender_persona = "tiberius"
    notif.expires_at     = None
    repo = Mock()
    repo.get_by_id.return_value       = notif
    repo.update_response.return_value = True
    main = Mock( config_mgr=Mock( get=Mock( return_value=300 ) ) )
    with patch.object( N, "get_db", _ctx_db() ), \
         patch.object( N, "NotificationRepository", return_value=repo ), \
         patch.dict( sys.modules, _fake_main( main ) ), \
         patch( "builtins.print" ):
        yield repo


@pytest.fixture
def validators():
    """
    The three validators the real credential dependencies call, and nothing above them.

    Ensures:
        - a well-formed API key validates as "svc-user"
        - a Bearer token validates as "login-user" whose email is OPERATOR_EMAIL
        - yields the mocks so a test can prove a refusal never reached them
    """
    key_check   = AsyncMock( return_value="svc-user" )
    token_check = AsyncMock( return_value={ "uid": "login-user" } )
    email_read  = Mock( return_value={ "email": OPERATOR_EMAIL } )
    with patch( "cosa.rest.middleware.api_key_auth.validate_api_key", new=key_check ), \
         patch( "cosa.rest.auth.verify_token", new=token_check ), \
         patch( "cosa.rest.jwt_service.decode_and_validate_token", new=email_read ):
        yield Mock( key_check=key_check, token_check=token_check, email_read=email_read )


def _post( client, response_value, headers=None ):
    return client.post(
        "/api/notify/response",
        json    = { "notification_id": UID_STR, "response_value": response_value },
        headers = headers or {},
    )


def _stored( repo ):
    """The response dict the door handed the repository — exactly one write expected."""
    assert repo.update_response.call_count == 1, (
        f"expected exactly one stored answer, got {repo.update_response.call_count}"
    )
    return repo.update_response.call_args[ 0 ][ 1 ]


# ---------------------------------------------------------------------------
# 1. THE DOOR REFUSES AN UNCREDENTIALED CALLER
# ---------------------------------------------------------------------------

def test_an_anonymous_answer_is_refused_at_the_door( client, store, validators ):
    """THE ONE THE ROW EXISTS FOR. Before this row the same request reached the DB lookup."""
    r = _post( client, "yes" )

    assert r.status_code == 401, r.text
    store.get_by_id.assert_not_called()
    store.update_response.assert_not_called()


def test_a_malformed_api_key_is_refused_at_the_door( client, store, validators ):
    r = _post( client, "yes", headers={ "X-API-Key": "not-a-key" } )

    assert r.status_code == 401, r.text
    validators.key_check.assert_not_called()          # refused on shape, before any lookup
    store.update_response.assert_not_called()


def test_an_unknown_api_key_is_refused_at_the_door( client, store, validators ):
    validators.key_check.return_value = None

    r = _post( client, "yes", headers=KEY_HEADERS )

    assert r.status_code == 401, r.text
    store.update_response.assert_not_called()


# ---------------------------------------------------------------------------
# 2. AN ACCEPTED ANSWER CARRIES THE SERVER'S ANSWERED_BY
# ---------------------------------------------------------------------------

def test_a_logged_in_answer_is_accepted_and_names_its_account( client, store, validators ):
    r = _post( client, "yes", headers=JWT_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store )[ "answered_by" ] == BY_LOGIN
    assert r.json()[ "answered_by" ] == BY_LOGIN


def test_an_api_key_answer_is_accepted_and_says_so( client, store, validators ):
    r = _post( client, "yes", headers=KEY_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store )[ "answered_by" ] == BY_KEY


def test_a_request_carrying_both_headers_is_credited_to_its_key( client, store, validators ):
    """
    `require_api_key_or_jwt` tries the key FIRST, so the key is what let this caller in.
    The token's email must not be credited to it — that would turn a service account's
    answer into a login's.
    """
    r = _post( client, "yes", headers=BOTH_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store )[ "answered_by" ] == BY_KEY


def test_a_caller_cannot_forge_answered_by( client, store, validators ):
    forged = { "user_id": "someone", "account_email": "rick@example.com", "method": "jwt" }

    r = _post( client, { "value": "yes", "answered_by": forged }, headers=KEY_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store )[ "answered_by" ] == BY_KEY


# ---------------------------------------------------------------------------
# 3. EVERY ANSWER SHAPE CARRIES THE STAMP (condition 3)
# ---------------------------------------------------------------------------

def test_a_yes_no_answer_stores_who_answered( client, store, validators ):
    r = _post( client, "yes", headers=JWT_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store ) == { "value": "yes", "source": "ui", "answered_by": BY_LOGIN }


def test_a_multiple_choice_or_batch_answer_sent_as_a_json_string_stores_who_answered( client, store, validators ):
    picked = json.dumps( { "answers": { "Scope": "Close only (Recommended)" } } )

    r = _post( client, picked, headers=JWT_HEADERS )

    assert r.status_code == 200, r.text
    stored = _stored( store )
    assert stored == { "value": picked, "source": "ui", "answered_by": BY_LOGIN }
    assert N._extract_response_value( stored ) == picked     # readers see the same answer as before


def test_a_dict_answer_stores_who_answered_beside_its_own_keys( client, store, validators ):
    r = _post( client, { "value": "blue", "source": "mux" }, headers=JWT_HEADERS )

    assert r.status_code == 200, r.text
    assert _stored( store ) == { "value": "blue", "source": "mux", "answered_by": BY_LOGIN }


@pytest.mark.parametrize( "value", [ 42, [ "a", "b" ], True ] )
def test_a_bare_json_value_answer_is_wrapped_so_it_can_carry_who_answered( client, store, validators, value ):
    r = _post( client, value, headers=JWT_HEADERS )

    assert r.status_code == 200, r.text
    stored = _stored( store )
    assert stored == { "value": value, "source": "ui", "answered_by": BY_LOGIN }
    # Before this row the value was stored bare and read back as json.dumps( value ). The
    # wrapper must not change what a reader gets.
    assert N._extract_response_value( stored ) == json.dumps( value )


# ---------------------------------------------------------------------------
# 4. THE IN-MEMORY ENTRY THE WAITING ASK READS (condition 4)
# ---------------------------------------------------------------------------

def test_the_waiting_ask_is_handed_who_answered_in_memory( client, store, validators ):
    """
    Its own test because the database write and the in-memory write are two statements:
    stamp one and not the other and the stored row is right while the live asker is told
    nobody answered.
    """
    N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None, "answered_by": None }
    try:
        r = _post( client, "yes", headers=JWT_HEADERS )

        assert r.status_code == 200, r.text
        entry = N.pending_responses[ UID_STR ]
        assert entry[ "answered_by" ] == BY_LOGIN
        assert entry[ "response_data" ] == "yes"
        assert entry[ "event" ].is_set()
    finally:
        N.pending_responses.pop( UID_STR, None )


# ---------------------------------------------------------------------------
# 5. BOTH RESPONDED FRAMES HAND THE ASKER WHO ANSWERED
# ---------------------------------------------------------------------------

def test_the_live_responded_frame_hands_the_asker_who_answered():
    """
    Drives the REAL `notify_user` generator: the ack frame, then the parked wait, then the
    `responded` frame, exactly as uvicorn advances it.
    """
    async def drive():
        repo = Mock()
        repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db() ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.dict( sys.modules, _fake_main( Mock( app_debug=False, app_verbose=False ) ) ), \
             patch( "builtins.print" ):
            ws = Mock()
            ws.is_user_connected             = Mock( return_value=True )
            ws.get_user_connection_count     = Mock( return_value=1 )
            ws.user_sessions                 = {}
            ws.active_connections            = {}
            ws.user_to_email                 = {}
            ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": True } )
            ws.emit_to_user_sync             = Mock()
            out = await N.notify_user(
                authenticated_user_id="svc", message="Hello", type="custom",
                direction="ai_to_human", priority="medium", target_user="someone@example.com",
                response_requested=True, response_type="yes_no", timeout_seconds=120,
                response_default=None, human_only=False, title=None, sender_id=None,
                response_options=None, abstract=None, job_id=None, queue_name=None,
                suppress_ding=False, progress_group_id=None, prediction_hint_override=None,
                display_qualifier_widget=False, session_name=None, idempotency_key=None,
                notification_queue=Mock(), ws_manager=ws,
            )
            it  = out.body_iterator
            nid = _frame( await it.__anext__() )[ "notification_id" ]
            try:
                entry = N.pending_responses[ nid ]
                unanswered = entry[ "answered_by" ]
                entry[ "response_data" ] = "yes"
                entry[ "answered_by" ]   = BY_LOGIN
                entry[ "event" ].set()
                frame = _frame( await it.__anext__() )
                await it.aclose()
            finally:
                N.pending_responses.pop( nid, None )
        return unanswered, frame

    unanswered, frame = asyncio.run( drive() )

    assert unanswered is None, "a fresh ask's entry must say nobody has answered yet"
    assert frame[ "status" ] == "responded"
    assert frame[ "response" ] == "yes"
    assert frame[ "answered_by" ] == BY_LOGIN


@pytest.mark.parametrize( "stored, expected", [
    ( { "value": "yes", "source": "ui", "answered_by": BY_LOGIN }, BY_LOGIN ),
    ( { "value": "yes", "source": "ui" },                         None ),       # stored before the stamp existed
] )
def test_a_reattached_ask_is_handed_who_answered_from_the_row( stored, expected ):
    row = { "state": "responded", "response_value": stored, "responded_at": datetime.now( timezone.utc ) }

    async def drive():
        with patch.object( N, "_read_notification_state_sync", return_value=row ):
            gen = N._ask_reattach_generator( UID_STR, 5 )
            await gen.__anext__()                                  # the ack
            return _frame( await gen.__anext__() )

    frame = asyncio.run( drive() )

    assert frame[ "status" ] == "responded"
    assert frame[ "response" ] == "yes"
    assert frame[ "answered_by" ] == expected


# ---------------------------------------------------------------------------
# THE HELPERS, AT THEIR EDGES
# ---------------------------------------------------------------------------

def test_stamping_a_dict_answer_never_mutates_the_callers_dict():
    body = { "value": "yes", "answered_by": "forged" }

    stored = N._stored_response_dict( body, BY_LOGIN )

    assert stored == { "value": "yes", "answered_by": BY_LOGIN }
    assert body == { "value": "yes", "answered_by": "forged" }


@pytest.mark.parametrize( "stored_value", [ "yes", None, 42 ] )
def test_a_stored_value_that_is_not_a_dict_names_nobody( stored_value ):
    assert N._stored_answered_by( stored_value ) is None
