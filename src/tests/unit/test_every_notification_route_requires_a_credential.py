"""
Every notification route asks for a credential (row cc899c44).

THE DEFECT. Measured at 327dcd04 on 2026-09-10: 15 of the 23 handlers in
src/cosa/rest/routers/notifications.py declared no credential dependency, and nothing added one at
the router, at `include_router`, or in app middleware. `DELETE /api/notifications/bulk/{user_email}`
wiped a user's whole history for any caller that could reach the port, and
`POST /api/notifications/generate-gist` spent LLM calls for anyone. The fix is the answer door's
pattern (e20e249a): `require_api_key_or_jwt` on each route.

WHAT THIS FILE PINS:

  1. every route on the router — read off `router.routes`, never a hand list — carries
     `require_api_key_or_jwt` in its dependency tree, and the walker is shown to catch a route that
     does not
  2. at the HTTP door, through TestClient over the real router with only the token validators and
     data seams mocked, each formerly-anonymous route:
       - refuses a caller with no credential, before its handler touches any data seam
       - refuses a malformed API key
       - admits a login token and an API key with a 2xx

Authorization — whether the email in the path belongs to the caller — is deliberately NOT here.
Mr. Radio ruled it a separate row (d90baf3d), because API-key seats carry no email.

:7999-eligible — no server, no network, no persistent state; the DB, user lookup and token
validators are mocked.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from fastapi import FastAPI

import cosa.rest.routers.notifications as N
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


UID_STR    = "12345678-1234-5678-1234-567812345678"
EMAIL      = "person@example.com"
VALID_KEY  = "ck_live_" + "a" * 64

JWT_HEADERS = { "Authorization": "Bearer header.payload.signature" }
KEY_HEADERS = { "X-API-Key": VALID_KEY }
BAD_KEY     = { "X-API-Key": "not-a-key" }


# The fifteen routes this row guarded, as (handler name, method, url, json body). A hand list on
# purpose — it is the HTTP table, and `test_the_http_table_is_exactly_the_routes_this_row_guarded`
# pins it to literals so it cannot quietly shrink. The router walk below is the surface guard.
ROUTES = [
    ( "get_user_notifications",          "GET",    f"/api/notifications/{EMAIL}",                                None ),
    ( "get_next_notification",           "GET",    f"/api/notifications/{EMAIL}/next",                           None ),
    ( "mark_notification_played",        "POST",   "/api/notifications/abc123/played",                           None ),
    ( "delete_notification",             "DELETE", "/api/notifications/abc123",                                  None ),
    ( "bulk_delete_notifications",       "DELETE", f"/api/notifications/bulk/{EMAIL}",                           None ),
    ( "get_senders_with_activity",       "GET",    f"/api/notifications/senders/{EMAIL}",                        None ),
    ( "get_sender_conversation",         "GET",    f"/api/notifications/conversation/s1/{EMAIL}",                None ),
    ( "delete_sender_conversation",      "DELETE", f"/api/notifications/conversation/s1/{EMAIL}",                None ),
    ( "get_sender_conversation_by_date", "GET",    f"/api/notifications/conversation-by-date/s1/{EMAIL}",        None ),
    ( "soft_delete_by_date",             "DELETE", f"/api/notifications/date/s1/{EMAIL}/2026-09-10",             None ),
    ( "get_sender_date_summaries",       "GET",    f"/api/notifications/sender-dates/s1/{EMAIL}",                None ),
    ( "get_visible_senders",             "GET",    f"/api/notifications/senders-visible/{EMAIL}",                None ),
    ( "get_active_conversation",         "GET",    f"/api/notifications/active-conversation/{EMAIL}",            None ),
    ( "get_project_sessions",            "GET",    f"/api/notifications/project-sessions/lupin/{EMAIL}",         None ),
    ( "generate_session_gist",           "POST",   "/api/notifications/generate-gist",                           { "messages": [], "abstracts": [] } ),
]
ROUTE_IDS = [ r[ 0 ] for r in ROUTES ]


# ---------------------------------------------------------------------------
# The surface: every route on the router
# ---------------------------------------------------------------------------

def _dependency_calls( dependant ):
    """Every callable in a route's dependency tree, depth-first."""
    calls = []
    for sub in dependant.dependencies:
        if sub.call is not None: calls.append( sub.call )
        calls.extend( _dependency_calls( sub ) )
    return calls


