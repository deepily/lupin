"""
The decision-proxy user routes and the prediction-engine reset refuse a caller without standing (row 2d6f2221).

THE DEFECT, MEASURED AT THE PATH RATHER THAN READ OFF THE DECORATOR. Driving the real routers
through a TestClient with no credential at all, before any fix:

    GET    /api/proxy/pending/{user_email}        200   reached the handler
    GET    /api/proxy/trust/{user_email}          200   reached the handler
    GET    /api/prediction-engine/reset           200   reached the handler

`main.py` includes both routers with no `dependencies=`, and the only middleware is CORS plus a
security-header pass, so the open definition really was an open path. That distinction is the whole
point of row f9e71d8e: an unauthenticated route DEFINITION is not proof of an unauthenticated PATH,
and the converse costs just as much — so it is measured here, not inferred.

THE RULE. Owner-only for the user-keyed proxy routes, no admin bypass (Mr. Radio on d90baf3d): the
path key must be the caller's user id, or their email ignoring case.

THE RESET ENDPOINT gets three changes rather than one, because it had three separate problems:
a destructive GET (reachable by a link or a prefetch, with no form and no preflight), a destructive
parameter that defaulted ON, and no credential. It is now POST + `drop_table=False` + a credential.
It takes `require_api_key_or_jwt` rather than `require_admin`: the defect is "anyone who can reach
the port", which any valid credential closes, and this route's callers are a test harness and
internal server-side code. `/api/init` took `require_admin` because it swaps the whole server's
config block and DB connection — a different blast radius, a different bar.

WHAT THIS FILE PINS:
  1. the door, over the real routers: no credential refused, a stranger refused, the owner admitted
  2. the surface: every decision-proxy route naming a user in its path carries the owner guard,
     read off `router.routes`, with the walker proved on a probe and the denominator a literal
  3. the reset endpoint's three properties, each of which can regress on its own
  4. the schema: `/docs` shows the refusals, which a bare `Depends` does NOT cause on its own

:7999-eligible — no server, no network, no persistent state. Three seams are closed, not two: the
credential dependency is overridden, the user lookup is patched, and so is `get_db`. That third one
was NOT obvious. Without it the owner case reached a live database and returned real rows, which
made this file quietly environment-dependent AND let it pass for the wrong reason — the assertion
was "not 401 and not 403", and a 500 from an absent database satisfies that just as well as a 200.
An assertion satisfiable by more than one path cannot tell you which one ran.
"""

from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.middleware.path_identity import (
    PATH_IDENTITY_PARAMS,
    QUERY_IDENTITY_PARAMS,
    require_path_identity_owner,
    require_query_identity_owner,
)
from cosa.rest.routers.decision_proxy import router as proxy_router
from cosa.rest.routers.system import router as system_router


OWNER_UID    = "11111111-1111-1111-1111-111111111111"
OWNER_EMAIL  = "owner@example.com"
VICTIM_EMAIL = "victim@example.com"

# The user-keyed proxy routes, pinned as a LITERAL. A loop over nothing passes every assertion
# inside it, so the population is stated here and checked against the router below.
USER_KEYED_PROXY_PATHS = {
    "/api/proxy/pending/{user_email}",
    "/api/proxy/trust/{user_email}",
}


def _app( router, authenticated_uid=None ):
    """
    Mount `router` and return a client speaking as `authenticated_uid`.

    Requires:
        - router is a FastAPI APIRouter

    Ensures:
        - authenticated_uid None leaves the real credential dependency in place, so the
          client is genuinely uncredentialed and the refusal is the route's own
        - a uid overrides the credential dependency, standing in for a validated key or token
    """
    app = FastAPI()
    app.include_router( router )
    if authenticated_uid is not None:
        app.dependency_overrides[ require_api_key_or_jwt ] = lambda: authenticated_uid
    return TestClient( app, raise_server_exceptions=False )


