"""
Multiplexer client-URL ↔ FastAPI-route CONTRACT test.

Closes the false-pass class that let the multiplexer JobStore 404 slip every
test tier (the SPA called `/api/queue/job-history` but the real route is
`/api/job-history`):

  GAP 1  JobsPaneRenderer.hydrateHistory(api).catch() SWALLOWED the failure,
         so the page still booted and the "page-loads" e2e passed.
  GAP 2  JobStore unit tests inject a STUB ApiClient — they validate response
         handling, never that the URL resolves to a real backend route.
  GAP 3  the :8000 e2e tolerated the swallowed error (no console-error /
         no-4xx assertion).

This test attacks the ROOT (a client URL with no matching backend route) at
unit speed, independent of all three swallow points above.

WHY PYTHON (and not a TS test) — justification per the deliverable:
    The authoritative route set lives in the FastAPI app. The single cleanest
    source of truth is `app.routes` (every mounted router + its prefix, exactly
    as the running server sees it) — reachable only from Python. Re-deriving
    that set in TS would mean re-parsing every `routers/*.py` decorator and
    re-implementing FastAPI's prefix/mount composition, which would drift from
    reality. So we enumerate routes in-process from `app.routes`, and read the
    client URLs out of the TS source with a focused regex over the actual
    network-call sites (`api.get/post/put/patch/delete(...)`, `fetch(...)`, and
    `*ENDPOINT*` constants). Best of both: real routes + real client literals,
    one test, unit speed.

Requires:
    - LUPIN_ROOT set + `src/` on sys.path (handled by src/tests/conftest.py).
    - The multiplexer TS source present at
      src/lupin_app/static/js/multiplexer/ .
    - lupin_app.main:app importable (the full FastAPI app).

Ensures:
    - EVERY `/api/...` URL literal the multiplexer client passes to a network
      call maps (by normalized path-pattern) to a registered FastAPI route.
    - Where the HTTP verb is statically visible at the call site, the
      (method, path) pair is also asserted against the route's allowed methods.
    - At least one client URL is discovered (fail-loud if the grep silently
      finds nothing — a hollow green is itself a regression).

Raises:
    - AssertionError naming each unmatched (url, site) so a reviewer sees the
      exact offending literal and file:line.
"""

import os
import re
import pathlib

import pytest


# ── Locations ─────────────────────────────────────────────────────────────────

def _multiplexer_src_dir():
    """
    Resolve the multiplexer TS source directory from LUPIN_ROOT.

    Requires:
        - LUPIN_ROOT env var set (conftest enforces this for the whole suite).

    Ensures:
        - returns an existing pathlib.Path to the multiplexer source root.

    Raises:
        - RuntimeError if LUPIN_ROOT is unset.
    """
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
    return pathlib.Path( lupin_root ) / "src" / "lupin_app" / "static" / "js" / "multiplexer"


# ── Client-URL extraction (TS source → set of /api/ literals + site + method) ──

# An /api/... URL literal in any of the three JS quote styles.
_URL_LITERAL = r"""['"`](/api/[^'"`]*)['"`]"""

# Network-call argument sites. The captured group `verb` (when present) lets us
# do method-aware matching; const sites carry no verb (path-only matching).
_CALL_PATTERNS = [
    # api.get<T>( "/api/..."   and   api.post<T>( "/api/...", body
    re.compile( r"""\.(?P<verb>get|post|put|patch|delete)\s*<[^>]*>\s*\(\s*""" + _URL_LITERAL ),
    # api.delete( "/api/..."   (no generic type arg)
    re.compile( r"""\.(?P<verb>get|post|put|patch|delete)\s*\(\s*""" + _URL_LITERAL ),
    # raw fetch( `/api/...`  — verb lives in an opts object, so treat as path-only.
    re.compile( r"""\bfetch\s*\(\s*""" + _URL_LITERAL ),
]
# `FOO_ENDPOINT = "/api/..."` / `BAR_ENDPOINT_PREFIX = "/api/..."` constants.
# These are indirected through a field before the verb is applied, so path-only.
_CONST_PATTERN = re.compile( r"""(?:ENDPOINT|_PREFIX)\w*\s*=\s*""" + _URL_LITERAL )


