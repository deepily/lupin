"""
A notification route keyed by a user refuses a caller who is not that user (row d90baf3d).

THE DEFECT. After cc899c44 every notification route asked for a credential, but the routes that
name a user in the path — `/api/notifications/bulk/{user_email}`, `/conversation/{sender_id}/{user_email}`
and the rest — never asked whether that user was the caller. Any valid login token or API key could
read or delete anybody's history by writing another email into the URL.

THE RULE (Mr. Radio, 2026-09-16): owner-only, no admin bypass. The path key must be the caller's
user id, or the caller's email ignoring case. An API key resolves to the user who owns it.

WHAT THIS FILE PINS:

  1. the guard itself, on a probe app: id match (no lookup), email match in any case, a stranger's
     email, a vanished user, a two-key path with one stranger, a route with no user key (500)
  2. the surface: every route on the notifications router whose path names a user carries the
     guard, read off `router.routes`; the walker is proved on a probe; the denominator is a literal
  3. the door, over the real router: for each of the twelve routes a stranger's login token and a
     stranger's API key are refused 403 before any data seam is touched, and the owner is admitted

:7999-eligible — no server, no network, no persistent state; validators, user lookup and data
seams are mocked.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import cosa.rest.routers.notifications as N
from cosa.rest.middleware.path_identity import PATH_IDENTITY_PARAMS, require_path_identity_owner


OWNER_UID    = "11111111-1111-1111-1111-111111111111"
OWNER_EMAIL  = "owner@example.com"
STRANGER_UID = "22222222-2222-2222-2222-222222222222"
VICTIM_EMAIL = "victim@example.com"
VALID_KEY    = "ck_live_" + "a" * 64

JWT_HEADERS = { "Authorization": "Bearer header.payload.signature" }
KEY_HEADERS = { "X-API-Key": VALID_KEY }

USERS = {
    OWNER_UID    : { "id": OWNER_UID,    "email": OWNER_EMAIL },
    STRANGER_UID : { "id": STRANGER_UID, "email": "stranger@example.com" },
}


# ---------------------------------------------------------------------------
# 1. The guard, on a probe app
# ---------------------------------------------------------------------------

@pytest.fixture
def probe():
    """
    A probe app with one route per path shape, and the credential validator and user lookup mocked.

    Ensures:
        - yields Mock( client, lookup, set_uid ) — set_uid( uid ) picks who the token authenticates as
    """
    router = APIRouter()

    @router.get( "/by-id/{user_id}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def by_id( user_id: str ): return { "ok": True }

    @router.get( "/by-email/{user_email}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def by_email( user_email: str ): return { "ok": True }

    @router.get( "/both/{user_id}/{user_email}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def both( user_id: str, user_email: str ): return { "ok": True }

    @router.get( "/no-user/{sender_id}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def no_user( sender_id: str ): return { "ok": True }

    app = FastAPI()
    app.include_router( router )

    identity = { "uid": OWNER_UID }
    token    = AsyncMock( side_effect=lambda _t: { "uid": identity[ "uid" ] } )
    lookup   = Mock( side_effect=lambda uid: USERS.get( uid ) )

    with patch( "cosa.rest.auth.verify_token", new=token ), \
         patch( "cosa.rest.user_service.get_user_by_id", new=lookup ), \
         TestClient( app, raise_server_exceptions=False ) as client:
        yield Mock( client=client, lookup=lookup, set_uid=lambda uid: identity.update( uid=uid ) )


def test_the_callers_own_id_is_admitted_without_a_user_lookup( probe ):
    r = probe.client.get( f"/by-id/{OWNER_UID}", headers=JWT_HEADERS )
    assert r.status_code == 200, r.text
    assert not probe.lookup.called, "an id match needs no database read"


@pytest.mark.parametrize( "spelling", [ OWNER_EMAIL, OWNER_EMAIL.upper(), "Owner@Example.COM" ] )
def test_the_callers_own_email_is_admitted_in_any_case( probe, spelling ):
    r = probe.client.get( f"/by-email/{spelling}", headers=JWT_HEADERS )
    assert r.status_code == 200, r.text
    probe.lookup.assert_called_once_with( OWNER_UID )


@pytest.mark.parametrize( "url", [ f"/by-email/{VICTIM_EMAIL}", f"/by-id/{STRANGER_UID}" ] )
def test_another_users_key_is_refused( probe, url ):
    r = probe.client.get( url, headers=JWT_HEADERS )
    assert r.status_code == 403, r.text
    assert "not the authenticated caller" in r.json()[ "detail" ]


def test_a_caller_whose_user_record_is_gone_is_refused( probe ):
    probe.set_uid( "33333333-3333-3333-3333-333333333333" )
    r = probe.client.get( f"/by-email/{OWNER_EMAIL}", headers=JWT_HEADERS )
    assert r.status_code == 403, r.text


def test_a_two_key_path_is_refused_when_either_key_is_a_stranger( probe ):
    assert probe.client.get( f"/both/{OWNER_UID}/{OWNER_EMAIL}",  headers=JWT_HEADERS ).status_code == 200
    assert probe.client.get( f"/both/{OWNER_UID}/{VICTIM_EMAIL}", headers=JWT_HEADERS ).status_code == 403
    assert probe.client.get( f"/both/{STRANGER_UID}/{OWNER_EMAIL}", headers=JWT_HEADERS ).status_code == 403


def test_a_route_that_names_no_user_is_a_wiring_error_not_an_open_door( probe ):
    r = probe.client.get( "/no-user/s1", headers=JWT_HEADERS )
    assert r.status_code == 500, r.text
    assert not probe.lookup.called


def test_no_credential_is_refused_401_before_the_owner_check( probe ):
    r = probe.client.get( f"/by-email/{OWNER_EMAIL}" )
    assert r.status_code == 401
    assert not probe.lookup.called


# ---------------------------------------------------------------------------
# 2. The surface: every user-keyed route on the router
# ---------------------------------------------------------------------------

def _dependency_calls( dependant ):
    """Every callable in a route's dependency tree, depth-first."""
    calls = []
    for sub in dependant.dependencies:
        if sub.call is not None: calls.append( sub.call )
        calls.extend( _dependency_calls( sub ) )
    return calls


