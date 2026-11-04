"""
E2E regression: a relative link inside a rendered markdown file opens the file it names.

WHATS-NEW.md links the rewrite plan as a repo-relative path, which is right on GitHub.
The viewer left that href alone. The browser resolved it against `/app/` and opened
`/app/src/rnd/...`, a 404, although the file exists.

This test clicks that exact link in a real browser and asserts where it lands.
Only the href the page hands the browser is wrong. The file, the API and the markdown are fine.

Venue: :8000 per the E2E-UI bucket (see CLAUDE.md, Testing venues).
"""

import json
import os
import re

import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

WHATS_NEW_PATH = "lupin/WHATS-NEW.md"
LINK_TEXT      = "documentation rewrite plan"
PLAN_REL       = "src/rnd/v0.2.2/2026.09.30-lupin-af-documentation-rewrite-plan/2026.09.30-lupin-af-documentation-rewrite-plan.md"
PLAN_NAME      = PLAN_REL.rsplit( "/", 1 )[ -1 ]


@pytest.fixture
def authed_page( page, context ):
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( tokens[ 'access_token' ] ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( tokens[ 'refresh_token' ] ) });"
    )
    return page


class TestDocViewerRelativeLinkResolves:

    def test_whats_new_plan_link_points_into_the_viewer( self, authed_page ):
        """The rendered href is the viewer URL for the plan, not the bare repo-relative path."""
        authed_page.goto( f"{BASE_URL}/app/docs?path={WHATS_NEW_PATH}", wait_until="networkidle" )
        link = authed_page.locator( "#doc-viewer-target a", has_text=LINK_TEXT ).first
        link.wait_for( timeout=10_000 )
        authed_page.wait_for_function(
            "( t ) => document.querySelector( '#doc-viewer-target a' ) && "
            "[ ...document.querySelectorAll( '#doc-viewer-target a' ) ].some( a => a.textContent.includes( t ) && "
            "a.getAttribute( 'href' ).startsWith( '/app/docs?path=' ) )",
            arg     = LINK_TEXT,
            timeout = 10_000,
        )
        assert link.get_attribute( "href" ) == f"/app/docs?path=lupin/{PLAN_REL}"

    def test_clicking_the_whats_new_plan_link_lands_on_the_plan( self, authed_page ):
        """The acceptance criterion: click the link, land on the plan, rendered, no 404."""
        authed_page.goto( f"{BASE_URL}/app/docs?path={WHATS_NEW_PATH}", wait_until="networkidle" )
        link = authed_page.locator( "#doc-viewer-target a", has_text=LINK_TEXT ).first
        link.wait_for( timeout=10_000 )
        authed_page.wait_for_function(
            "() => [ ...document.querySelectorAll( '#doc-viewer-target a' ) ].some( a => ( a.getAttribute( 'href' ) || '' ).startsWith( '/app/docs?path=' ) && a.textContent.includes( 'documentation rewrite plan' ) )",
            timeout = 10_000,
        )
        link.click()
        authed_page.wait_for_url( re.compile( r"/app/docs\?path=" ), timeout=10_000 )
        authed_page.wait_for_function( "() => document.querySelector( '#doc-viewer-target.doc-viewer-content' ) !== null", timeout=10_000 )

        assert "/app/src/" not in authed_page.url, f"landed on the broken URL: { authed_page.url }"
        assert PLAN_NAME in authed_page.title(), f"title was { authed_page.title()!r}"
        assert authed_page.query_selector_all( ".doc-viewer-error" ) == []