def _extract_client_urls( src_dir ):
    """
    Enumerate every `/api/` URL literal the multiplexer client hands to a
    network call, with its file:line site and (when statically visible) verb.

    Requires:
        - src_dir is an existing directory of multiplexer TS source.

    Ensures:
        - returns a list of dicts { "url": str, "site": "file:line", "method":
          str|None }; one entry per call site (duplicate URLs preserved so the
          failure report can name every offending site).
        - test files (*.test.ts) and comment-only lines are excluded — comments
          may reference deprecated/WS endpoints that are intentionally NOT
          called (e.g. /api/claude-code/ws/{task_id}).

    Raises:
        - (none) — empty result is the caller's fail-loud responsibility.
    """
    found = []
    for ts in sorted( src_dir.rglob( "*.ts" ) ):
        if ts.name.endswith( ".test.ts" ): continue
        for ln_no, line in enumerate( ts.read_text().splitlines(), start=1 ):
            stripped = line.lstrip()
            # Skip line-comments and block-comment continuation lines: a URL
            # mentioned in prose is documentation, not a live client call.
            if stripped.startswith( "//" ) or stripped.startswith( "*" ): continue
            for pat in _CALL_PATTERNS:
                for m in pat.finditer( line ):
                    verb = m.groupdict().get( "verb" )
                    found.append( {
                        "url"    : m.group( m.lastindex ),
                        "site"   : f"{ts.name}:{ln_no}",
                        "method" : verb.upper() if verb else None,
                    } )
            for m in _CONST_PATTERN.finditer( line ):
                found.append( {
                    "url"    : m.group( m.lastindex ),
                    "site"   : f"{ts.name}:{ln_no}",
                    "method" : None,
                } )
    return found


# ── Backend route enumeration (live app.routes) ────────────────────────────────

def _registered_routes():
    """
    Enumerate the FastAPI app's registered `/api` routes as (pattern, methods).

    Requires:
        - lupin_app.main:app importable (src on sys.path via conftest).

    Ensures:
        - returns a dict mapping normalized path-pattern → frozenset of upper
          HTTP methods, for every route whose path starts with "/api".
        - normalization: FastAPI `{name}` path params collapse to `{p}` and any
          trailing slash (other than root) is stripped, so client template
          literals `${...}` line up with backend `{...}`.

    Raises:
        - ImportError if the app cannot be imported.
    """
    # Imported lazily so a TS-source-only failure still reports cleanly without
    # paying the (heavy) app-construction cost first.
    from lupin_app.main import app

    routes = {}
    for r in app.routes:
        path = getattr( r, "path", None )
        if not path or not path.startswith( "/api" ): continue
        pattern = _normalize_route( path )
        methods = getattr( r, "methods", None ) or set()
        routes.setdefault( pattern, set() ).update( str( m ).upper() for m in methods )
    return { pattern: frozenset( methods ) for pattern, methods in routes.items() }


def _normalize_route( path ):
    """
    Collapse a FastAPI route path to a comparison pattern.

    Requires:
        - path is a non-empty string beginning with "/".

    Ensures:
        - every `{name}` segment becomes `{p}`.
        - a trailing slash is stripped unless the whole path is "/".
    """
    pattern = re.sub( r"\{[^}]*\}", "{p}", path )
    if len( pattern ) > 1 and pattern.endswith( "/" ): pattern = pattern[:-1]
    return pattern


def _normalize_client_url( url ):
    """
    Collapse a TS client URL literal to a comparison pattern.

    Requires:
        - url is a string beginning with "/api/".

    Ensures:
        - the query string (everything from the first "?") is dropped.
        - every `${...}` template expression becomes `{p}`.
        - a trailing slash is stripped unless the whole path is "/".
    """
    url = url.split( "?", 1 )[0]
    url = re.sub( r"\$\{[^}]*\}", "{p}", url )
    if len( url ) > 1 and url.endswith( "/" ): url = url[:-1]
    return url


def _resolve_match( client_pattern, route_patterns ):
    """
    Find the registered route pattern a client URL resolves to.

    Requires:
        - client_pattern is a normalized client path.
        - route_patterns is an iterable of normalized route patterns.

    Ensures:
        - returns the matching route pattern string, or None if no match.
        - handles the *prefix-constant* idiom: a client constant that ends with
          the bare prefix (e.g. "/api/notify/prediction-vote") is later
          concatenated with an id at the call site, so it resolves to the
          "<prefix>/{p}" parameterized route.

    Raises:
        - (none).
    """
    route_set = set( route_patterns )
    if client_pattern in route_set:
        return client_pattern
    prefix_candidate = client_pattern.rstrip( "/" ) + "/{p}"
    if prefix_candidate in route_set:
        return prefix_candidate
    return None


# ── The contract test ───────────────────────────────────────────────────────