# ---------------------------------------------------------------------------
# 1. The door, over the real decision-proxy router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "path", sorted( USER_KEYED_PROXY_PATHS ) )
def test_no_credential_is_refused( path ):
    """Ensures: the uncredentialed 200 that this row reported is now a 401."""
    response = _app( proxy_router ).get( path.replace( "{user_email}", VICTIM_EMAIL ) )
    assert response.status_code == 401


@pytest.mark.parametrize( "path", sorted( USER_KEYED_PROXY_PATHS ) )
def test_a_stranger_is_refused_before_the_handler( path ):
    """
    Ensures: a VALID credential naming someone else is refused 403.

    This is the half a bare credential check does not cover — the original hole let any
    caller read any user's data by writing their email into the URL, and simply demanding
    a token would have left that intact for anyone who has one.
    """
    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ):
        response = _app( proxy_router, OWNER_UID ).get( path.replace( "{user_email}", VICTIM_EMAIL ) )
    assert response.status_code == 403


@pytest.mark.parametrize( "path", sorted( USER_KEYED_PROXY_PATHS ) )
def test_the_owner_is_not_refused( path ):
    """
    Ensures: the caller's own email passes the gate and the handler runs.

    Asserted as exactly 200, with the data seam stood up on mocks. An earlier cut asserted
    "not 401 and not 403" and left `get_db` real: it passed, but it would have passed just as
    well against a 500 from a missing database, and it was reading live rows on a box that had
    one. Pinning the code to 200 and the seam to a mock makes the pass mean one thing.
    """
    session = MagicMock()
    db_ctx  = MagicMock()
    db_ctx.__enter__.return_value = session
    db_ctx.__exit__.return_value  = False

    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ), \
         patch( "cosa.rest.routers.decision_proxy.get_db", return_value=db_ctx ), \
         patch( "cosa.rest.routers.decision_proxy.ProxyDecisionRepository" ) as pending_repo, \
         patch( "cosa.rest.routers.decision_proxy.TrustStateRepository" ) as trust_repo:
        pending_repo.return_value.get_pending_decisions.return_value = []
        trust_repo.return_value.get_trust_states.return_value        = []
        response = _app( proxy_router, OWNER_UID ).get( path.replace( "{user_email}", OWNER_EMAIL ) )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. The surface: every user-keyed proxy route carries the guard
# ---------------------------------------------------------------------------

def _names_a_user( route ):
    """Ensures: True iff the route's path declares a parameter named in PATH_IDENTITY_PARAMS."""
    return any( "{" + name + "}" in route.path for name in PATH_IDENTITY_PARAMS )


def _carries_owner_guard( route ):
    """Ensures: True iff require_path_identity_owner is reached from this route's dependencies."""
    stack = list( route.dependant.dependencies )
    while stack:
        dep = stack.pop()
        if dep.call is require_path_identity_owner: return True
        stack.extend( dep.dependencies )
    return False


def test_the_walker_tells_a_guarded_route_from_an_unguarded_one():
    """
    Ensures: both predicates return True and False on a probe before either is trusted.

    A guard that cannot demonstrate a negative is indistinguishable from one that always
    says yes, and it would then vouch for the router no matter what the router did.
    """
    probe = APIRouter()

    @probe.get( "/guarded/{user_email}", dependencies=[ Depends( require_path_identity_owner ) ] )
    async def guarded( user_email: str ): return {}

    @probe.get( "/unguarded/{user_email}" )
    async def unguarded( user_email: str ): return {}

    @probe.get( "/no-user-key" )
    async def no_user_key(): return {}

    routes = { r.path: r for r in probe.routes if isinstance( r, APIRoute ) }
    assert _names_a_user( routes[ "/guarded/{user_email}" ] ) is True
    assert _names_a_user( routes[ "/no-user-key" ] ) is False
    assert _carries_owner_guard( routes[ "/guarded/{user_email}" ] ) is True
    assert _carries_owner_guard( routes[ "/unguarded/{user_email}" ] ) is False


