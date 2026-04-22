"""
E2E UI tests for admin role gating.

Phase 5: Admin Flow Tests — validates that non-admin users are blocked
from all admin pages and redirected appropriately.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

import pytest

from .conftest import BASE_URL, ADMIN_PAGES, PAGE_URLS


# ---------------------------------------------------------------------------
# Non-Admin Blocked from Admin Pages
# ---------------------------------------------------------------------------

class TestRoleGating:
    """Tests that regular users cannot access admin pages."""

    @pytest.mark.parametrize( "page_name", ADMIN_PAGES )
    def test_non_admin_blocked_from_admin_page( self, logged_in_page, page_name ):
        """
        Regular user is redirected away from admin pages.

        Requires:
            - Authenticated as regular user (no admin role)

        Ensures:
            - Navigating to admin page redirects to profile or login
            - User does not remain on admin page
        """
        url = f"{BASE_URL}{PAGE_URLS[ page_name ]}"
        logged_in_page.goto( url )
        logged_in_page.wait_for_timeout( 2000 )

        # Should be redirected away from the admin page
        # requireAdmin() redirects to profile with alert, or login
        current_url = logged_in_page.url
        assert page_name not in current_url or "/login" in current_url or "/profile" in current_url, \
            f"Regular user should not remain on {page_name}, got: {current_url}"


# ---------------------------------------------------------------------------
# Unauthenticated Blocked from Admin Pages
# ---------------------------------------------------------------------------

class TestUnauthenticatedAdminAccess:
    """Tests that unauthenticated users cannot access admin pages."""

    @pytest.mark.parametrize( "page_name", ADMIN_PAGES )
    def test_unauthenticated_blocked_from_admin_page( self, page, clean_test_db, page_name ):
        """
        Unauthenticated user is redirected to login from admin pages.

        Requires:
            - No active session

        Ensures:
            - Navigating to admin page redirects to login
        """
        # Clear any existing tokens
        page.goto( f"{BASE_URL}/app/auth/login" )
        page.evaluate( "localStorage.clear()" )

        url = f"{BASE_URL}{PAGE_URLS[ page_name ]}"
        page.goto( url )
        page.wait_for_timeout( 2000 )

        assert "/login" in page.url, \
            f"Unauthenticated user should be redirected to login from {page_name}, got: {page.url}"
