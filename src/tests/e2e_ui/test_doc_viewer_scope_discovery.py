"""
E2E regression: the doc-viewer must resolve scopes from the LIVE registry.

Bug `3d41fcba` (2026-07-13). `document-viewer.html` carried a HARDCODED
`KNOWN_PROJECTS` literal. Any repo registered after that literal was last
hand-edited fell through to the legacy `/api/io/file` branch and 404'd — while
the backend resolved the file perfectly and the browser never even asked it.

Rick could not read a doc for ~40 minutes because of a stale JavaScript Set.

The literal was wrong in BOTH directions when found: it listed `cosa-voice`
(not actually registered) and omitted `skills-distillation` (registered, live,
serving 200s). That is the signature of a hand-maintained mirror of a runtime
registry — it drifts silently, and it re-arms for repo #11, #12, #13...

The fix: consume `GET /api/docs/scopes`, whose own docstring calls it "runtime
scope discovery."

WHY THIS TEST DRIVES A REAL BROWSER. The routing decision lives in the page's
JavaScript, not in the API. Every backend assertion passed while the bug was
live — `_is_whitelisted_in_scope` → True, `resolve_in_scope` → the right path,
`os.path.isfile` → True, `/api/docs/file` → 200. The ONLY place the defect is
observable is in which endpoint the browser chooses to call. So we assert on
that: the page must hit `/api/docs/scopes`, must route to `/api/docs/file`, and
must NOT fall back to `/api/io/file`.

Venue: :8000 per the E2E-UI bucket (see CLAUDE.md § TESTING VENUES).
"""

import json
import os

import pytest
import requests


# Parameterized per the house rule — never hardcode the host.
BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


# A scope that did NOT exist when the hardcoded literal was written. The whole point is
# that NOTHING in the frontend had to be edited for this to work. If someone reintroduces
# a literal, this file goes red.
LATE_REGISTERED_SCOPE = "skills-distillation"
DOC_PATH              = f"{LATE_REGISTERED_SCOPE}/docs/explainers/how-skills-distillation-works.md"
DOC_HEADING           = "How Skills Distillation Works"


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    """Login via /auth/login → (access_token, refresh_token)."""
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


@pytest.fixture
def authed_page( page, context ):
    access_token, refresh_token = _login_tokens()
    _seed_auth( context, access_token, refresh_token )
    return page


@pytest.fixture
def api_calls( page ):
    """Record every /api/ request the page makes — the routing decision IS the assertion."""
    calls = []
    page.on( "request", lambda r: calls.append( r.url ) if "/api/" in r.url else None )
    return calls


class TestDocViewerScopeDiscovery:

    def test_late_registered_scope_renders( self, authed_page, api_calls ):
        """
        The acceptance criterion from the bug report, verbatim: the page must RENDER.
        Not "it compiles", not "the endpoint 200s" — it renders, in a browser.
        """
        authed_page.goto( f"{BASE_URL}/app/docs?path={DOC_PATH}", wait_until="networkidle" )

        heading = authed_page.wait_for_selector( "h1", timeout=10_000 )
        assert DOC_HEADING in heading.inner_text()
        assert authed_page.query_selector_all( ".doc-viewer-error" ) == []

    def test_page_consults_the_live_registry( self, authed_page, api_calls ):
        """The viewer must ASK the registry, not consult a literal baked into the page."""
        authed_page.goto( f"{BASE_URL}/app/docs?path={DOC_PATH}", wait_until="networkidle" )

        assert any( "/api/docs/scopes" in c for c in api_calls ), (
            "The viewer never called /api/docs/scopes — it is routing from a hardcoded "
            "list again. That is bug 3d41fcba."
        )

    def test_routes_to_docs_endpoint_not_the_legacy_io_fallback( self, authed_page, api_calls ):
        """
        The bug's exact signature: an unrecognized first segment fell through to
        /api/io/file, which 404s for a project-scoped path. If this fails, the scope set
        has gone stale again.
        """
        authed_page.goto( f"{BASE_URL}/app/docs?path={DOC_PATH}", wait_until="networkidle" )

        assert any( "/api/docs/file" in c for c in api_calls ), "did not route to /api/docs/file"
        assert not any( "/api/io/file" in c for c in api_calls ), (
            "FELL BACK TO /api/io/file — the scope was not recognized. This is the 404 Rick hit."
        )

    def test_long_registered_scope_still_works( self, authed_page, api_calls ):
        """No regression for the scopes the old literal DID happen to list."""
        authed_page.goto( f"{BASE_URL}/app/docs?path=lupin/CLAUDE.md", wait_until="networkidle" )

        assert any( "/api/docs/file" in c for c in api_calls )
        assert not any( "/api/io/file" in c for c in api_calls )
