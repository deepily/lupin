"""
No LITERAL route may be registered below a parameterised sibling that swallows it.

WHY THIS FILE EXISTS. `GET /api/tasks/flow-ratio` shipped registered BELOW
`GET /api/tasks/{task_id}`. FastAPI matches in REGISTRATION ORDER, so the literal path
was never reached and answered 422 — "task reference 'flow-ratio' is neither a UUID nor
a hex id prefix" — for its entire life. It was invisible because the client hides a
non-2xx by design, so a broken endpoint and a quiet board render identically.

THIS FILE IS THE GENERALISATION OF `test_task_routes_resolve_literal_paths.py`, WHICH
IT DOES NOT REPLACE. That file asks a sharper question about two known paths — it drives
real requests through a TestClient and reads the id-parser's words out of the response
body, which is direct evidence that a swallow occurred. But its population is a
HAND-MAINTAINED list carrying the instruction "Add a row here whenever a literal task
route is introduced", and it covers `/api/tasks` only. A control that depends on
somebody remembering is not installed — this repo's own doctrine — and the next
flow-ratio will not be under `/api/tasks`.

So this file trades depth for COVERAGE: it derives its population from the assembled
app, cannot miss a route nobody remembered to list, and needs no request at all. Keep
both. The pair is the check.

WHAT IT WALKS, AND WHY THAT AND NOT THE SOURCE. `main.app.routes` in REGISTRATION
ORDER. The ordering IS the defect, so reading decorators out of the source text would
measure the wrong thing — and it would also miss shadowing BETWEEN routers, which is
decided by main.py's `include_router` order rather than by any one router's file.

Measured at sha 8eca08f7: 200 routes, 140 literal x 60 parameterised, ZERO shadowed.

⚠️ SCOPE, stated so a green here is not over-read:
  - HTTP methods must INTERSECT for a shadow to be real, so `POST /a/{id}` above
    `GET /a/literal` is correctly not flagged.
  - Routes with no `methods` (WebSocket routes, Mounts) are never flagged. Path
    resolution for those does not work this way.
  - A parameterised segment is treated as matching exactly one path segment, which is
    Starlette's default `str` convertor. A `:path` convertor spans separators and is NOT
    modelled here — if one is ever added above a literal sibling, this test will not see
    it.

Venue: :7999-eligible — in-process, no server, no network, no persistent-state mutation.
"""

import re

from lupin_app import main


def _one_segment_pattern( path ):
    """
    Compile a parameterised route path into a regex matching its literal siblings.

    Requires:
        - path is a route path, e.g. "/api/tasks/{task_id}"

    Ensures:
        - returns None when `path` has no `{...}` segment (a literal shadows nothing)
        - otherwise returns a compiled regex where each `{...}` segment matches exactly
          one path segment ([^/]+), mirroring Starlette's default `str` convertor
    """
    parts = path.split( "/" )
    if not any( s.startswith( "{" ) for s in parts ):
        return None
    return re.compile(
        "^" + "/".join( r"[^/]+" if s.startswith( "{" ) else re.escape( s ) for s in parts ) + "$"
    )


def _route_table():
    """Every route with a path, in REGISTRATION ORDER, as (path, sorted methods)."""
    table = []
    for route in main.app.routes:
        path = getattr( route, "path", None )
        if not path:
            continue
        table.append( ( path, sorted( getattr( route, "methods", None ) or [] ) ) )
    return table


def _shadowed( table ):
    """Every (literal, parameterised) pair where the literal is registered LATER."""
    found = []
    for i, ( literal, literal_methods ) in enumerate( table ):
        if "{" in literal:
            continue
        for j, ( param, param_methods ) in enumerate( table ):
            if j >= i:
                continue                      # only an EARLIER sibling can shadow
            pattern = _one_segment_pattern( param )
            if pattern and pattern.match( literal ) and ( set( literal_methods ) & set( param_methods ) ):
                found.append( ( literal, sorted( set( literal_methods ) & set( param_methods ) ), param, j, i ) )
    return found


def test_the_detector_can_see_a_shadow_when_one_exists():
    """
    THE POSITIVE CONTROL, and it runs FIRST for a reason.

    The whole-app assertion below is an ABSENCE claim, and an absence looks identical
    whether the instrument works or the population is empty. So prove the instrument
    returns a positive over the same shape before trusting a negative from it.

    The synthetic table is the real defect as it actually shipped: the parameterised
    route registered first, the literal second.

    Ensures:
        - _shadowed() reports the pair, naming both paths
        - reversing the order clears it, so the detector is reading ORDER and not merely
          the fact that two paths overlap
    """
    broken = [ ( "/api/tasks/{task_id}", [ "GET" ] ), ( "/api/tasks/flow-ratio", [ "GET" ] ) ]
    hits   = _shadowed( broken )
    assert len( hits ) == 1, f"detector blind to the known defect: {hits}"
    assert hits[ 0 ][ 0 ] == "/api/tasks/flow-ratio"
    assert hits[ 0 ][ 2 ] == "/api/tasks/{task_id}"

    fixed = list( reversed( broken ) )
    assert _shadowed( fixed ) == [], "detector flags correct ordering — it is not reading order"


def test_methods_must_intersect_for_a_shadow_to_count():
    """
    A parameterised route on a DIFFERENT method cannot swallow the literal.

    Without this the detector would flag every literal sitting under any parameterised
    path regardless of verb, and a wall of false positives is how a guard gets deleted.
    """
    table = [ ( "/api/tasks/{task_id}", [ "POST" ] ), ( "/api/tasks/flow-ratio", [ "GET" ] ) ]
    assert _shadowed( table ) == []


def test_no_literal_route_in_the_assembled_app_is_shadowed():
    """
    The real check, over the whole app.

    Requires:
        - lupin_app.main imports (the unit conftest supplies JWT_SECRET_KEY)

    Ensures:
        - the route table contains both literal and parameterised routes — otherwise
          "zero shadowed" would be vacuously true
        - no literal path is registered after a parameterised sibling that matches it
          on a shared HTTP method

    RED ON REVERT: move the `/tasks/flow-ratio` registration in
    `src/cosa/rest/routers/tasks.py` back below `/tasks/{task_id}` and this names the
    pair. Verified by running exactly that, not by assuming it.
    """
    table    = _route_table()
    literals = [ p for p, m in table if "{" not in p ]
    params   = [ p for p, m in table if "{" in p ]

    # The population guard. A detector run over an empty or one-sided table would report
    # "zero shadowed" and mean nothing by it.
    assert len( literals ) > 50 and len( params ) > 10, (
        f"route table looks wrong — {len( literals )} literal / {len( params )} "
        f"parameterised. A near-empty table makes the assertion below vacuous."
    )

    hits = _shadowed( table )
    assert hits == [], "\n".join(
        [ "a literal route is registered BELOW a parameterised sibling that swallows it;",
          "FastAPI matches in REGISTRATION ORDER, so it will answer the sibling's error:" ]
        + [ f"  {','.join( m )} {lit}  <- shadowed by {par}  (registered #{j} before #{i})"
            for lit, m, par, j, i in hits ]
    )
