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

from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.middleware.path_identity import PATH_IDENTITY_PARAMS, require_path_identity_owner
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