def test_the_router_names_exactly_the_user_keyed_routes_this_file_pins():
    """
    Ensures: the literal population above is what the router actually holds.

    Without this, adding a third user-keyed proxy route would leave it unguarded AND
    unnoticed — the parametrized cases would keep passing over the two they know.
    """
    found = { r.path for r in proxy_router.routes if isinstance( r, APIRoute ) and _names_a_user( r ) }
    assert found == USER_KEYED_PROXY_PATHS


@pytest.mark.parametrize( "path", sorted( USER_KEYED_PROXY_PATHS ) )
def test_every_user_keyed_route_carries_the_owner_guard( path ):
    """
    Ensures: the guard is on the route itself, not merely observed through one HTTP call,
    and that the route is mounted for the verb the door arms above actually send.

    🔴 THE METHOD IS PINNED, NOT ASSUMED — and this file is the reason that rule exists.
    Matching a route by PATH alone stays green against a door whose VERB has moved, and then
    the arms above fail saying a caller was "not refused" when nothing was ever asked: a
    routing change wearing a permissions failure, which sends the next reader into the
    permissions system instead of the route table. This very commit moves
    /api/prediction-engine/reset from GET to POST, so the hazard is not hypothetical here.
    The union is read off the route table rather than restated from what I believe the verb
    to be — a projection of a gate must ask the gate.
    """
    matching = [ r for r in proxy_router.routes if isinstance( r, APIRoute ) and r.path == path ]
    assert matching, f"{path} is not mounted on the decision-proxy router at all"

    mounted = set().union( *( getattr( r, "methods", set() ) or set() for r in matching ) )
    assert "GET" in mounted, (
        f"{path} is mounted for {sorted( mounted )}, and the arms in this file send GET. "
        "Every one of them would answer 405 — a routing change wearing a permissions failure."
    )

    assert all( _carries_owner_guard( r ) for r in matching )


# ---------------------------------------------------------------------------
# 3. The reset endpoint — three properties, three ways to regress
# ---------------------------------------------------------------------------

RESET_PATH = "/api/prediction-engine/reset"


def test_reset_no_longer_answers_a_bare_get():
    """
    Ensures: the destructive verb is not reachable by a URL.

    A GET can be fired by a link, a prefetch or an <img src> without the caller intending
    it. That is why the verb moved, and it is a separate property from the credential —
    each can be reverted without touching the other.
    """
    assert _app( system_router ).get( RESET_PATH ).status_code == 405


def test_reset_refuses_a_post_without_a_credential():
    """Ensures: the uncredentialed 200 this row measured is now a 401."""
    assert _app( system_router ).post( RESET_PATH ).status_code == 401


def test_reset_does_not_drop_the_table_by_default():
    """
    Ensures: the destructive parameter defaults OFF.

    All six callers in the tree pass drop_table explicitly, so this default was load-bearing
    for nobody and dangerous for anyone who called the endpoint bare.
    """
    import inspect
    from cosa.rest.routers.system import reset_prediction_engine
    assert inspect.signature( reset_prediction_engine ).parameters[ "drop_table" ].default is False


# ---------------------------------------------------------------------------
# 4. The schema — a bare Depends does not put the refusal in /docs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "router, path, verb, expected",
    [
        ( proxy_router,  "/api/proxy/pending/{user_email}", "get",  ( "401", "403" ) ),
        ( proxy_router,  "/api/proxy/trust/{user_email}",   "get",  ( "401", "403" ) ),
        ( system_router, RESET_PATH,                        "post", ( "401", ) ),
    ],
)
def test_the_schema_declares_the_refusals( router, path, verb, expected ):
    """
    Ensures: `/docs` shows the refusals these routes can return.

    🔴 NOT REDUNDANT WITH THE GUARDS ABOVE. `require_api_key_or_jwt` and
    `require_path_identity_owner` take their headers as ORDINARY dependencies, so they
    contribute no security scheme and no 401/403 to the generated schema. A gated route
    whose schema says otherwise publishes itself as being exactly as open as it was before
    the fix — which is what `/api/init` did after it was gated, until row 977eaaf2 declared
    the pair explicitly. CLAUDE.md names `/docs` the authoritative API reference, so the
    schema is part of the fix rather than a description of it.
    """
    app = FastAPI()
    app.include_router( router )
    declared = app.openapi()[ "paths" ][ path ][ verb ][ "responses" ]
    for code in expected:
        assert code in declared


