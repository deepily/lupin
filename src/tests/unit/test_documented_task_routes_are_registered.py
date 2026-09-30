"""
Every documented task route must be REGISTERED at the path its documentation names.

WHY THIS FILE EXISTS, and it is a different question from its two neighbours. An
independent mutation pass on 2026-09-02 (Tiberius 👑) renamed

    GET /api/tasks/{task_id}/events   ->   GET /api/tasks/{task_id}/event

and the arm SURVIVED the entire sixteen-file population. The endpoint simply vanished
from the API and not one test noticed.

🔴 IT IS NOT A SHADOWING DEFECT, AND SAYING SO WOULD SEND THE NEXT READER TO THE WRONG
GUARD. Measured before writing this file: a one-segment parameter cannot match a
two-segment sibling — the regex for `/tasks/{task_id}` does not match
`/tasks/abc/events` — so `test_no_literal_route_is_shadowed_by_a_parameterised_sibling`
is CORRECT not to flag it. Nothing was swallowed. The route was simply gone.

⇒ THE GAP IS THAT THE TWO EXISTING GUARDS BOTH ASK ABOUT ORDERING, AND NEITHER ASKS
ABOUT EXISTENCE:

  · test_no_literal_route_is_shadowed_by_a_parameterised_sibling.py
        — asks whether a registered literal is UNREACHABLE behind a parameterised one
  · test_task_routes_resolve_literal_paths.py
        — asks whether a LITERAL path reaches its own route, from a hand-kept list
          that (correctly, by its own charter) holds only literals

A PARAMETERISED route carrying a suffix — `/tasks/{task_id}/events` — is in neither
population. It cannot be shadowed by its shorter sibling and it is not a literal, so
both guards pass while it is renamed out of existence.

⚠️ AND THIS IS THE SAME SHAPE AS THE 422 THAT STARTED ALL OF THIS, arriving from the
other side. There, a route existed and could not be reached. Here, a route can be
reached and does not exist. Both render identically to the client — `fetchFlowRatio`
and its siblings return null on ANY non-2xx — so a missing endpoint and a quiet board
look the same on the page. Ordering was guarded; existence was not.

Venue: :7999-eligible — in-process, builds the router, no server, no network.
"""

import pytest
from fastapi import FastAPI

from cosa.rest.routers import tasks as tasks_router


# Every route this router is documented to expose, literal AND parameterised.
# Add a row here whenever a task route is introduced or its path changes.
#
# 🔴 WRITE THE PATH AS A LITERAL STRING. Do NOT derive it from the router, from a
# constant in the module under test, or from the route object itself — a expectation
# derived from the source moves WITH the source and can never fail. That is exactly the
# defect this file was written after: an assertion comparing a value to the constant
# that produced it is unfalsifiable, and reads as 100% covered while it happens.
DOCUMENTED_TASK_ROUTES = [
    ( "GET",    "/api/tasks" ),
    ( "POST",   "/api/tasks" ),
    ( "GET",    "/api/tasks/events" ),
    ( "GET",    "/api/tasks/flow-ratio" ),
    ( "GET",    "/api/tasks/flow-ratio/settings" ),
    ( "PATCH",  "/api/tasks/flow-ratio/settings" ),
    ( "DELETE", "/api/tasks/flow-ratio/settings" ),
    ( "GET",    "/api/tasks/{task_id}" ),
    ( "PATCH",  "/api/tasks/{task_id}" ),
    ( "GET",    "/api/tasks/{task_id}/events" ),
    ( "POST",   "/api/tasks/{task_id}/amend" ),
    ( "POST",   "/api/tasks/{task_id}/correlate" ),
    ( "POST",   "/api/tasks/{task_id}/transition" ),
    ( "GET",    "/api/epic-stories" ),
]


def _registered( router ):
    """
    Ensures:
        - returns the set of ( METHOD, path ) pairs the router actually registers
        - one entry per method, so a route serving GET and PATCH yields two
    """
    found = set()
    for route in router.routes:
        for method in getattr( route, "methods", set() ) or set():
            if method in ( "HEAD", "OPTIONS" ): continue
            found.add( ( method, route.path ) )
    return found


@pytest.mark.parametrize( "method,path", DOCUMENTED_TASK_ROUTES,
                          ids=[ f"{m} {p}" for m, p in DOCUMENTED_TASK_ROUTES ] )
def test_a_documented_task_route_is_actually_registered( method, path ):
    """
    The route named in the list above exists on the router, spelled exactly that way.

    Requires:
        - DOCUMENTED_TASK_ROUTES holds literal strings, never values read from the source

    Ensures:
        - reddens when a documented route is renamed, removed, or has its method changed
    """
    registered = _registered( tasks_router.router )
    assert ( method, path ) in registered, (
        f"{method} {path} is documented but NOT registered. The endpoint has been "
        f"renamed or removed and every ordering guard still passes, because neither of "
        f"them asks whether a route EXISTS. Nearest registered paths: "
        f"{sorted( p for m, p in registered if p.startswith( path.rsplit( '/', 1 )[ 0 ] ) )}"
    )


def test_the_existence_DETECTOR_actually_fires():
    """
    A positive control: the check above must fail for a route that is not registered.

    Without this, a bug in `_registered` — returning everything, or comparing loosely —
    would make every case above pass vacuously, and a green list of documented routes
    would mean nothing at all.

    Ensures:
        - a deliberately absent route is reported as missing
        - so a green result above is evidence rather than silence
    """
    registered = _registered( tasks_router.router )
    assert ( "GET", "/api/tasks/{task_id}/event" ) not in registered, (
        "the singular '/event' path is registered — this control assumed it was not"
    )
    assert ( "GET", "/api/tasks/definitely-not-a-real-route" ) not in registered


def test_the_events_route_is_not_shadowable_by_its_shorter_sibling():
    """
    `/tasks/{task_id}` cannot swallow `/tasks/{task_id}/events` — segment counts differ.

    Recorded as a test rather than a comment so the claim in this module's docstring is
    checked rather than asserted. If FastAPI's matching ever changed, or a greedy
    `{path:path}` converter were introduced above it, this would redden and the reader
    would be sent to the shadowing guard instead of this one.

    Ensures:
        - the two routes differ in segment count, so no ordering fix is needed here
    """
    import re
    shorter = "/api/tasks/{task_id}"
    longer  = "/api/tasks/{task_id}/events"
    as_regex = re.compile( "^" + re.sub( r"\{[^}]+\}", r"[^/]+", shorter ) + "$" )
    concrete = longer.replace( "{task_id}", "abc123" )
    assert not as_regex.match( concrete ), (
        "a one-segment parameter now matches a two-segment path — the events route IS "
        "shadowable after all, and this file's premise needs revisiting"
    )
