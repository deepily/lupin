"""
Smoke tests for /api/docs/file under unified path-prefix routing.

Tier: smoke (:7999, AI-discretionary per CLAUDE.md TESTING VENUES).

Rewritten 2026-05-16: the legacy `scope=docs` model these tests originally
covered was retired by the 2026-05-15 unification (Q-R2). Every test now
uses the new `?path=<project>/<rel>` form with JWT auth. The `lupin` scope
replaces the legacy `docs` scope.

For multi-repo external-scope tests see test_external_scopes.py.
For the 2026-05-16 dispatcher / health regression suite see
test_doc_viewer_path_prefix_routing.py.

Covered:
- Whitelisted file serves with markdown content type (lupin/CLAUDE.md)
- Whitelisted prefix serves a known doc (lupin/src/docs/...)
- Directory listing returns JSON shape
- Bare prefix root + trailing-slash variants both list successfully
- Hidden entries / unwhitelisted extensions filtered from listings
- Entries sort directories-first
- Whitelisted but missing returns 404
- Directory-traversal blocked
- Unsupported extension rejected
- Missing auth returns 401
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest


BASE_URL    = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
DOCS_URL    = f"{BASE_URL}/api/docs/file"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login() -> str:
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
        return json.loads( resp.read() )[ "tokens" ][ "access_token" ]


def _get( path: str, token: str = None ):
    """GET /api/docs/file?path=<path> → (status_code, content_type, body_bytes)."""
    url     = f"{DOCS_URL}?path={urllib.parse.quote( path, safe='/' )}"
    headers = { "Authorization": f"Bearer {token}" } if token else { }
    req     = urllib.request.Request( url, headers=headers, method="GET" )
    try:
        with urllib.request.urlopen( req, timeout=10 ) as resp:
            return resp.status, resp.headers.get( "content-type", "" ), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get( "content-type", "" ), e.read()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture( scope="module" )
def token():
    return _login()


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

def test_missing_auth_returns_401():
    status, _ctype, _body = _get( "lupin/CLAUDE.md" )
    assert status == 401


# ---------------------------------------------------------------------------
# File-serving happy paths
# ---------------------------------------------------------------------------

def test_lupin_scope_root_file_serves( token ):
    """Root-level whitelisted file (lupin/CLAUDE.md) serves as markdown."""
    status, ctype, body = _get( "lupin/CLAUDE.md", token=token )
    assert status == 200, f"got {status}: {body!r}"
    assert ctype.startswith( "text/markdown" )
    assert b"#" in body[ :200 ]


def test_lupin_scope_prefix_file_serves( token ):
    """File under whitelisted prefix (lupin/src/docs/...) serves."""
    status, ctype, body = _get( "lupin/src/docs/notification-api.md", token=token )
    assert status == 200, f"got {status}: {body!r}"
    assert ctype.startswith( "text/markdown" )
    assert b"#" in body[ :200 ]


# ---------------------------------------------------------------------------
# Reject paths
# ---------------------------------------------------------------------------

def test_path_outside_manifest_rejected( token ):
    """lupin/.docview.yml allows `src/` only — io/ is outside."""
    status, _ctype, body = _get( "lupin/io/agents/", token=token )
    assert status == 400, f"got {status}: {body!r}"
    detail = json.loads( body )[ "detail" ].lower()
    assert "whitelist" in detail


def test_directory_traversal_blocked( token ):
    """Path-traversal attempt blocked before disk access."""
    status, _ctype, _body = _get( "lupin/../../../etc/passwd", token=token )
    assert status == 400


def test_unsupported_extension_rejected( token ):
    """File extension outside MEDIA_TYPES is rejected (400 or 404 acceptable)."""
    status, _ctype, _body = _get( "lupin/src/conf/keys/openai", token=token )
    assert status in ( 400, 404 )


def test_whitelisted_but_missing_returns_404( token ):
    status, _ctype, _body = _get(
        "lupin/src/docs/this-file-definitely-does-not-exist-2026-05-16.md",
        token=token
    )
    assert status == 404


# ---------------------------------------------------------------------------
# Directory listing
# ---------------------------------------------------------------------------

def test_directory_listing_returns_json_shape( token ):
    """Polymorphic dispatch: directory path returns JSON, not text."""
    status, ctype, body = _get( "lupin/src/rnd/v0.1.7", token=token )
    assert status == 200, f"got {status}: {body!r}"
    assert ctype.startswith( "application/json" )
    listing = json.loads( body )
    assert listing[ "kind" ] == "directory"
    assert listing[ "scope" ] == "lupin"
    assert listing[ "path" ] == "src/rnd/v0.1.7"
    assert "parent" in listing
    assert isinstance( listing[ "entries" ], list )


def test_directory_listing_bare_prefix_root( token ):
    """Bare prefix root (no trailing slash) lists successfully."""
    status, ctype, body = _get( "lupin/src/rnd", token=token )
    assert status == 200, f"got {status}: {body!r}"
    assert ctype.startswith( "application/json" )
    listing = json.loads( body )
    assert listing[ "kind" ] == "directory"
    assert listing[ "path" ] == "src/rnd"


def test_directory_listing_with_trailing_slash( token ):
    """Trailing-slash form lists identically to bare form."""
    status, _ctype, body = _get( "lupin/src/rnd/", token=token )
    assert status == 200
    listing = json.loads( body )
    assert listing[ "path" ] == "src/rnd"   # trailing slash normalized away


def test_directory_listing_outside_whitelist_rejected( token ):
    """Whitelist boundary still holds for directory requests."""
    status, _ctype, body = _get( "lupin/io", token=token )
    assert status == 400
    assert "whitelist" in json.loads( body )[ "detail" ].lower()


def test_directory_listing_nonexistent_returns_404( token ):
    """Whitelisted-but-missing directory returns 404."""
    status, _ctype, _body = _get(
        "lupin/src/rnd/no-such-dir-2026-05-16-unique",
        token=token
    )
    assert status == 404


def test_directory_listing_excludes_hidden_files( token ):
    status, _ctype, body = _get( "lupin/src/rnd/v0.1.7", token=token )
    assert status == 200
    listing = json.loads( body )
    for entry in listing[ "entries" ]:
        assert not entry[ "name" ].startswith( "." ), \
            f"hidden entry leaked: {entry[ 'name' ]}"


def test_directory_listing_entries_sorted_dirs_first( token ):
    status, _ctype, body = _get( "lupin/src/rnd/v0.1.7", token=token )
    assert status == 200
    listing = json.loads( body )
    kinds = [ e[ "kind" ] for e in listing[ "entries" ] ]
    if "directory" in kinds and "file" in kinds:
        last_dir   = max( i for i, k in enumerate( kinds ) if k == "directory" )
        first_file = min( i for i, k in enumerate( kinds ) if k == "file" )
        assert last_dir < first_file, "files mixed in before all directories"


def test_directory_listing_view_url_uses_path_prefix( token ):
    """Every entry has a view_url; /app/docs URLs carry the project prefix."""
    status, _ctype, body = _get( "lupin/src/rnd/v0.1.7", token=token )
    assert status == 200
    listing = json.loads( body )
    assert listing[ "entries" ]
    for entry in listing[ "entries" ]:
        view = entry.get( "view_url" )
        assert view, f"missing view_url: {entry}"
        # Legacy ?scope= form is forbidden under the new model
        assert "scope=" not in view, f"legacy ?scope= leaked: {view}"
        if view.startswith( "/app/docs?path=" ):
            decoded = urllib.parse.unquote( view.split( "path=", 1 )[ 1 ] )
            assert decoded.startswith( "lupin/" ), \
                f"view_url missing 'lupin/' prefix: {view}"


# ---------------------------------------------------------------------------
# Aggressive deprecation of legacy ?scope= query parameter (2026-05-21)
#
# Policy: any presence of ?scope= (even empty) returns 400 with educational
# detail. Replaces prior silent-ignore semantics (Phase 4b AC4b.7 original).
# See src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md
# (Amendment 2026-05-21) for the policy-flip record.
# ---------------------------------------------------------------------------

def _get_with_query( query_string: str, token: str = None ):
    """GET /api/docs/file?<raw query> → (status, body_bytes)."""
    url     = f"{DOCS_URL}?{query_string}"
    headers = { "Authorization": f"Bearer {token}" } if token else { }
    req     = urllib.request.Request( url, headers=headers, method="GET" )
    try:
        with urllib.request.urlopen( req, timeout=10 ) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_legacy_scope_param_with_value_returns_400( token ):
    """?scope=docs alongside a valid path → 400 with educational detail."""
    status, body = _get_with_query( "path=lupin/CLAUDE.md&scope=docs", token=token )
    assert status == 400, f"got {status}: {body!r}"
    detail = json.loads( body )[ "detail" ]
    assert "RETIRED" in detail
    assert "?path=<project>/<file>" in detail
    assert "lupin" in detail  # registered-project list includes lupin
    assert "doc-viewer-links.md" in detail or "Doc Viewer Scope" in detail


def test_legacy_scope_param_with_empty_value_returns_400( token ):
    """?scope= (empty value) is still presence → 400."""
    status, body = _get_with_query( "path=lupin/CLAUDE.md&scope=", token=token )
    assert status == 400, f"got {status}: {body!r}"
    detail = json.loads( body )[ "detail" ]
    assert "RETIRED" in detail


def test_legacy_scope_param_fires_before_path_validation( token ):
    """?scope= check fires BEFORE path validation — even with no path
    prefix or empty path, the scope=-presence 400 wins.
    """
    # Path missing project prefix would normally 400 "Missing project prefix";
    # presence of scope= overrides to the educational error.
    status, body = _get_with_query( "path=bug-fix-queue.md&scope=docs", token=token )
    assert status == 400, f"got {status}: {body!r}"
    detail = json.loads( body )[ "detail" ]
    assert "RETIRED" in detail
    assert "Missing project prefix" not in detail


def test_canonical_path_prefix_form_unchanged( token ):
    """Canonical form (no scope=) keeps working — regression guard."""
    status, _body = _get_with_query( "path=lupin/CLAUDE.md", token=token )
    assert status == 200


# ---------------------------------------------------------------------------
# Image MIME support (2026-05-21)
#
# Policy: extensions in {.png,.jpg,.jpeg,.gif,.svg,.webp} serve as image/*
# via FileResponse (binary). Text MIMEs continue using PlainTextResponse.
# Existing extensions are unaffected.
# Driven by Rachel's git_loc_delta plot-sharing use case (CoSA session
# e13fed4f) and the Lupin+CoSA joint-patch design ratified 2026-05-21.
# ---------------------------------------------------------------------------

def test_png_serves_with_image_png_content_type( token ):
    """A real PNG (Firefox plugin icon) serves as image/png with binary bytes."""
    status, ctype, body = _get(
        "lupin/src/lupin-plugin-firefox/icons/microphone-48.png",
        token = token,
    )
    assert status == 200, f"got {status}: {body[ :100 ]!r}"
    assert ctype.startswith( "image/png" ), f"unexpected content-type: {ctype}"
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    assert body[ :8 ] == b"\x89PNG\r\n\x1a\n", f"missing PNG magic: {body[ :8 ]!r}"


def test_text_markdown_still_serves_as_text( token ):
    """Regression guard: existing text MIME path still serves as text/markdown."""
    status, ctype, body = _get( "lupin/CLAUDE.md", token=token )
    assert status == 200
    assert ctype.startswith( "text/markdown" ), f"text path regressed: {ctype}"
    # Should be human-readable markdown, not binary
    assert b"#" in body[ :2000 ]


def test_directory_listing_includes_image_files( token ):
    """Directory listings include image files now that MEDIA_TYPES expanded."""
    status, ctype, body = _get(
        "lupin/src/lupin-plugin-firefox/icons/",
        token = token,
    )
    assert status == 200, f"got {status}: {body[ :200 ]!r}"
    assert ctype.startswith( "application/json" ), f"unexpected ctype: {ctype}"
    listing = json.loads( body )
    entry_names = [ e[ "name" ] for e in listing.get( "entries", [] ) ]
    # The icons directory is full of PNGs; at least one should show up
    png_count = sum( 1 for n in entry_names if n.endswith( ".png" ) )
    assert png_count > 0, f"no PNGs in directory listing: {entry_names!r}"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
