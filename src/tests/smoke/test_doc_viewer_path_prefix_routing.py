"""
Smoke tests for the doc-viewer path-prefix routing regression fix.

Tier: smoke (:7999, AI-discretionary per CLAUDE.md TESTING VENUES).
Companion bug fix: 2026-05-16 — frontend SPA dispatcher in
src/lupin_app/static/html/document-viewer.html still defaulted scope
to 'io' and routed all unprefixed paths to /api/io/file, causing 404
on every /app/docs?path=lupin/... URL the doc-link mandate produces.
Also fixes the latent /api/docs/health NameError on the retired
ALLOWED_FILES/ALLOWED_PREFIXES constants.

Covered:
- /api/docs/file?path=lupin/<rel> serves the project file (the user's
  reproducer URL) end-to-end with JWT auth.
- /api/docs/file?path=lupin/ returns a directory-listing JSON shape.
- /api/docs/health returns 200 with the new shape (status, project_root,
  io, scopes, media_types) — no more NameError.
- The static document-viewer.html ships the new dispatcher (sanity check
  that the deploy applied; protects against accidental rollback).
- The directory-listing view_url field is path-prefixed (not legacy
  ?path=...&scope=...).

Run:
    pytest src/tests/smoke/test_doc_viewer_path_prefix_routing.py -v
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest


BASE_URL    = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
DOCS_FILE   = f"{BASE_URL}/api/docs/file"
DOCS_HEALTH = f"{BASE_URL}/api/docs/health"
DOC_VIEWER  = f"{BASE_URL}/static/html/document-viewer.html"


def _login() -> str:
    """POST /auth/login → access token (per reference_auth_testing_contract)."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD} not set" )

    body = json.dumps( { "email": email, "password": password } ).encode()
    req  = urllib.request.Request(
        f"{BASE_URL}/auth/login",
        data    = body,
        headers = { "Content-Type": "application/json" },
        method  = "POST",
    )
    with urllib.request.urlopen( req, timeout=10 ) as resp:
        payload = json.loads( resp.read() )
    return payload[ "tokens" ][ "access_token" ]


def _fetch( url: str, token: str = None ):
    """GET → (status, content_type, body_bytes). 4xx/5xx do not raise."""
    headers = { "Authorization": f"Bearer {token}" } if token else { }
    req     = urllib.request.Request( url, headers=headers, method="GET" )
    try:
        with urllib.request.urlopen( req, timeout=10 ) as resp:
            return resp.status, resp.headers.get( "content-type", "" ), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get( "content-type", "" ), e.read()


@pytest.fixture( scope="module" )
def token():
    return _login()


# ---------------------------------------------------------------------------
# Health endpoint — was 500 with NameError before the fix
# ---------------------------------------------------------------------------

def test_health_endpoint_returns_200_with_new_shape():
    status, ctype, body = _fetch( DOCS_HEALTH )
    assert status == 200, f"expected 200, got {status}: {body!r}"
    assert "application/json" in ctype

    payload = json.loads( body )
    assert payload[ "status" ] == "ok"
    assert "project_root" in payload
    assert "io" in payload and "exists" in payload[ "io" ]
    assert "scopes" in payload
    assert "media_types" in payload

    # lupin scope MUST be present — the user's bug depended on it
    assert "lupin" in payload[ "scopes" ], \
        f"lupin scope missing from registry: {sorted( payload['scopes'].keys() )}"
    lupin_scope = payload[ "scopes" ][ "lupin" ]
    assert lupin_scope[ "exists" ] is True
    assert "src/" in lupin_scope[ "allowed_prefixes" ]


# ---------------------------------------------------------------------------
# /api/docs/file — the original failing endpoint, with new-form path prefix
# ---------------------------------------------------------------------------

def test_lupin_scope_file_serves_via_path_prefix( token ):
    # Use CLAUDE.md as a stable witness — present in every lupin checkout.
    url = f"{DOCS_FILE}?path=lupin/CLAUDE.md"
    status, ctype, body = _fetch( url, token=token )
    assert status == 200, f"expected 200, got {status}: {body!r}"
    assert ctype.startswith( "text/markdown" )
    # Cheap sanity: CLAUDE.md starts with a header
    assert b"#" in body[ :200 ]


def test_lupin_scope_root_listing_via_path_prefix( token ):
    # Path-prefix form for the scope root: ?path=lupin/  (trailing slash)
    url = f"{DOCS_FILE}?path=lupin/"
    status, ctype, body = _fetch( url, token=token )
    assert status == 200
    assert "application/json" in ctype

    listing = json.loads( body )
    assert listing[ "kind" ] == "directory"
    assert listing[ "scope" ] == "lupin"
    assert isinstance( listing[ "entries" ], list )


def test_unknown_project_prefix_returns_400( token ):
    url = f"{DOCS_FILE}?path=not-a-real-project/foo.md"
    status, _ctype, body = _fetch( url, token=token )
    assert status == 400
    detail = json.loads( body )[ "detail" ]
    assert "unknown project" in detail.lower()


def test_missing_project_prefix_returns_400( token ):
    # Bare path without a project prefix is the legacy form — backend now rejects.
    url = f"{DOCS_FILE}?path=CLAUDE.md"
    status, _ctype, body = _fetch( url, token=token )
    assert status == 400
    detail = json.loads( body )[ "detail" ]
    assert "project prefix" in detail.lower()


# ---------------------------------------------------------------------------
# Directory listing view_url shape — must be path-prefixed, not legacy
# ---------------------------------------------------------------------------

def test_directory_listing_view_urls_use_path_prefix( token ):
    url = f"{DOCS_FILE}?path=lupin/src/"
    status, _ctype, body = _fetch( url, token=token )
    assert status == 200, f"expected 200, got {status}: {body!r}"
    listing = json.loads( body )
    assert listing[ "entries" ], "src/ should not be empty"

    for entry in listing[ "entries" ]:
        view = entry.get( "view_url", "" )
        assert view, f"missing view_url on {entry}"
        # Legacy form is forbidden under the new model
        assert "scope=" not in view, \
            f"legacy ?scope= leaked in view_url: {view}"
        # /app/docs URLs must carry the project prefix as the first path segment
        if view.startswith( "/app/docs?path=" ):
            decoded = urllib.parse.unquote( view.split( "path=", 1 )[ 1 ].split( "&", 1 )[ 0 ] )
            assert decoded.startswith( "lupin/" ), \
                f"view_url missing 'lupin/' prefix: {view}"


# ---------------------------------------------------------------------------
# Static SPA HTML deploy sanity — protect against accidental rollback
# ---------------------------------------------------------------------------

def test_static_doc_viewer_contains_new_dispatcher():
    status, ctype, body = _fetch( DOC_VIEWER )
    assert status == 200
    text = body.decode( "utf-8", errors="replace" )
    # Hallmarks of the new dispatcher
    assert "KNOWN_PROJECTS" in text, \
        "document-viewer.html missing KNOWN_PROJECTS — old dispatcher still deployed?"
    assert "2026-05-15 unification" in text or "path-prefix" in text, \
        "document-viewer.html missing unification comment"
    # The old default-to-io defaulting line must be gone
    assert "params.get( 'scope' ) || 'io'" not in text, \
        "old scope-defaulting code still present"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