def _requires_credential( route ):
    """True when `require_api_key_or_jwt` is anywhere in the route's dependency tree."""
    return require_api_key_or_jwt in _dependency_calls( route.dependant )


def _api_routes( router ):
    return [ r for r in router.routes if isinstance( r, APIRoute ) ]


def test_the_walker_catches_a_route_without_a_credential():
    """
    The instrument is proved before it is trusted: an unguarded route reads False, a guarded one
    True, whether the guard sits in the signature or in the decorator.
    """
    probe = APIRouter()

    @probe.get( "/open" )
    async def open_route(): return {}

    @probe.get( "/decorated", dependencies=[ Depends( require_api_key_or_jwt ) ] )
    async def decorated_route(): return {}

    @probe.get( "/signature" )
    async def signature_route( uid: str = Depends( require_api_key_or_jwt ) ): return {}

    verdicts = { r.path: _requires_credential( r ) for r in _api_routes( probe ) }
    assert verdicts == { "/open": False, "/decorated": True, "/signature": True }


def test_the_router_walk_reads_every_route():
    """A loop over nothing passes every assertion in it — so the denominator is asserted first."""
    routes = _api_routes( N.router )
    assert len( routes ) >= 23, f"the notifications router exposes only {len( routes )} routes — the walk lost them"


@pytest.mark.parametrize( "route", _api_routes( N.router ), ids=lambda r: r.endpoint.__name__ )
def test_every_notification_route_requires_a_credential( route ):
    assert _requires_credential( route ), (
        f"{sorted( route.methods )} {route.path} ({route.endpoint.__name__}) takes no credential — "
        "add dependencies=[ Depends( require_api_key_or_jwt ) ] or a reviewed public reason"
    )


def test_the_http_table_is_exactly_the_routes_this_row_guarded():
    """The table below cannot drop a route without this failing; each name is on the router."""
    assert set( ROUTE_IDS ) == {
        "get_user_notifications", "get_next_notification", "mark_notification_played",
        "delete_notification", "bulk_delete_notifications", "get_senders_with_activity",
        "get_sender_conversation", "delete_sender_conversation", "get_sender_conversation_by_date",
        "soft_delete_by_date", "get_sender_date_summaries", "get_visible_senders",
        "get_active_conversation", "get_project_sessions", "generate_session_gist",
    }
    on_router = { r.endpoint.__name__ for r in _api_routes( N.router ) }
    assert set( ROUTE_IDS ) <= on_router


# ---------------------------------------------------------------------------
# The door: TestClient over the real router
# ---------------------------------------------------------------------------

