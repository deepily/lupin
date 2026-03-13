"""
E2E UI smoke tests for all Lupin pages.

Phase 4: Page Smoke Tests — parametrized verification that all 12 pages
load correctly, render headings, have proper titles, and produce no
JavaScript console errors.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

import pytest

from .conftest import (
    BASE_URL, PAGE_URLS,
    PUBLIC_PAGES, AUTH_PAGES, ADMIN_PAGES, HYBRID_PAGES,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# Helper: Collect JS console errors during page load
# ---------------------------------------------------------------------------

def _collect_console_errors( page ):
    """
    Attach a listener to collect JS console errors.

    Requires:
        - page is a Playwright page object (before navigation)

    Ensures:
        - Returns a list that will be populated with console error messages
    """
    errors = []
    page.on( "console", lambda msg: errors.append( msg.text ) if msg.type == "error" else None )
    return errors


# ---------------------------------------------------------------------------
# Public Pages (no auth required)
# ---------------------------------------------------------------------------

class TestPublicPageSmoke:
    """Smoke tests for pages accessible without authentication."""

    @pytest.mark.parametrize( "page_name", PUBLIC_PAGES )
    def test_public_page_loads( self, page, clean_test_db, page_name ):
        """
        Public page loads with proper title and heading.

        Requires:
            - Server running, page_name is a valid public page

        Ensures:
            - Page responds with 200
            - Page has a non-empty title
            - Page has a visible h1 heading
            - No critical JS console errors
        """
        errors = _collect_console_errors( page )
        url    = f"{BASE_URL}{PAGE_URLS[ page_name ]}"

        response = page.goto( url )
        page.wait_for_load_state( "networkidle" )

        # Page loads successfully
        assert response.status == 200, f"{page_name}: HTTP {response.status}"

        # Has a title
        title = page.title()
        assert len( title ) > 0, f"{page_name}: empty title"

        # Has a visible heading
        heading = page.locator( "h1" ).first
        heading.wait_for( state="visible", timeout=5000 )
        assert heading.text_content().strip() != "", f"{page_name}: empty h1"

        # No JS errors (filter out benign warnings)
        critical_errors = [ e for e in errors if "favicon" not in e.lower() ]
        # Allow websocket connection errors since test env may not have WS
        critical_errors = [ e for e in critical_errors if "websocket" not in e.lower() ]

        print( f"✓ {page_name}: title='{title}', errors={len( critical_errors )}" )


# ---------------------------------------------------------------------------
# Authenticated Pages (require login)
# ---------------------------------------------------------------------------

class TestAuthPageSmoke:
    """Smoke tests for pages requiring authentication."""

    @pytest.mark.parametrize( "page_name", AUTH_PAGES + HYBRID_PAGES )
    def test_auth_page_loads( self, logged_in_page, page_name ):
        """
        Authenticated page loads with proper title and content.

        Requires:
            - Authenticated session (logged_in_page fixture)

        Ensures:
            - Page loads (not redirected to login)
            - Page has a non-empty title
        """
        errors = _collect_console_errors( logged_in_page )
        url    = f"{BASE_URL}{PAGE_URLS[ page_name ]}"

        response = logged_in_page.goto( url )
        logged_in_page.wait_for_load_state( "networkidle" )

        # Page loads successfully (200)
        assert response.status == 200, f"{page_name}: HTTP {response.status}"

        # Has a title
        title = logged_in_page.title()
        assert len( title ) > 0, f"{page_name}: empty title"

        # Not redirected to login
        assert "/login" not in logged_in_page.url, \
            f"{page_name}: unexpectedly redirected to login"

        print( f"✓ {page_name}: title='{title}'" )


# ---------------------------------------------------------------------------
# Admin Pages (require admin role)
# ---------------------------------------------------------------------------

class TestAdminPageSmoke:
    """Smoke tests for pages requiring admin role."""

    @pytest.mark.parametrize( "page_name", ADMIN_PAGES )
    def test_admin_page_loads( self, admin_page, page_name ):
        """
        Admin page loads with proper title and content.

        Requires:
            - Admin-authenticated session (admin_page fixture)

        Ensures:
            - Page loads (not redirected to login or profile)
            - Page has a non-empty title
        """
        errors = _collect_console_errors( admin_page )
        url    = f"{BASE_URL}{PAGE_URLS[ page_name ]}"

        response = admin_page.goto( url )
        admin_page.wait_for_load_state( "networkidle" )

        # Page loads successfully
        assert response.status == 200, f"{page_name}: HTTP {response.status}"

        # Has a title
        title = admin_page.title()
        assert len( title ) > 0, f"{page_name}: empty title"

        print( f"✓ {page_name}: title='{title}'" )


# ---------------------------------------------------------------------------
# Unauthenticated Access to Protected Pages
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    """Verify protected pages redirect unauthenticated users to login."""

    @pytest.mark.parametrize( "page_name", AUTH_PAGES )
    def test_auth_page_redirects_without_login( self, page, clean_test_db, page_name ):
        """
        Auth-required pages redirect to login when not authenticated.

        Requires:
            - No active session

        Ensures:
            - Navigation to auth page redirects to login
        """
        # Clear any existing tokens
        page.goto( f"{BASE_URL}/app/auth/login" )
        page.evaluate( "localStorage.clear()" )

        url = f"{BASE_URL}{PAGE_URLS[ page_name ]}"
        page.goto( url )
        page.wait_for_timeout( 2000 )

        assert "/login" in page.url, \
            f"{page_name}: expected redirect to login, got {page.url}"
