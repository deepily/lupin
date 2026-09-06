"""
Literal task routes must not be swallowed by `/tasks/{task_id}`.

WHY THIS FILE EXISTS. `GET /api/tasks/flow-ratio` shipped registered BELOW
`GET /api/tasks/{task_id}`. FastAPI matches in REGISTRATION ORDER, so the literal
path was never reached: every request answered

    422  {"detail":"task reference 'flow-ratio' is neither a UUID nor a hex id
                    prefix of at least 4 characters"}

for as long as it was deployed.

🔴 AND NOTHING SAW IT, WHICH IS THE REAL LESSON. Three instruments covered this
feature and each was blind to the seam in a different way:

  · test_flow_ratio_endpoint.py  — calls the handler, so ordering never applies
  · task_list_panel.test.ts      — renders a hand-built payload
  · e2e_ui/test_task_list_card.py — `route.fulfill`s `/api/tasks/flow-ratio`
                                    ITSELF, faking the exact call that was broken

The client compounds it: `fetchFlowRatio` returns null on ANY non-2xx and the
header omits the clause, so a broken endpoint and a quiet board render
IDENTICALLY. Rick found it by looking at the page and asking twice.

⇒ This test asks the ROUTE TABLE, which is the only thing that knows the answer.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import tasks as tasks_router


# 🔴 DERIVED FROM THE ROUTER, NOT TYPED OUT — AND THIS REPLACED A HAND LIST THAT HAD
# ALREADY GONE STALE. Found by Tiffany 💍, 2026-09-06: the list held two entries while the
# router carried more, so literal routes were being introduced and silently left unguarded.
# The comment above it said "add a row here whenever a literal task route is introduced",
# and that instruction is exactly what failed — a hand-maintained enumeration is correct
# for everything its author thought of and silently wrong for everything else.
#
# ⇒ SO THE FIX IS NOT A LONGER LIST. The predicate this list was approximating is "every
# GET path under /api/tasks whose segments are all literal". Written as the predicate it
# cannot go stale: a route added tomorrow is in the corpus the moment it is registered,
# and nobody has to remember anything.
#
# ⚠️ A PARAMETERISED SEGMENT IS EXCLUDED because it is not what a sibling can swallow —
# `/api/tasks/promotions/{ticket_id}` cannot be shadowed by the one-segment
# `/api/tasks/{task_id}`, while the literal `/api/tasks/promotions` absolutely can.
def _literal_task_paths():
    """
    Every literal GET path under /api/tasks, read off the router itself.

    Ensures:
        - returns paths carrying no `{param}` segment beyond the /api/tasks prefix
        - excludes `/api/tasks` itself, which has no sibling to be swallowed by
        - the result is sorted, so a failure names the same path every run
    """
    found = set()
    for route in tasks_router.router.routes:
        path    = getattr( route, "path", "" )
        methods = getattr( route, "methods", set() ) or set()
        if "GET" not in methods:            continue
        if not path.startswith( "/api/tasks/" ): continue
        if "{" in path:                     continue
        found.add( path )
    return sorted( found )


LITERAL_TASK_PATHS = _literal_task_paths()

# The message `/tasks/{task_id}` produces when handed a non-id. Its presence in a
# response to a LITERAL path is the signature of a swallow.
_SWALLOW_SIGNATURE = ( "task reference", "hex id prefix" )


@pytest.fixture( scope="module" )
def client():
    """
    🔴 AUTH IS OVERRIDDEN, AND THAT IS THE WHOLE POINT OF THIS FIXTURE.

    My first cut of this file did NOT override it, and it passed against the
    BROKEN route ordering — because an unauthenticated request answers 401 from
    the auth dependency BEFORE path resolution can matter. Both orderings
    returned the same 401, so the test was reading the auth layer and reporting
    on the route table. It was green, it was well-named, and it proved nothing.
    I found that only by running the broken arm underneath it.

    ⇒ Getting past auth is what lets the two orderings produce DIFFERENT
    observations, which is the only thing that makes any assertion below worth
    reading.

    The router already carries prefix="/api" — mounting it under another prefix
    yields /api/api/... and 404s everything, which reads exactly like a swallow
    and is not one.
    """
    app = FastAPI()
    app.include_router( tasks_router.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app, raise_server_exceptions=False )


def _swallowed( response ):
    return any( sig in response.text for sig in _SWALLOW_SIGNATURE )


@pytest.mark.parametrize( "path", LITERAL_TASK_PATHS )
def test_a_literal_task_path_reaches_its_own_route( client, path ):
    """
    Authenticated (overridden), so the request gets far enough for ROUTING to be
    the thing under test. A response carrying the id-parser's words proves the
    literal path was handed to `/tasks/{task_id}` instead of its own handler.

    RED ON REVERT: move the `/tasks/flow-ratio` registration back below
    `/tasks/{task_id}` and this returns 422 with "task reference". Verified by
    running exactly that, not by assuming it.
    """
    r = client.get( path )
    assert not _swallowed( r ), (
        f"{path} was swallowed by /tasks/{{task_id}} — FastAPI matches in "
        f"REGISTRATION ORDER, so move its @router.get ABOVE the parameterised "
        f"route in tasks.py. Response: {r.status_code} {r.text[ :200 ]}"
    )
    assert r.status_code != 404, (
        f"{path} answered 404 — usually this test mounting the router under a "
        f"second prefix, not a missing route."
    )


def test_the_swallow_DETECTOR_actually_fires( client ):
    """
    THE NEGATIVE CONTROL, and without it the assertions above are worthless — a
    detector that can never fire reports every route as healthy.

    Drive a genuinely-bad id at the parameterised route WITH auth, so the id parser
    is reached, and require the signature this file keys on to appear.
    """
    r = client.get( "/api/tasks/not-an-id" )
    assert _swallowed( r ), (
        f"the swallow detector never fires, so the tests above prove nothing. "
        f"Got {r.status_code} {r.text[ :200 ]}"
    )


def test_the_derived_corpus_is_not_EMPTY_and_reaches_the_routes_we_know_exist():
    """
    🔴 THE POSITIVE CONTROL, AND THE PARAMETRIZED ARMS ABOVE ARE WORTHLESS WITHOUT IT.
    A derivation that returned NOTHING would generate zero test cases, and a loop over
    nothing is green — the same shape as a search whose empty result is read as a
    negative rather than as a search that never ran.

    ⚠️ IT NAMES THE PATHS THE HAND LIST USED TO CARRY, PLUS THE ONE THAT EXPOSED IT.
    The hand list held `/api/tasks/flow-ratio` and `/api/tasks/events` and had gone stale
    by at least two — Tiffany 💍's finding, 2026-09-06. Asserting a FLOOR rather than an
    exact set is deliberate: an exact set is a hand-maintained enumeration wearing an
    assertion's clothes, and would fail on the next legitimate route.
    """
    derived = set( LITERAL_TASK_PATHS )

    assert len( derived ) >= 4, (
        f"the derivation found only {sorted( derived )}. It is reading the router wrong, "
        f"and every parametrized arm above is silently testing nothing."
    )
    for known in ( "/api/tasks/flow-ratio", "/api/tasks/events", "/api/tasks/promotions" ):
        assert known in derived, (
            f"{known} is registered on the router and the derivation missed it — so the "
            f"corpus is narrower than the thing it claims to cover"
        )