@pytest.fixture
def seams():
    """
    Every data seam the fifteen handlers reach, mocked to answer with empty data.

    Ensures:
        - yields a Mock whose attributes record whether a handler touched the queue, the user
          lookup or the repository — the proof a refusal happened BEFORE the handler ran
    """
    queue = Mock()
    queue.get_user_notifications.return_value = []
    queue.get_next_unplayed.return_value      = None
    queue.mark_played.return_value            = True
    queue.delete_by_id_hash.return_value      = True

    repo = Mock()
    repo.bulk_delete_by_user.return_value               = 0
    repo.get_sender_last_activities.return_value        = []
    repo.get_sender_conversation.return_value           = []
    repo.delete_by_sender.return_value                  = 0
    repo.get_sender_conversations_by_date.return_value  = {}
    repo.soft_delete_by_date.return_value               = 0
    repo.get_sender_date_summaries.return_value         = []
    repo.get_sender_last_activities_visible.return_value = []
    repo.get_active_conversation.return_value           = None
    repo.get_sessions_for_project.return_value          = []
    repo_cls = Mock( return_value=repo )

    get_db = MagicMock()
    get_db.return_value.__enter__.return_value = Mock()

    user_lookup = Mock( return_value={ "id": UID_STR } )

    with ExitStack() as stack:
        stack.enter_context( patch.object( N, "get_db", get_db ) )
        stack.enter_context( patch.object( N, "NotificationRepository", repo_cls ) )
        stack.enter_context( patch( "cosa.rest.user_service.get_user_by_email", user_lookup ) )
        # get_local_timestamp() imports lupin_app.main; the queue routes stamp their reply with it.
        stack.enter_context( patch.object( N, "get_local_timestamp", return_value="2026-09-10T20:00:00-04:00" ) )
        stack.enter_context( patch( "builtins.print" ) )
        yield Mock( queue=queue, repo_cls=repo_cls, user_lookup=user_lookup, get_db=get_db )


@pytest.fixture
def validators():
    """The two validators the real credential dependency calls, and nothing above them."""
    key_check   = AsyncMock( return_value="svc-user" )
    token_check = AsyncMock( return_value={ "uid": "login-user" } )
    with patch( "cosa.rest.middleware.api_key_auth.validate_api_key", new=key_check ), \
         patch( "cosa.rest.auth.verify_token", new=token_check ):
        yield Mock( key_check=key_check, token_check=token_check )


@pytest.fixture
def client( seams, validators ):
    app = FastAPI()
    app.include_router( N.router )
    app.dependency_overrides[ N.get_notification_queue ] = lambda: seams.queue
    with TestClient( app, raise_server_exceptions=False ) as c:
        yield c
    app.dependency_overrides.clear()


def _call( client, method, url, body, headers ):
    return client.request( method, url, json=body, headers=headers )


def _untouched( seams ):
    """No data seam was reached."""
    return (
        not seams.queue.method_calls
        and not seams.user_lookup.called
        and not seams.repo_cls.called
        and not seams.get_db.called
    )


@pytest.mark.parametrize( "name, method, url, body", ROUTES, ids=ROUTE_IDS )
def test_a_caller_with_no_credential_is_refused_before_the_handler( client, seams, validators, name, method, url, body ):
    response = _call( client, method, url, body, {} )

    assert response.status_code == 401, f"{name}: anonymous {method} {url} answered {response.status_code}"
    assert _untouched( seams ), f"{name}: the handler reached a data seam for an anonymous caller"


@pytest.mark.parametrize( "name, method, url, body", ROUTES, ids=ROUTE_IDS )
def test_a_malformed_api_key_is_refused( client, seams, validators, name, method, url, body ):
    response = _call( client, method, url, body, BAD_KEY )

    assert response.status_code == 401, f"{name}: a malformed key answered {response.status_code}"
    assert not validators.key_check.called, "a malformed key reached the database check"
    assert _untouched( seams )


@pytest.mark.parametrize( "name, method, url, body", ROUTES, ids=ROUTE_IDS )
def test_a_login_token_is_admitted( client, seams, validators, name, method, url, body ):
    response = _call( client, method, url, body, JWT_HEADERS )

    assert 200 <= response.status_code < 300, f"{name}: a valid login answered {response.status_code}: {response.text}"
    assert validators.token_check.await_count == 1, f"{name}: the token was not validated exactly once"


@pytest.mark.parametrize( "name, method, url, body", ROUTES, ids=ROUTE_IDS )
def test_an_api_key_is_admitted( client, seams, validators, name, method, url, body ):
    response = _call( client, method, url, body, KEY_HEADERS )

    assert 200 <= response.status_code < 300, f"{name}: a valid API key answered {response.status_code}: {response.text}"
    assert validators.key_check.await_count == 1, f"{name}: the key was not validated exactly once"