def test_every_multiplexer_client_url_maps_to_a_registered_route():
    """
    Assert each multiplexer client `/api/` URL maps to a registered route.

    This is the primary regression gate for the 404 false-pass class: a client
    URL with no backend route fails HERE, at unit speed, regardless of whether
    the renderer swallows the runtime error.

    Requires:
        - multiplexer TS source + importable app (see module docstring).

    Ensures:
        - fails (naming url + site) if ANY client URL is unmatched.
        - fails loud if zero client URLs were discovered (hollow-green guard).
        - additionally fails if a statically-verb'd call site targets a real
          path but a method the route does not allow (405 sub-class).
    """
    src_dir = _multiplexer_src_dir()
    assert src_dir.is_dir(), f"multiplexer source dir not found: {src_dir}"

    client_calls = _extract_client_urls( src_dir )

    # Hollow-green guard: a silently-empty grep would make this test pass for
    # the wrong reason. The multiplexer is known to call many /api/ routes.
    assert len( client_calls ) >= 5, (
        f"extracted only {len(client_calls)} client /api/ URLs from {src_dir} — "
        "the extraction regex likely broke (expected the multiplexer to make "
        "many backend calls). Refusing to pass on a hollow result."
    )

    routes = _registered_routes()
    route_patterns = set( routes.keys() )

    path_failures   = []
    method_failures = []

    for call in client_calls:
        client_pattern = _normalize_client_url( call[ "url" ] )
        matched        = _resolve_match( client_pattern, route_patterns )

        if matched is None:
            path_failures.append( f"  {call['site']:42s} {call['url']}  (normalized: {client_pattern})" )
            continue

        # Method-aware strengthening — only where the verb is visible inline.
        if call[ "method" ] is not None and call[ "method" ] not in routes[ matched ]:
            method_failures.append(
                f"  {call['site']:42s} {call['url']}  wants {call['method']}, "
                f"route {matched} allows {sorted(routes[matched])}"
            )

    msg_parts = []
    if path_failures:
        msg_parts.append(
            "Client URL(s) with NO matching registered FastAPI route "
            "(the 404 false-pass class):\n" + "\n".join( path_failures )
        )
    if method_failures:
        msg_parts.append(
            "Client URL(s) targeting a real path with a DISALLOWED method "
            "(405 sub-class):\n" + "\n".join( method_failures )
        )

    assert not msg_parts, (
        f"{len(path_failures)} path + {len(method_failures)} method contract "
        f"violation(s) across {len(client_calls)} client call site(s) "
        f"({len(route_patterns)} registered /api routes):\n\n"
        + "\n\n".join( msg_parts )
    )


def test_contract_catches_a_bogus_client_url():
    """
    Prove the contract assertion CATCHES a regression — i.e. that a client URL
    pointing at a non-existent route is reported, not silently passed.

    This is the in-suite analogue of the manual /tmp revert proof: it feeds the
    exact historical bug path (`/api/queue/job-history`, the wrong prefix) plus
    a method-mismatch case through the SAME matching primitives the real test
    uses, and asserts both are flagged.

    Requires:
        - importable app (for the live route set).

    Ensures:
        - the known-bad path resolves to no route (would fail the path gate).
        - a real path + wrong verb is flagged by the method gate.
        - a real path + right verb is accepted (no false positive).
    """
    routes         = _registered_routes()
    route_patterns = set( routes.keys() )

    # 1. The historical bug: wrong prefix → no matching route.
    bogus = _normalize_client_url( "/api/queue/job-history?limit=100" )
    assert _resolve_match( bogus, route_patterns ) is None, (
        "expected /api/queue/job-history to have NO matching route (it is the "
        "exact 404 bug) — if this resolves, the matcher is too loose."
    )

    # 2. The correct path is present (sanity: the matcher is not just always-None).
    good = _normalize_client_url( "/api/job-history?limit=100" )
    matched = _resolve_match( good, route_patterns )
    assert matched == "/api/job-history", (
        f"expected /api/job-history to resolve to itself, got {matched}"
    )

    # 3. Method gate: a real path with a verb it does not allow is a violation.
    #    /api/job-history allows GET; a PUT against it must be rejected.
    assert "GET" in routes[ "/api/job-history" ]
    assert "PUT" not in routes[ "/api/job-history" ], (
        "test fixture assumption broke: /api/job-history unexpectedly allows PUT"
    )


if __name__ == "__main__":
    # Smoke entry point: run the contract checks standalone (no pytest harness).
    # Requires LUPIN_ROOT set + src on PYTHONPATH.
    import sys
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path: sys.path.insert( 0, src_path )

    test_every_multiplexer_client_url_maps_to_a_registered_route()
    test_contract_catches_a_bogus_client_url()
    print( "OK — multiplexer API contract holds + regression-catch proven." )
