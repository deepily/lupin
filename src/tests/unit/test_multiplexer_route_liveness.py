"""
Multiplexer client-URL → live-ASGI route LIVENESS test (the runtime fail-loud
sibling of the static contract test).

This is part (b) of closing the multiplexer test-gap CLASS surfaced when the SPA
called `/api/queue/job-history` (the wrong prefix; real route is
`/api/job-history`) and the 404 slipped EVERY test tier:

  GAP 1  JobsPaneRenderer.hydrateHistory(api).catch() SWALLOWED the failure, so
         the page still booted and the "page-loads" e2e passed.
  GAP 2  JobStore unit tests inject a STUB ApiClient — they validate response
         handling, never that the URL resolves to a real backend route.
  GAP 3  the :8000 e2e tolerated the swallowed error (no console-error / no-4xx
         assertion) — the swallowed 404 silently passed.

Two complementary mechanisms close the class:

  (a) test_multiplexer_api_contract.py — a STATIC check: every client `/api/`
      literal maps (by normalized path-pattern) to a route present in
      `app.routes`. Catches drift at enumeration time.

  (b) THIS test — a RUNTIME check: each client URL is GET-probed against the
      live ASGI app and must NOT return 404. `app.routes` enumeration is not
      the same as actual ASGI dispatch — a route can be listed yet shadowed by
      an earlier match, mounted on a sub-app that does not serve it, or
      otherwise unreachable. The static heuristic (regex extraction + pattern
      normalization) can also match the wrong pattern; a real request removes
      that heuristic from the loop by asking the router itself.

WHY A BOGUS-METHOD ROUTING PROBE (not a GET) — SAFE + :7999-ELIGIBLE:
    The sweep must answer one question: "does the live router have a route for
    this exact path?" A GET probe answers it noisily — a registered route can
    legitimately return 404 from its OWN handler (e.g. `/api/notifications/
    senders-visible/{email}` returns `{"detail":"User not found"}` for an
    unknown user), which is an APPLICATION 404, not the route-missing bug. To
    ask the ROUTER and nothing else, each path is probed with a deliberately
    unsupported HTTP method (`LIVENESSPROBE`):
      - path IS registered → Starlette matches the path, rejects the method,
        returns 405 — and the handler NEVER runs (no DB, no mutation, no
        semantic 404 / auth / validation noise to confuse the signal).
      - path is NOT registered → Starlette returns 404.
    So 404 means exactly "no route matches this path" — the swallowed-404 bug
    class, and nothing else. The test is in-process (FastAPI TestClient, no
    lifespan → no DB), executes zero handlers (a never-allowed method), and
    finishes in seconds: it meets all three :7999 criteria.

WHY THIS REALIZES THE ":8000 fail-loud e2e" UNDER A :7999-ONLY MANDATE:
    The original remediation called for a browser e2e on :8000 asserting "zero
    4xx during /app/multiplexer boot." A real browser + real backend needs the
    :8000 monopolize venue, which this work-order excludes. Probing the live
    ASGI app in-process is the faithful, CI-stable substitute: it surfaces a
    swallowed 404 at the routing layer — the exact failure the browser e2e
    would have caught — without a server monopoly. (Surfacing the failure in
    the rendered UI remains a feature/WS4 concern; see the manager hand-off.)

Requires:
    - LUPIN_ROOT set + `src/` on sys.path (handled by src/tests/conftest.py).
    - lupin_app.main:app importable (the full FastAPI app).
    - The multiplexer TS source present (reused via the contract module's
      extraction helpers — ONE source of truth for "what URLs the client emits").

Ensures:
    - EVERY multiplexer client `/api/` URL resolves to a route the LIVE app
      dispatches without 404.
    - The historical bug path (`/api/queue/job-history`) is proven to 404 at
      runtime (the in-suite analogue of a revert proof — the probe catches the
      drift, it does not merely pass).

Raises:
    - AssertionError naming each client URL whose probe 404'd (or had no
      matching route), with the concrete path probed, so a reviewer sees the
      exact offending literal.
"""

import os

import pytest
from fastapi.testclient import TestClient

# Reuse the contract module's extraction + normalization as the SINGLE source of
# truth for the client-URL set and the route-pattern matching. The runtime check
# differs only in HOW it verifies the match (a live request vs `app.routes`
# membership), never in WHAT it considers a client call.
from test_multiplexer_api_contract import (
    _multiplexer_src_dir,
    _extract_client_urls,
    _registered_routes,
    _normalize_client_url,
    _resolve_match,
)


