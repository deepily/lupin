"""
Every decision-proxy route but one refuses an anonymous caller (row 2d6f2221).

THE DEFECT, measured 2026-09-24 on the unfixed router with the database mocked: an anonymous
caller got 200 from acknowledge, pending, trust and decisions, and reached the ratify and delete
handlers (they failed only on the fake decision id). Only /mode answered 401. So anyone who could
reach the port could read any user's pending decisions and trust state, list every user's decision
history, and approve, reject or delete decisions in another user's name.

THE RULE:
    pending/{user_email}, trust/{user_email}   the caller's own email (path-owner guard)
    ratify, decision  ?user_email=…            the caller's own email (query-owner guard)
    decisions/{domain}/{category}              admin only — it returns every user's decisions
    acknowledge                                any valid login or API key
    mode (GET, PUT)                            a login, as before
    batch-id                                   PUBLIC, deliberately — see PUBLIC_PROXY_ROUTES

WHAT THIS FILE PINS:
  1. the query-owner guard, on a probe app (the path guard is pinned by
     test_notification_routes_refuse_another_users_path.py)
  2. the door, over the real router: no credential → 401 on every route except the one public
     route, a literal denominator of nine routes, and the public list read from the module
  3. ownership over the real router: a stranger's email is refused 403 before any data seam, the
     owner is admitted, and a non-admin is refused the cross-user history

:7999-eligible — no server, no network, no persistent state; credentials, user lookup and the
database are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.decision_proxy as D
from cosa.rest.middleware.path_identity import require_query_identity_owner


OWNER_UID    = "11111111-1111-1111-1111-111111111111"
OWNER_EMAIL  = "owner@example.com"
VICTIM_EMAIL = "victim@example.com"
DECISION_ID  = "33333333-3333-3333-3333-333333333333"

JWT = { "Authorization": "Bearer header.payload.signature" }

USERS = { OWNER_UID: { "id": OWNER_UID, "email": OWNER_EMAIL } }


# ---------------------------------------------------------------------------
# 1. The query-owner guard, on a probe app
# ---------------------------------------------------------------------------

@pytest.fixture
def probe():
    router = APIRouter()

    @router.post( "/act", dependencies=[ Depends( require_query_identity_owner ) ] )
    async def act( user_email: str ): return { "ok": True }

    @router.post( "/act-by-id", dependencies=[ Depends( require_query_identity_owner ) ] )
    async def act_by_id( user_id: str ): return { "ok": True }

    @router.post( "/unkeyed", dependencies=[ Depends( require_query_identity_owner ) ] )
    async def unkeyed(): return { "ok": True }

    app = FastAPI()
    app.include_router( router )
    identity = { "uid": OWNER_UID }
    token    = AsyncMock( side_effect=lambda _t: { "uid": identity[ "uid" ] } )
    lookup   = Mock( side_effect=lambda uid: USERS.get( uid ) )
    with patch( "cosa.rest.auth.verify_token", new=token ), \
         patch( "cosa.rest.user_service.get_user_by_id", new=lookup ), \
         TestClient( app, raise_server_exceptions=False ) as client:
        yield Mock( client=client, lookup=lookup, set_uid=lambda uid: identity.update( uid=uid ) )


@pytest.mark.parametrize( "spelling", [ OWNER_EMAIL, OWNER_EMAIL.upper() ] )
def test_the_callers_own_email_in_the_query_is_admitted_in_any_case( probe, spelling ):
    r = probe.client.post( "/act", params={ "user_email": spelling }, headers=JWT )
    assert r.status_code == 200, r.text


def test_the_callers_own_id_in_the_query_needs_no_lookup( probe ):
    r = probe.client.post( "/act-by-id", params={ "user_id": OWNER_UID }, headers=JWT )
    assert r.status_code == 200, r.text
    assert not probe.lookup.called


def test_another_users_email_in_the_query_is_refused( probe ):
    r = probe.client.post( "/act", params={ "user_email": VICTIM_EMAIL }, headers=JWT )
    assert r.status_code == 403, r.text
    assert r.json()[ "detail" ] == "The user named in this query is not the authenticated caller"


def test_a_caller_whose_record_is_gone_is_refused( probe ):
    probe.set_uid( "44444444-4444-4444-4444-444444444444" )
    assert probe.client.post( "/act", params={ "user_email": OWNER_EMAIL }, headers=JWT ).status_code == 403


def test_a_route_whose_query_names_no_user_is_a_wiring_error_not_a_pass( probe ):
    r = probe.client.post( "/unkeyed", headers=JWT )
    assert r.status_code == 500, r.text


def test_no_credential_is_refused_before_the_owner_check( probe ):
    assert probe.client.post( "/act", params={ "user_email": OWNER_EMAIL } ).status_code == 401


# ---------------------------------------------------------------------------
# 2 + 3. The real router
# ---------------------------------------------------------------------------

# Every route on the router, with a request that would reach its handler if nothing stopped it.
# NINE, as a literal: a new route that is not listed here reddens the count test below.
ROUTES = {
    ( "POST",   "/api/proxy/acknowledge" )               : ( "/api/proxy/acknowledge", {} ),
    ( "GET",    "/api/proxy/batch-id" )                  : ( "/api/proxy/batch-id", {} ),
    ( "GET",    "/api/proxy/pending/{user_email}" )      : ( f"/api/proxy/pending/{OWNER_EMAIL}", {} ),
    ( "POST",   "/api/proxy/ratify/{decision_id}" )      : ( f"/api/proxy/ratify/{DECISION_ID}", { "approved": "true", "user_email": OWNER_EMAIL } ),
    ( "DELETE", "/api/proxy/decision/{decision_id}" )    : ( f"/api/proxy/decision/{DECISION_ID}", { "user_email": OWNER_EMAIL } ),
    ( "GET",    "/api/proxy/trust/{user_email}" )        : ( f"/api/proxy/trust/{OWNER_EMAIL}", {} ),
    ( "GET",    "/api/proxy/decisions/{domain}/{category}" ) : ( "/api/proxy/decisions/swe/testing", {} ),
    ( "GET",    "/api/proxy/mode" )                      : ( "/api/proxy/mode", {} ),
    ( "PUT",    "/api/proxy/mode" )                      : ( "/api/proxy/mode", {} ),
}


def _router_routes():
    return { ( m, r.path ) for r in D.router.routes for m in r.methods }


def test_the_route_list_here_is_the_router_exactly():
    assert len( ROUTES ) == 9
    assert _router_routes() == set( ROUTES ), "a route was added or removed — list it here and decide its guard"


def test_the_public_list_is_exactly_batch_id():
    assert D.PUBLIC_PROXY_ROUTES == ( ( "GET", "/api/proxy/batch-id" ), )
    assert set( D.PUBLIC_PROXY_ROUTES ) <= set( ROUTES )


@pytest.fixture
def real():
    """The real router, the database mocked so an unguarded handler would answer 200, not crash."""
    app = FastAPI()
    app.include_router( D.router )
    repo = MagicMock()
    repo.return_value.get_pending.return_value            = []
    repo.return_value.get_by_domain_category.return_value = []
    trust = MagicMock()
    trust.return_value.get_by_user.return_value = []
    identity = { "uid": OWNER_UID, "roles": [ "user" ] }
    token    = AsyncMock( side_effect=lambda _t: { "uid": identity[ "uid" ], "roles": identity[ "roles" ] } )
    lookup   = Mock( side_effect=lambda uid: USERS.get( uid ) )
    with patch.object( D, "get_db", MagicMock() ), \
         patch.object( D, "ProxyDecisionRepository", repo ), \
         patch.object( D, "TrustStateRepository", trust ), \
         patch( "cosa.rest.auth.verify_token", new=token ), \
         patch( "cosa.rest.auth_middleware.verify_token", new=token ), \
         patch( "cosa.rest.user_service.get_user_by_id", new=lookup ), \
         TestClient( app, raise_server_exceptions=False ) as client:
        # ⚠️ auth_middleware imports verify_token BY NAME, so patching cosa.rest.auth alone leaves
        # require_admin validating for real — every admin case answers 401 and reads like a gate.
        yield Mock( client=client, repo=repo, trust=trust, identity=identity )


@pytest.mark.parametrize( "key", sorted( ROUTES ), ids=lambda k: f"{k[ 0 ]} {k[ 1 ]}" )
def test_no_credential_is_refused_on_every_route_but_the_public_one( real, key ):
    url, params = ROUTES[ key ]
    r = real.client.request( key[ 0 ], url, params=params )
    if key in D.PUBLIC_PROXY_ROUTES:
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 401, f"{key} answered {r.status_code} to an anonymous caller: {r.text[ :200 ]}"


@pytest.mark.parametrize( "key", [
    ( "GET",    "/api/proxy/pending/{user_email}" ),
    ( "GET",    "/api/proxy/trust/{user_email}" ),
    ( "POST",   "/api/proxy/ratify/{decision_id}" ),
    ( "DELETE", "/api/proxy/decision/{decision_id}" ),
], ids=lambda k: f"{k[ 0 ]} {k[ 1 ]}" )
def test_another_users_email_is_refused_before_any_data_is_touched( real, key ):
    url, params = ROUTES[ key ]
    url    = url.replace( OWNER_EMAIL, VICTIM_EMAIL )
    params = { k: ( VICTIM_EMAIL if v == OWNER_EMAIL else v ) for k, v in params.items() }
    r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
    assert r.status_code == 403, r.text
    assert not real.repo.called and not real.trust.called, "the refusal must come before the database"


@pytest.mark.parametrize( "key", [
    ( "GET", "/api/proxy/pending/{user_email}" ),
    ( "GET", "/api/proxy/trust/{user_email}" ),
    ( "POST", "/api/proxy/acknowledge" ),
], ids=lambda k: f"{k[ 0 ]} {k[ 1 ]}" )
def test_the_owner_is_admitted( real, key ):
    url, params = ROUTES[ key ]
    r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
    assert r.status_code == 200, r.text


def test_the_owner_reaches_the_ratify_and_delete_handlers( real ):
    # The mocked repository finds no such decision; reaching that answer proves the guard let the owner through.
    real.repo.return_value.get_by_id.return_value = None
    for key in ( ( "POST", "/api/proxy/ratify/{decision_id}" ), ( "DELETE", "/api/proxy/decision/{decision_id}" ) ):
        url, params = ROUTES[ key ]
        r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
        assert r.status_code not in ( 401, 403 ), f"{key}: {r.status_code} {r.text}"
        assert real.repo.called, f"{key}: the owner never reached the handler"


def test_every_users_decision_history_is_admin_only( real ):
    url, _ = ROUTES[ ( "GET", "/api/proxy/decisions/{domain}/{category}" ) ]
    assert real.client.get( url, headers=JWT ).status_code == 403, "a non-admin must not read every user's decisions"
    real.identity[ "roles" ] = [ "user", "admin" ]
    assert real.client.get( url, headers=JWT ).status_code == 200