def _names_a_user( route ):
    """True when a path parameter of the route is one of the guard's identity names."""
    return any( p.name in PATH_IDENTITY_PARAMS for p in route.dependant.path_params )


def _is_owner_guarded( route ):
    return require_path_identity_owner in _dependency_calls( route.dependant )


def _api_routes( router ):
    return [ r for r in router.routes if isinstance( r, APIRoute ) ]


def test_the_walker_tells_a_guarded_user_route_from_an_unguarded_one():
    """The instrument is proved before it is trusted."""
    probe = APIRouter()

    @probe.get( "/open/{user_email}" )
    async def open_route( user_email: str ): return {}

    @probe.get( "/guarded/{user_id}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def guarded_route( user_id: str ): return {}

    @probe.get( "/unkeyed/{sender_id}" )
    async def unkeyed_route( sender_id: str ): return {}

    verdicts = { r.path: ( _names_a_user( r ), _is_owner_guarded( r ) ) for r in _api_routes( probe ) }
    assert verdicts == {
        "/open/{user_email}"   : ( True,  False ),
        "/guarded/{user_id}"   : ( True,  True  ),
        "/unkeyed/{sender_id}" : ( False, False ),
    }


def test_the_router_names_exactly_the_twelve_user_keyed_routes():
    """A loop over nothing passes — so the population is pinned to a literal first."""
    keyed = { r.endpoint.__name__ for r in _api_routes( N.router ) if _names_a_user( r ) }
    assert keyed == {
        "get_user_notifications", "get_next_notification", "bulk_delete_notifications",
        "get_senders_with_activity", "get_sender_conversation", "delete_sender_conversation",
        "get_sender_conversation_by_date", "soft_delete_by_date", "get_sender_date_summaries",
        "get_visible_senders", "get_active_conversation", "get_project_sessions",
    }


@pytest.mark.parametrize( "route", _api_routes( N.router ), ids=lambda r: f"{r.endpoint.__name__}" )
def test_a_route_carries_the_owner_guard_iff_it_names_a_user( route ):
    assert _is_owner_guarded( route ) == _names_a_user( route ), (
        f"{sorted( route.methods )} {route.path} ({route.endpoint.__name__}): names a user = "
        f"{_names_a_user( route )}, owner-guarded = {_is_owner_guarded( route )} — a route naming a "
        "user needs Depends( require_path_identity_owner ); one naming nobody must not carry it"
    )


# ---------------------------------------------------------------------------
# 3. The door, over the real router
# ---------------------------------------------------------------------------

# ( handler name, method, url template ) — {who} is the user written into the path.
ROUTES = [
    ( "get_user_notifications",          "GET",    "/api/notifications/{who}" ),
    ( "get_next_notification",           "GET",    "/api/notifications/{who}/next" ),
    ( "bulk_delete_notifications",       "DELETE", "/api/notifications/bulk/{who}" ),
    ( "get_senders_with_activity",       "GET",    "/api/notifications/senders/{who}" ),
    ( "get_sender_conversation",         "GET",    "/api/notifications/conversation/s1/{who}" ),
    ( "delete_sender_conversation",      "DELETE", "/api/notifications/conversation/s1/{who}" ),
    ( "get_sender_conversation_by_date", "GET",    "/api/notifications/conversation-by-date/s1/{who}" ),
    ( "soft_delete_by_date",             "DELETE", "/api/notifications/date/s1/{who}/2026-09-16" ),
    ( "get_sender_date_summaries",       "GET",    "/api/notifications/sender-dates/s1/{who}" ),
    ( "get_visible_senders",             "GET",    "/api/notifications/senders-visible/{who}" ),
    ( "get_active_conversation",         "GET",    "/api/notifications/active-conversation/{who}" ),
    ( "get_project_sessions",            "GET",    "/api/notifications/project-sessions/lupin/{who}" ),
]
ROUTE_IDS = [ r[ 0 ] for r in ROUTES ]


def test_the_http_table_covers_every_user_keyed_route():
    keyed = { r.endpoint.__name__ for r in _api_routes( N.router ) if _names_a_user( r ) }
    assert set( ROUTE_IDS ) == keyed


@pytest.fixture
def door():
    """
    The real router with every data seam mocked, a login token and an API key both authenticating
    as OWNER_UID, and the user lookup answering from USERS.

    Ensures:
        - yields Mock( client, touched ) — touched() is True when any data seam was reached
    """
    queue = Mock()
    queue.get_user_notifications.return_value = []
    queue.get_next_unplayed.return_value      = None

    repo = Mock()
    repo.bulk_delete_by_user.return_value                = 0
    repo.get_sender_last_activities.return_value         = []
    repo.get_sender_conversation.return_value            = []
    repo.delete_by_sender.return_value                   = 0
    repo.get_sender_conversations_by_date.return_value   = {}
    repo.soft_delete_by_date.return_value                = 0
    repo.get_sender_date_summaries.return_value          = []
    repo.get_sender_last_activities_visible.return_value = []
    repo.get_active_conversation.return_value            = None
    repo.get_sessions_for_project.return_value           = []
    repo_cls = Mock( return_value=repo )

    get_db = MagicMock()
    get_db.return_value.__enter__.return_value = Mock()

    by_email = Mock( return_value={ "id": OWNER_UID } )
    by_id    = Mock( side_effect=lambda uid: USERS.get( uid ) )

    app = FastAPI()
    app.include_router( N.router )
    app.dependency_overrides[ N.get_notification_queue ] = lambda: queue

    with ExitStack() as stack:
        stack.enter_context( patch.object( N, "get_db", get_db ) )
        stack.enter_context( patch.object( N, "NotificationRepository", repo_cls ) )
        stack.enter_context( patch.object( N, "get_local_timestamp", return_value="2026-09-16T18:30:00-04:00" ) )
        stack.enter_context( patch( "cosa.rest.user_service.get_user_by_email", by_email ) )
        stack.enter_context( patch( "cosa.rest.user_service.get_user_by_id", by_id ) )
        stack.enter_context( patch( "cosa.rest.middleware.api_key_auth.validate_api_key", new=AsyncMock( return_value=OWNER_UID ) ) )
        stack.enter_context( patch( "cosa.rest.auth.verify_token", new=AsyncMock( return_value={ "uid": OWNER_UID } ) ) )
        stack.enter_context( patch( "builtins.print" ) )
        client = stack.enter_context( TestClient( app, raise_server_exceptions=False ) )

        def touched():
            return bool( queue.method_calls ) or by_email.called or repo_cls.called or get_db.called

        yield Mock( client=client, touched=touched )


@pytest.mark.parametrize( "headers", [ JWT_HEADERS, KEY_HEADERS ], ids=[ "login-token", "api-key" ] )
@pytest.mark.parametrize( "name, method, url", ROUTES, ids=ROUTE_IDS )
def test_a_stranger_is_refused_before_the_handler( door, name, method, url, headers ):
    r = door.client.request( method, url.format( who=VICTIM_EMAIL ), headers=headers )
    assert r.status_code == 403, f"{name}: {method} for another user answered {r.status_code}: {r.text}"
    assert not door.touched(), f"{name}: the handler reached a data seam for a stranger"


@pytest.mark.parametrize( "headers", [ JWT_HEADERS, KEY_HEADERS ], ids=[ "login-token", "api-key" ] )
@pytest.mark.parametrize( "name, method, url", ROUTES, ids=ROUTE_IDS )
def test_the_owner_is_admitted( door, name, method, url, headers ):
    r = door.client.request( method, url.format( who=OWNER_EMAIL ), headers=headers )
    assert 200 <= r.status_code < 300, f"{name}: the owner's {method} answered {r.status_code}: {r.text}"