# A path segment substituted for every `{p}` template param when building a
# concrete probe path. Any non-empty, route-syntax-neutral token works — the
# router matches a `{param}` segment by shape, not value.
_PROBE_SEGMENT = "probe"

# A deliberately-unsupported HTTP method. Sending it forces a PURE routing
# decision: 405 if the path is registered (handler never runs), 404 if not.
# No real route allows it, so the probe is non-mutating by construction.
_PROBE_METHOD = "LIVENESSPROBE"


# ── Core liveness primitive ────────────────────────────────────────────────────

def _liveness_failure( client, url, route_patterns ):
    """
    Return a human-readable failure reason if `url` is not live, else None.

    Requires:
        - client is a TestClient over the full app.
        - url is a multiplexer client `/api/` URL literal.
        - route_patterns is the set of normalized registered route patterns.

    Ensures:
        - returns None when the client URL resolves to a registered route AND a
          routing probe of that route's concrete path does NOT 404 (a 405 — the
          healthy result — proves the live router dispatches the path).
        - returns a non-empty reason string when EITHER no registered route
          matches the client URL OR the live router returns 404 for the probe.

    Raises:
        - (none).
    """
    normalized = _normalize_client_url( url )
    matched    = _resolve_match( normalized, route_patterns )

    if matched is None:
        return f"no registered route matches {url} (normalized: {normalized})"

    probe = matched.replace( "{p}", _PROBE_SEGMENT )
    resp  = client.request( _PROBE_METHOD, probe )
    if resp.status_code == 404:
        return (
            f"{url} resolves to route {matched} but the live router returned 404 "
            f"for {_PROBE_METHOD} {probe} (registered-but-unroutable)"
        )
    return None


def _collect_liveness_failures( client, client_calls, route_patterns ):
    """
    Map every client call through `_liveness_failure`, collecting one formatted
    line per dead URL.

    Requires:
        - client_calls is a list of { "url", "site", ... } dicts.

    Ensures:
        - returns a list of "  <site>  <reason>" strings, one per URL that is
          NOT live; an empty list when every URL is live.

    Raises:
        - (none).
    """
    failures = []
    for call in client_calls:
        reason = _liveness_failure( client, call[ "url" ], route_patterns )
        if reason is not None:
            failures.append( f"  {call['site']:42s} {reason}" )
    return failures


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def client():
    """
    A TestClient over the full FastAPI app, constructed WITHOUT entering the
    lifespan context (no DB/startup needed — routing dispatch is independent of
    lifespan). Module-scoped so the heavy app import is paid once.
    """
    from lupin_app.main import app
    return TestClient( app )


@pytest.fixture( scope="module" )
def route_patterns():
    """The set of normalized registered `/api` route patterns (live app)."""
    return set( _registered_routes().keys() )


# ── The runtime liveness sweep ──────────────────────────────────────────────

def test_every_multiplexer_client_url_is_live_against_the_running_app( client, route_patterns ):
    """
    Assert each multiplexer client `/api/` URL is dispatched (not 404) by the
    live ASGI app.

    This is the runtime regression gate for the 404 false-pass class: a client
    URL the real router cannot dispatch fails HERE, independent of whether the
    renderer swallows the error or an e2e tolerates it.

    Requires:
        - multiplexer TS source + importable app (see module docstring).

    Ensures:
        - fails (naming url + concrete probe path) if ANY client URL 404s.
        - fails loud if zero client URLs were discovered (hollow-green guard).
    """
    src_dir      = _multiplexer_src_dir()
    assert src_dir.is_dir(), f"multiplexer source dir not found: {src_dir}"
    client_calls = _extract_client_urls( src_dir )

    # Hollow-green guard: a silently-empty extraction would pass for the wrong
    # reason. The multiplexer is known to call many /api/ routes.
    assert len( client_calls ) >= 5, (
        f"extracted only {len(client_calls)} client /api/ URLs from {src_dir} — "
        "the extraction regex likely broke. Refusing to pass on a hollow result."
    )

    failures = _collect_liveness_failures( client, client_calls, route_patterns )

    assert not failures, (
        f"{len(failures)} client URL(s) not live against the running app "
        f"(the swallowed-404 class):\n\n" + "\n".join( failures )
    )


