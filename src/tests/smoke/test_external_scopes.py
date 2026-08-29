"""
Smoke tests for the multi-repo doc viewer's external-scope handling under
unified path-prefix routing.

Tier: smoke (:7999, AI-discretionary per CLAUDE.md TESTING VENUES).
Design docs:
- src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md §5 (original)
- src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md (path-prefix routing)

Rewritten 2026-05-16 for the unification model: tests now use the
`?path=<project>/<rel>` form. The legacy `?scope=` query param is retired
server-side (Q-R2). The legacy `docs` scope is fully replaced by `lupin`.

Covered:
- Per-scope directory listing via path-prefix form
- Per-scope file fetch (markdown + source-code)
- Lupin scope is the canonical replacement for the retired `docs` scope
- Unknown project prefix → 400
- Missing project prefix → 400
- Cross-scope traversal blocked → 400
- Secrets blocklist → 400
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
    """POST /auth/login → access token (per reference_auth_testing_contract)."""
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
def registered_scopes():
    """
    Hit /api/docs/health (unauthenticated) and return the list of registered
    scope names. The health endpoint's `scopes` field is the source of truth.
    """
    status, _, body = _fetch( "/api/docs/health" )
    if status != 200:
        pytest.skip( f"/api/docs/health failed: {status}" )
    return list( json.loads( body )[ "scopes" ].keys() )


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

class TestAuthGate:
    """JWT auth is required on both /api/docs/file and /api/io/file."""

    def test_docs_file_without_auth_returns_401( self ):
        status, _, _ = _fetch(
            "/api/docs/file",
            query = { "path": "lupin/CLAUDE.md" },
        )
        assert status == 401, f"expected 401, got {status}"

    def test_io_file_without_auth_returns_401( self ):
        status, _, _ = _fetch( "/api/io/file", query={ "path": "anything.md" } )
        assert status == 401, f"expected 401, got {status}"

    def test_docs_file_with_auth_passes_gate( self, access_token ):
        # Don't assert on 200 specifically — assert it's NOT 401, which proves
        # the auth gate accepts the token. The path may or may not resolve;
        # either way it should be past auth.
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src" },
        )
        assert status != 401, f"auth header rejected — got {status}"


# ---------------------------------------------------------------------------
# Unified path-prefix routing — project as first segment of `path`
# ---------------------------------------------------------------------------

class TestPathPrefixRouting:

    def test_missing_project_prefix_returns_400( self, access_token ):
        # Bare path with no slash → server can't extract project name.
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "anything" },
        )
        assert status == 400, f"expected 400, got {status}"
        assert b"project prefix" in body.lower()

    def test_unknown_project_returns_400( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "this-project-does-not-exist/foo.md" },
        )
        assert status == 400, f"expected 400, got {status}"
        assert b"unknown project" in body.lower()

    def test_legacy_scope_query_param_is_rejected_with_400( self, access_token ):
        """
        The server REJECTS `?scope=` with an educational 400.

        Refreshed 2026-08-26. This asserted the opposite — Q-R2's original
        silent-ignore rule, under which a request carrying both `path=` and
        `scope=` returned 200 as if `scope` were absent. The policy was flipped
        from silent-ignore to aggressive-400 on 2026-05-21 (amendment to AC4b.7
        of src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md; shipped in
        53fef419). Both the endpoint's own OpenAPI description
        (docs_files.py:125) and CLAUDE.md § Doc Viewer Scope document the flip,
        and the scope-presence check fires BEFORE path validation — so a valid
        path does not rescue the request. The test was simply left behind.
        """
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/CLAUDE.md", "scope": "irrelevant-junk" },
        )
        assert status == 400, f"expected 400 for a retired scope param, got {status} body={body[:200]!r}"
        assert b"retired" in body.lower(), f"400 body should name the retirement; got {body[:200]!r}"
        # The message must point at the canonical form, not just refuse.
        assert b"path=" in body.lower(), f"400 body should name the canonical form; got {body[:200]!r}"


# ---------------------------------------------------------------------------
# Per-scope routing — lupin replaces the retired `docs` scope
# ---------------------------------------------------------------------------

class TestLupinScope:
    """lupin is the canonical replacement for the retired legacy `docs` scope."""

    def test_lupin_scope_lists_src( self, access_token ):
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src" },
        )
        assert status == 200, f"lupin/src listing failed: {status} body={body[:200]!r}"
        assert "application/json" in ct
        listing = json.loads( body )
        assert listing[ "scope" ] == "lupin"
        assert listing[ "kind" ] == "directory"
        assert len( listing[ "entries" ] ) > 0, "lupin/src listing was empty"

    def test_lupin_root_md_serves( self, access_token ):
        """Root-level CLAUDE.md is in the manifest's allowed_root_files."""
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/CLAUDE.md" },
        )
        assert status == 200, f"lupin/CLAUDE.md fetch failed: {status}"
        assert ct.startswith( "text/markdown" )
        assert b"#" in body[ :200 ]


