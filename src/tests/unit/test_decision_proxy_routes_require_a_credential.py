"""
Every decision-proxy route but one refuses an anonymous caller (row 2d6f2221).

THE DEFECT, measured 2026-09-24 on the unfixed router with the database mocked: an anonymous
caller got 200 from acknowledge, pending, trust and decisions, and reached the ratify and delete
handlers (they failed only on the fake decision id). Only /mode answered 401. So anyone who could
reach the port could read any user's pending decisions and trust state, list every user's decision
history, and approve, reject or delete decisions in another user's name.

THE RULE:
    trust/{user_email}                         the caller's own email (path-owner guard)
    pending/{user_email}, ratify, decision     admin only — decisions carry no owner, so the queue
    decisions/{domain}/{category}              is the whole fleet's and a row is found by id alone
    acknowledge                                any valid login or API key
    mode (GET, PUT)                            a login, as before
    batch-id                                   PUBLIC, deliberately — see PUBLIC_PROXY_ROUTES

WHY ADMIN AND NOT OWNER for pending/ratify/delete: the first cut guarded them with an owner check
on the `user_email` the caller names. The adversarial review found that ProxyDecision has no user
column, `get_pending` never receives the email, and ratify/delete look a row up by id — so any user
who named themselves read the whole queue and could approve or delete anyone's decision. An owner
check on a value the handler ignores guards nothing.

WHAT THIS FILE PINS, over the real router:
  1. the door: no credential → 401 on every route except the one public route, a literal
     denominator of nine routes, and the public list read from the module
  2. the admin routes refuse a non-admin even when it names its own email, before any data seam,
     and admit an admin
  3. trust refuses a stranger's email before the data seam and admits the owner (the path guard
     itself is pinned by test_notification_routes_refuse_another_users_path.py)

:7999-eligible — no server, no network, no persistent state; credentials, user lookup and the
database are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.decision_proxy as D


OWNER_UID    = "11111111-1111-1111-1111-111111111111"
OWNER_EMAIL  = "owner@example.com"
VICTIM_EMAIL = "victim@example.com"
DECISION_ID  = "33333333-3333-3333-3333-333333333333"

JWT = { "Authorization": "Bearer header.payload.signature" }

USERS = { OWNER_UID: { "id": OWNER_UID, "email": OWNER_EMAIL } }


# ---------------------------------------------------------------------------
# The real router
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


ADMIN_ONLY = [
    ( "GET",    "/api/proxy/pending/{user_email}" ),
    ( "POST",   "/api/proxy/ratify/{decision_id}" ),
    ( "DELETE", "/api/proxy/decision/{decision_id}" ),
    ( "GET",    "/api/proxy/decisions/{domain}/{category}" ),
]


@pytest.mark.parametrize( "key", ADMIN_ONLY, ids=lambda k: f"{k[ 0 ]} {k[ 1 ]}" )
def test_a_non_admin_naming_its_own_email_is_refused_before_any_data_is_touched( real, key ):
    url, params = ROUTES[ key ]
    r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
    assert r.status_code == 403, f"{key}: a non-admin was let in with {r.status_code}"
    assert not real.repo.called and not real.trust.called, "the refusal must come before the database"


def test_an_admin_reads_the_pending_queue_and_the_decision_history( real ):
    real.identity[ "roles" ] = [ "user", "admin" ]
    for key in ( ( "GET", "/api/proxy/pending/{user_email}" ), ( "GET", "/api/proxy/decisions/{domain}/{category}" ) ):
        url, params = ROUTES[ key ]
        r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
        assert r.status_code == 200, f"{key}: {r.status_code} {r.text}"


def test_an_admin_reaches_the_ratify_and_delete_handlers( real ):
    # The mocked repository finds no such decision; reaching that answer proves the guard let the admin through.
    real.identity[ "roles" ] = [ "user", "admin" ]
    real.repo.return_value.get_by_id.return_value = None
    for key in ( ( "POST", "/api/proxy/ratify/{decision_id}" ), ( "DELETE", "/api/proxy/decision/{decision_id}" ) ):
        url, params = ROUTES[ key ]
        r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
        assert r.status_code not in ( 401, 403 ), f"{key}: {r.status_code} {r.text}"
        assert real.repo.called, f"{key}: the admin never reached the handler"


def test_another_users_trust_state_is_refused_before_any_data_is_touched( real ):
    url, _ = ROUTES[ ( "GET", "/api/proxy/trust/{user_email}" ) ]
    r = real.client.get( url.replace( OWNER_EMAIL, VICTIM_EMAIL ), headers=JWT )
    assert r.status_code == 403, r.text
    assert not real.trust.called, "the refusal must come before the database"


@pytest.mark.parametrize( "key", [
    ( "GET",  "/api/proxy/trust/{user_email}" ),
    ( "POST", "/api/proxy/acknowledge" ),
], ids=lambda k: f"{k[ 0 ]} {k[ 1 ]}" )
def test_an_ordinary_user_is_admitted_to_its_own_trust_and_to_acknowledge( real, key ):
    url, params = ROUTES[ key ]
    r = real.client.request( key[ 0 ], url, params=params, headers=JWT )
    assert r.status_code == 200, r.text
