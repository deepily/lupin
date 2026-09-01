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


# Every LITERAL path under /api/tasks that a parameterised sibling could swallow.
# Add a row here whenever a literal task route is introduced.
LITERAL_TASK_PATHS = [
    "/api/tasks/flow-ratio",
    "/api/tasks/events",
]

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