def test_collector_flags_dead_urls_and_passes_live_ones( client, route_patterns ):
    """
    Exercise `_collect_liveness_failures` over a MIXED batch so its
    failure-append path is covered by a real assertion (not only by the
    all-green sweep, where it never fires).

    Ensures:
        - a dead URL (the historical bug prefix) is collected, tagged with its
          call site.
        - a live URL in the same batch is NOT collected.
    """
    calls = [
        { "url": "/api/queue/job-history?limit=100", "site": "Bogus.ts:1", "method": None },
        { "url": "/api/job-history?limit=100",       "site": "JobStore.ts:164", "method": None },
    ]
    failures = _collect_liveness_failures( client, calls, route_patterns )
    assert len( failures ) == 1, f"expected exactly the dead URL flagged, got: {failures}"
    assert "Bogus.ts:1"   in failures[ 0 ]
    assert "JobStore.ts" not in failures[ 0 ]


def test_job_history_route_answers_get( client ):
    """
    Focused regression for the exact incident endpoint: GET `/api/job-history`
    (the route the multiplexer JobStore.hydrateHistory actually calls) is
    dispatched by the live app — NOT 404.

    A 401 (no credentials) is the expected, correct answer: it proves the route
    exists and enforces auth. The bug was a 404, which this asserts against.
    """
    resp = client.get( "/api/job-history" )
    assert resp.status_code != 404, (
        "GET /api/job-history returned 404 — the job-history route is missing "
        "from the live app (this is the exact 404 the original bug surfaced)."
    )
    assert resp.status_code != 405, (
        "GET /api/job-history returned 405 — the route exists but no longer "
        "accepts GET, which the multiplexer client requires."
    )


def test_runtime_probe_catches_the_historical_bug_path( client, route_patterns ):
    """
    Prove the liveness primitive CATCHES a regression rather than silently
    passing — the in-suite analogue of a manual revert proof.

    Feeds the exact historical bug literal (`/api/queue/job-history`, the wrong
    prefix) plus two synthetic drift shapes through the SAME `_liveness_failure`
    primitive the sweep uses, and asserts each is flagged for the right reason.

    Ensures:
        - the historical wrong-prefix URL is flagged (it matches NO route).
        - a URL whose pattern is "registered" but which the live app 404s is
          flagged by the runtime-probe branch (registered-but-unreachable).
        - a real, dispatched URL is NOT flagged (no false positive).
    """
    # 1. The historical bug: wrong prefix → no matching registered route.
    bug = _liveness_failure( client, "/api/queue/job-history?limit=100", route_patterns )
    assert bug is not None, (
        "expected /api/queue/job-history to be flagged (it is the exact 404 "
        "bug) — if it passes, the liveness primitive is too lax."
    )
    assert "no registered route" in bug

    # 2. Registered-but-unreachable: inject a pattern the matcher will accept but
    #    the live app does not actually serve, exercising the runtime-404 branch
    #    deterministically (without disturbing any real route).
    phantom_pattern = "/api/__route_liveness_phantom__"
    unreachable = _liveness_failure(
        client, phantom_pattern, route_patterns | { phantom_pattern }
    )
    assert unreachable is not None, (
        "expected a registered-but-unreachable pattern to be flagged by the "
        "runtime probe — the live router returns 404 for it."
    )
    assert "live router returned 404" in unreachable

    # 3. No false positive: the correct endpoint resolves AND is dispatched.
    good = _liveness_failure( client, "/api/job-history?limit=100", route_patterns )
    assert good is None, f"expected /api/job-history to be live, got: {good}"


if __name__ == "__main__":
    # Smoke entry point: run the liveness checks standalone (no pytest harness).
    # Requires LUPIN_ROOT set + src on PYTHONPATH.
    import sys

    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path: sys.path.insert( 0, src_path )
    tests_dir = os.path.join( src_path, "tests", "unit" )
    if tests_dir not in sys.path: sys.path.insert( 0, tests_dir )

    from lupin_app.main import app
    _client   = TestClient( app )
    _patterns = set( _registered_routes().keys() )

    test_every_multiplexer_client_url_is_live_against_the_running_app( _client, _patterns )
    test_job_history_route_answers_get( _client )
    test_runtime_probe_catches_the_historical_bug_path( _client, _patterns )
    print( "OK — multiplexer route liveness holds + regression-catch proven." )
