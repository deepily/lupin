"""
Smoke tests for the multi-repo doc viewer's external-scope handling.

Tier: smoke (:7999, AI-discretionary per CLAUDE.md TESTING VENUES).
Design doc: src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md §5

Covered:
- Per-scope directory listing
- Per-scope file fetch (markdown + source-code)
- Legacy `scope=docs` route still works without explicit scope param
- Unknown scope → 400
- Cross-scope traversal blocked → 400
- Secrets blocklist → 400 even on a non-existent path
- Auth gate: missing header → 401, valid token → 200
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login( email: str, password: str ) -> str:
    """
    POST /auth/login → access token (per reference_auth_testing_contract).
    """
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


def _fetch( path: str, token: str = None, query: dict = None ):
    """
    GET against BASE_URL with optional Authorization header.

    Returns:
        ( status_code, content_type, body_bytes )

    On HTTP error (4xx/5xx), returns the same tuple — the test inspects
    `status_code` rather than catching an exception.
    """
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode( query )}"

    headers = { }
    if token:
        headers[ "Authorization" ] = f"Bearer {token}"

    req = urllib.request.Request( url, headers=headers, method="GET" )

    try:
        with urllib.request.urlopen( req, timeout=10 ) as resp:
            return resp.status, resp.headers.get( "content-type", "" ), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get( "content-type", "" ), e.read()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture( scope="module" )
def access_token():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD not set" )

    try:
        return _login( email, password )
    except Exception as e:
        pytest.skip( f"login failed: {e}" )


@pytest.fixture( scope="module" )
def registered_scopes( access_token ):
    """
    Hit /api/docs/health (unauthenticated) and return the list of external
    scopes the running server has registered. Avoids hard-coding the list
    here so tests adapt to environment-by-environment differences.
    """
    status, _, body = _fetch( "/api/docs/health" )
    if status != 200:
        pytest.skip( f"/api/docs/health failed: {status}" )
    return list( json.loads( body )[ "external_scopes" ].keys() )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAuthGate:
    """JWT auth is required on both /api/docs/file and /api/io/file."""

    def test_docs_file_without_auth_returns_401( self ):
        status, _, _ = _fetch(
            "/api/docs/file",
            query = { "path": "src/CLAUDE.md", "scope": "lupin" },
        )
        assert status == 401, f"expected 401, got {status}"

    def test_io_file_without_auth_returns_401( self ):
        status, _, _ = _fetch( "/api/io/file", query={ "path": "anything.md" } )
        assert status == 401, f"expected 401, got {status}"

    def test_docs_file_with_auth_returns_200_or_404( self, access_token ):
        # We don't assert on 200 specifically — we assert it's NOT 401, which is
        # what proves the auth gate accepts the token. The path may or may not
        # resolve in this environment; either way it should be past auth.
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src", "scope": "lupin" },
        )
        assert status != 401, f"auth header rejected — got {status}"


class TestLegacyDocsScope:
    """`scope=docs` (or omitted, defaulting to 'docs') must preserve the legacy whitelist."""

    def test_legacy_default_scope_works( self, access_token ):
        # Omit `scope` → defaults to 'docs' per back-compat
        status, ct, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/rnd" },
        )
        assert status == 200, f"legacy scope=docs default broken — got {status}"
        assert "application/json" in ct, f"directory listing should be JSON — got {ct!r}"

    def test_legacy_explicit_scope_works( self, access_token ):
        status, ct, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/rnd", "scope": "docs" },
        )
        assert status == 200
        assert "application/json" in ct


class TestUnknownScope:

    def test_unknown_scope_returns_400( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "anything", "scope": "this-does-not-exist" },
        )
        assert status == 400, f"expected 400 for unknown scope, got {status}"
        assert b"Unknown scope" in body or b"unknown" in body.lower()


class TestTraversalBlocked:

    def test_dot_dot_traversal_blocked( self, access_token, registered_scopes ):
        if not registered_scopes:
            pytest.skip( "no external scopes registered" )
        scope = registered_scopes[ 0 ]
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "../etc/passwd", "scope": scope },
        )
        # Two valid rejection paths:
        #   - 400 from whitelist check (non-empty prefix list)
        #   - 400 from resolve_in_scope traversal block (empty prefix list)
        assert status == 400, f"traversal not blocked — got {status}"


class TestSecretsBlocklist:

    def test_blocklist_rejects_dotenv_path( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/.env", "scope": "lupin" },
        )
        assert status == 400, f"expected 400 for .env path, got {status}"
        assert b"secrets blocklist" in body.lower() or b"secret" in body.lower()

    def test_blocklist_rejects_credentials_path( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/credentials.json", "scope": "lupin" },
        )
        assert status == 400
        assert b"secrets blocklist" in body.lower()

    def test_blocklist_rejects_id_rsa_path( self, access_token ):
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/id_rsa", "scope": "lupin" },
        )
        assert status == 400


class TestPerScopeRouting:
    """Each registered scope should at minimum list its root."""

    def test_lupin_scope_lists_src( self, access_token ):
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src", "scope": "lupin" },
        )
        assert status == 200, f"lupin scope src listing failed: {status} body={body[:200]!r}"
        assert "application/json" in ct
        listing = json.loads( body )
        assert listing[ "scope" ] == "lupin"
        assert listing[ "kind" ] == "directory"
        assert len( listing[ "entries" ] ) > 0, "lupin/src listing was empty"

    def test_claude_plans_scope_lists_root( self, access_token, registered_scopes ):
        if "claude-plans" not in registered_scopes:
            pytest.skip( "claude-plans scope not registered" )
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "", "scope": "claude-plans" },
        )
        assert status == 200, f"claude-plans root listing failed: {status} body={body[:200]!r}"
        listing = json.loads( body )
        assert listing[ "scope" ] == "claude-plans"
        # The directory has many .md plans; assert ≥1 entry to confirm reach
        assert len( listing[ "entries" ] ) >= 1


class TestSourceCodeServing:
    """The MEDIA_TYPES expansion lets source files be fetched as text/*."""

    def test_python_file_served_as_text( self, access_token ):
        # Pick a known-stable file — `_scope_registry.py` itself.
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = {
                "path"  : "src/cosa/rest/routers/_scope_registry.py",
                "scope" : "lupin",
            },
        )
        assert status == 200, f"py fetch failed: {status} body={body[:200]!r}"
        assert ct.startswith( "text/x-python" ), f"wrong content-type for .py: {ct!r}"
        # Sanity: file contents include the module-level docstring header
        assert b"Scope registry" in body


class TestUnknownExtensionRejected:

    def test_unknown_extension_returns_400( self, access_token ):
        # Pass a path the scope-whitelist allows but with an extension
        # outside MEDIA_TYPES. Pick something likely to exist or at least
        # have its extension checked before file-existence.
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "src/somefile.exe", "scope": "lupin" },
        )
        # Either 400 (unsupported ext) OR 404 (file not found) is acceptable;
        # we explicitly DO NOT accept 200. The point is "no .exe content served."
        assert status in ( 400, 404 ), f"unexpected status {status}"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