class TestExternalScopes:
    """Each registered external scope should at minimum list its root."""

    def test_claude_plans_scope_lists_root( self, access_token, registered_scopes ):
        if "claude-plans" not in registered_scopes:
            pytest.skip( "claude-plans scope not registered" )
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "claude-plans/" },
        )
        assert status == 200, f"claude-plans root listing failed: {status} body={body[:200]!r}"
        listing = json.loads( body )
        assert listing[ "scope" ] == "claude-plans"
        # claude-plans has many .md plans; ≥1 entry confirms reach
        assert len( listing[ "entries" ] ) >= 1


# ---------------------------------------------------------------------------
# Traversal block
# ---------------------------------------------------------------------------

class TestTraversalBlocked:

    def test_dot_dot_traversal_blocked( self, access_token, registered_scopes ):
        if not registered_scopes:
            pytest.skip( "no scopes registered" )
        scope = registered_scopes[ 0 ]
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": f"{scope}/../etc/passwd" },
        )
        # Two valid rejection paths:
        #   - 400 from whitelist check (non-empty prefix list)
        #   - 400 from resolve_in_scope traversal block (empty prefix list)
        assert status == 400, f"traversal not blocked — got {status}"


# ---------------------------------------------------------------------------
# Secrets blocklist — universal floor, applies BEFORE project resolution
# ---------------------------------------------------------------------------

class TestSecretsBlocklist:

    def test_blocklist_rejects_dotenv_path( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src/.env" },
        )
        assert status == 400, f"expected 400 for .env path, got {status}"
        assert b"secrets blocklist" in body.lower() or b"secret" in body.lower()

    def test_blocklist_rejects_credentials_path( self, access_token ):
        status, _, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src/credentials.json" },
        )
        assert status == 400
        assert b"secrets blocklist" in body.lower()

    def test_blocklist_rejects_id_rsa_path( self, access_token ):
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src/id_rsa" },
        )
        assert status == 400


# ---------------------------------------------------------------------------
# Source-code serving — MEDIA_TYPES expansion lets .py files be fetched
# ---------------------------------------------------------------------------

class TestSourceCodeServing:

    def test_python_file_served_as_text( self, access_token ):
        # Pick a known-stable file — `_scope_registry.py` itself.
        status, ct, body = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src/cosa/rest/routers/_scope_registry.py" },
        )
        assert status == 200, f"py fetch failed: {status} body={body[:200]!r}"
        assert ct.startswith( "text/x-python" ), f"wrong content-type for .py: {ct!r}"
        # Sanity: file contents include the module-level docstring header
        assert b"Scope registry" in body


# ---------------------------------------------------------------------------
# Unsupported extension
# ---------------------------------------------------------------------------

class TestUnknownExtensionRejected:

    def test_unknown_extension_returns_400( self, access_token ):
        # Path the scope-whitelist allows but with an extension outside
        # MEDIA_TYPES. Either 400 (unsupported ext) OR 404 (file not found)
        # is acceptable; we explicitly DO NOT accept 200.
        status, _, _ = _fetch(
            "/api/docs/file",
            token = access_token,
            query = { "path": "lupin/src/somefile.exe" },
        )
        assert status in ( 400, 404 ), f"unexpected status {status}"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