# ---------------------------------------------------------------------------
# 5. Row 44d8e89c — the other five decision-proxy routes
#
# Row 2d6f2221 gated the two path-keyed routes and left five open as a stated decision. This
# section closes them. The population below is a LITERAL for the same reason the one above is:
# a loop over nothing passes every assertion in it.
# ---------------------------------------------------------------------------

# Every route on the decision-proxy router, with the verb each is mounted for. Written out
# rather than derived, so that a route ADDED to the router without a credential fails
# `test_the_literal_route_table_is_the_router_s_own` below — a walk that derives its own
# denominator cannot notice a new row.
ALL_PROXY_ROUTES = {
    ( "GET",    "/api/proxy/batch-id" ),
    ( "POST",   "/api/proxy/acknowledge" ),
    ( "GET",    "/api/proxy/pending/{user_email}" ),
    ( "POST",   "/api/proxy/ratify/{decision_id}" ),
    ( "DELETE", "/api/proxy/decision/{decision_id}" ),
    ( "GET",    "/api/proxy/trust/{user_email}" ),
    ( "GET",    "/api/proxy/decisions/{domain}/{category}" ),
    ( "GET",    "/api/proxy/mode" ),
    ( "PUT",    "/api/proxy/mode" ),
}

# The two whose user sits in a QUERY parameter. `require_path_identity_owner` cannot serve these
# — it reads `request.path_params` and raises 500 for a route naming no user in its path.
QUERY_KEYED_PROXY_ROUTES = {
    ( "POST",   "/api/proxy/ratify/{decision_id}" ),
    ( "DELETE", "/api/proxy/decision/{decision_id}" ),
}

# Credential only: nothing in them names a user, so there is no owner to be.
CREDENTIAL_ONLY_PROXY_ROUTES = {
    ( "GET",    "/api/proxy/batch-id" ),
    ( "POST",   "/api/proxy/acknowledge" ),
    ( "GET",    "/api/proxy/decisions/{domain}/{category}" ),
}


def _concrete( path ):
    """Ensures: a path template with every placeholder filled, so the request routes."""
    return (
        path.replace( "{user_email}", VICTIM_EMAIL )
            .replace( "{decision_id}", "12345678-1234-5678-1234-567812345678" )
            .replace( "{domain}", "swe" )
            .replace( "{category}", "testing" )
    )


def test_the_literal_route_table_is_the_router_s_own():
    """
    Ensures: ALL_PROXY_ROUTES is exactly what the router mounts, verb included.

    This is the denominator for the walk below. Without it, a sixth ungated route added
    tomorrow would simply be absent from every assertion in this file and the file would stay
    green — "I looked and found none" printing identically to "there can be none".
    """
    mounted = {
        ( verb, r.path )
        for r in proxy_router.routes if isinstance( r, APIRoute )
        for verb in ( getattr( r, "methods", set() ) or set() )
        if verb != "HEAD"
    }
    assert mounted == ALL_PROXY_ROUTES


@pytest.mark.parametrize( "verb, path", sorted( ALL_PROXY_ROUTES ) )
def test_no_decision_proxy_route_answers_an_uncredentialed_caller( verb, path ):
    """
    Ensures: every route on the router refuses a caller with no credential — 0 of 9 open.

    MEASURED OVER THE REAL ROUTER, at the path, with the real credential dependency in place.
    Before this row five of these answered 200 or reached the database; the two that reached the
    database answered 422 to a BARE call, which is why a decorator read reported them refused.
    A 422 is checked for explicitly here rather than being lumped under "not 200": it is the
    exact reading that hid this defect for a month.
    """
    response = _app( proxy_router ).request( verb, _concrete( path ) )
    assert response.status_code == 401, (
        f"{verb} {path} answered {response.status_code} to a caller with no credential. "
        "A 422 here is NOT a refusal — it is the missing-parameter complaint that row "
        "2d6f2221 mistook for one."
    )


@pytest.mark.parametrize( "verb, path", sorted( QUERY_KEYED_PROXY_ROUTES ) )
def test_a_query_keyed_route_refuses_a_stranger( verb, path ):
    """
    Ensures: a VALID credential naming someone else in the QUERY string is refused 403.

    The half a bare credential check leaves open. Before this row, `user_email` was simply the
    string the caller typed: anyone could ratify or delete another user's decision and have the
    audit column record that other user as the actor.
    """
    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ):
        response = _app( proxy_router, OWNER_UID ).request(
            verb, _concrete( path ), params={ "user_email": VICTIM_EMAIL, "approved": "true" }
        )
    assert response.status_code == 403


@pytest.mark.parametrize( "verb, path", sorted( QUERY_KEYED_PROXY_ROUTES ) )
def test_a_query_keyed_route_refuses_a_caller_whose_user_record_is_gone( verb, path ):
    """
    Ensures: a credential that resolves to no user record is refused 403, not served.

    A deactivated or deleted account can still hold a live token for its remaining lifetime.
    The guard cannot name such a caller, so it cannot record one either — and this is its own
    arm because `user is None` and "the key names someone else" are two branches of one
    condition, and a test of either alone leaves the other unwatched.
    """
    with patch( "cosa.rest.user_service.get_user_by_id", return_value=None ):
        response = _app( proxy_router, OWNER_UID ).request(
            verb, _concrete( path ), params={ "user_email": OWNER_EMAIL, "approved": "true" }
        )
    assert response.status_code == 403


@pytest.mark.parametrize( "verb, path", sorted( CREDENTIAL_ONLY_PROXY_ROUTES ) )
def test_a_credential_only_route_admits_any_valid_caller( verb, path ):
    """
    Ensures: the three routes naming no user are gated on the CREDENTIAL only — a valid caller
    still gets through, and gets a 200 rather than merely "not 401".

    These carry no owner check on purpose. `batch-id` and `acknowledge` read and bump one
    process-global counter, and `decisions/{domain}/{category}` is keyed on a domain, not a
    person — there is no owner in any of them to be. Asserting 200 rather than "not 401 and not
    403" is deliberate: a 500 from an absent database satisfies the weaker form just as well.
    """
    session = MagicMock()
    db_ctx  = MagicMock()
    db_ctx.__enter__.return_value = session
    db_ctx.__exit__.return_value  = False

    with patch( "cosa.rest.routers.decision_proxy.get_db", return_value=db_ctx ), \
         patch( "cosa.rest.routers.decision_proxy.ProxyDecisionRepository" ) as repo:
        repo.return_value.get_by_domain_category.return_value = []
        response = _app( proxy_router, OWNER_UID ).request( verb, _concrete( path ) )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 6. The audit identity comes from the credential, not from the query string
# ---------------------------------------------------------------------------

def _owner_client_and_repos():
    """
    Ensures: returns ( client, decision_repo, trust_repo, exit_stack ) speaking as OWNER_UID with
    the data seam mocked, so a 200 means the handler ran rather than a database being absent.
    """
    import contextlib

    session = MagicMock()
    db_ctx  = MagicMock()
    db_ctx.__enter__.return_value = session
    db_ctx.__exit__.return_value  = False

    decision_repo = MagicMock()
    trust_repo    = MagicMock()

    stack = contextlib.ExitStack()
    stack.enter_context( patch( "cosa.rest.user_service.get_user_by_id",
                                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ) )
    stack.enter_context( patch( "cosa.rest.routers.decision_proxy.get_db", return_value=db_ctx ) )
    stack.enter_context( patch( "cosa.rest.routers.decision_proxy.ProxyDecisionRepository",
                                return_value=decision_repo ) )
    stack.enter_context( patch( "cosa.rest.routers.decision_proxy.TrustStateRepository",
                                return_value=trust_repo ) )
    return _app( proxy_router, OWNER_UID ), decision_repo, trust_repo, stack


# The caller's own identity, written three ways that all pass the ownership check. The point of
# the parametrization is that only one string may reach the database from any of them.
SPELLINGS_OF_THE_SAME_CALLER = [ OWNER_EMAIL, OWNER_EMAIL.upper(), OWNER_UID ]


@pytest.mark.parametrize( "typed", SPELLINGS_OF_THE_SAME_CALLER )
def test_ratify_records_the_credential_s_email_not_the_typed_string( typed ):
    """
    Ensures: `ratified_by`, the trust-state key, and the response all carry the account email
    resolved from the credential — never the string in the query.

    🔴 THE OWNERSHIP CHECK DOES NOT MAKE THE TYPED STRING SAFE TO STORE, which is why this is a
    separate test from the 403 arms. `_key_is_owned` accepts the caller's bare user id and
    compares email without regard to case, so all three spellings above belong to one person and
    all three pass the gate. Taking the audit identity from the query would let one person write
    three different values into `ratified_by` and into the trust-state key — and a trust counter
    split across two spellings of the same user is a silent wrong answer, not a cosmetic one.
    """
    client, decision_repo, trust_repo, stack = _owner_client_and_repos()
    decision_repo.get_by_id.return_value = MagicMock( ratification_state="pending",
                                                      domain="swe", category="testing" )
    decision_repo.ratify.return_value = MagicMock( ratification_state="approved",
                                                   ratified_at=None, domain="swe",
                                                   category="testing" )
    with stack:
        response = client.post(
            "/api/proxy/ratify/12345678-1234-5678-1234-567812345678",
            params={ "approved": "true", "user_email": typed }
        )

    assert response.status_code == 200
    assert decision_repo.ratify.call_args.kwargs[ "ratified_by" ] == OWNER_EMAIL
    assert trust_repo.update_after_ratification.call_args.kwargs[ "user_email" ] == OWNER_EMAIL
    assert response.json()[ "ratified_by" ] == OWNER_EMAIL


@pytest.mark.parametrize( "typed", SPELLINGS_OF_THE_SAME_CALLER )
def test_delete_records_the_credential_s_email_not_the_typed_string( typed ):
    """Ensures: `deleted_by` carries the credential's email for every spelling that passes the gate."""
    client, decision_repo, _trust_repo, stack = _owner_client_and_repos()
    decision_repo.delete_pending.return_value = True
    with stack:
        response = client.delete(
            "/api/proxy/decision/12345678-1234-5678-1234-567812345678",
            params={ "user_email": typed }
        )

    assert response.status_code == 200
    assert response.json()[ "deleted_by" ] == OWNER_EMAIL


@pytest.mark.parametrize( "verb, path", sorted( QUERY_KEYED_PROXY_ROUTES ) )
def test_omitting_the_user_still_reaches_the_handler_s_own_422( verb, path ):
    """
    Ensures: the query guard does NOT convert a malformed request into a 403 or a 500.

    Its path-keyed sibling raises 500 when a route names no user, because that is a WIRING error
    — the route was decorated with a guard it cannot satisfy. A missing QUERY parameter is a
    different thing: the route is wired correctly and the CALLER is malformed. So this guard has
    no 500 arm, and the handler's own required-parameter validation is left to answer. Pinned
    because the tempting symmetry — copying the 500 across — would turn every caller who forgot
    a parameter into a server error, and a 403 would tell them they lack permission they have.
    """
    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ):
        response = _app( proxy_router, OWNER_UID ).request( verb, _concrete( path ) )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "path, verb, expected",
    [
        ( "/api/proxy/batch-id",                      "get",    ( "401", ) ),
        ( "/api/proxy/acknowledge",                   "post",   ( "401", ) ),
        ( "/api/proxy/decisions/{domain}/{category}", "get",    ( "401", ) ),
        ( "/api/proxy/ratify/{decision_id}",          "post",   ( "401", "403" ) ),
        ( "/api/proxy/decision/{decision_id}",        "delete", ( "401", "403" ) ),
    ],
)
def test_the_five_newly_gated_routes_declare_their_refusals( path, verb, expected ):
    """
    Ensures: `/docs` shows the refusals, which a bare `Depends` does not cause on its own.

    Same reason as the section above: these guards take their headers as ordinary dependencies,
    contribute no security scheme, and add no 401 to the generated schema. A gated route whose
    schema still reads open publishes itself as being exactly as open as it was — and
    `rest-api-reference.md` listed these as **Public**, which is the same defect in prose.
    """
    app = FastAPI()
    app.include_router( proxy_router )
    declared = app.openapi()[ "paths" ][ path ][ verb ][ "responses" ]
    for code in expected:
        assert code in declared


# ---------------------------------------------------------------------------
# 7. The guard itself: the query tuple, and that it reads the query rather than the path
# ---------------------------------------------------------------------------

def test_the_query_guard_reads_the_query_and_not_the_path():
    """
    Ensures: `require_query_identity_owner` keys off `request.query_params`.

    Proved by a discriminating probe rather than by reading the source: one route names the user
    in its PATH only, and the guard must NOT accept a stranger's path value as the caller's
    identity. If the two guards were accidentally wired to the same source, the arms above would
    still pass — the proxy routes carry the user in the query — and this is the only thing that
    would notice.
    """
    probe = APIRouter()

    @probe.get( "/by-path/{user_email}", dependencies=[ Depends( require_query_identity_owner ) ] )
    async def by_path( user_email: str ): return { "seen": user_email }

    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ):
        client = _app( probe, OWNER_UID )
        # A stranger in the PATH is invisible to this guard, so the route is served: the guard
        # found no identity in the QUERY and had nothing to refuse.
        assert client.get( f"/by-path/{VICTIM_EMAIL}" ).status_code == 200
        # The same stranger in the QUERY is refused.
        assert client.get( f"/by-path/{OWNER_EMAIL}",
                           params={ "user_email": VICTIM_EMAIL } ).status_code == 403


def test_the_query_guard_returns_the_account_email():
    """
    Ensures: the value the handler receives is the account email, pinned to a LITERAL.

    Asserted through a probe route that echoes what it was handed. The proxy arms above check the
    value that reaches the repository; this checks the guard's own return, so a regression in the
    guard and a regression in one handler cannot be confused for each other.
    """
    probe = APIRouter()

    @probe.get( "/echo" )
    async def echo( who: Annotated[ str, Depends( require_query_identity_owner ) ] ):
        return { "who": who }

    with patch( "cosa.rest.user_service.get_user_by_id",
                return_value={ "id": OWNER_UID, "email": OWNER_EMAIL } ):
        response = _app( probe, OWNER_UID ).get( "/echo", params={ "user_email": OWNER_UID } )

    assert response.status_code == 200
    assert response.json() == { "who": OWNER_EMAIL }


def test_the_query_identity_tuple_holds_every_spelling_the_path_tuple_does():
    """
    Ensures: the two tuples name the same parameter spellings.

    They are separate objects on purpose — the path tuple is a router-walk denominator and the
    query tuple is not — but a spelling added to one and forgotten in the other is a silent hole:
    a route carrying `?user_id=` under the query guard would be checked against nothing and
    served. Equality is asserted rather than containment, so a query-only spelling is caught too.
    """
    assert set( QUERY_IDENTITY_PARAMS ) == set( PATH_IDENTITY_PARAMS )
