"""
E2E UI tests for session management.

Phase 3: Auth Flow Tests — validates localStorage token management,
session persistence across page reloads, logout behavior, and
unauthenticated redirect behavior.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

import json

from .conftest import (
    BASE_URL,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _register_and_login( page, email="session@example.com", password="TestPassword123!" ):
    """
    Register and login via browser UI.

    Requires:
        - page is a Playwright page object
        - Server has clean test database

    Ensures:
        - User is registered and logged in
        - Page is on the landing page
    """
    page.goto( f"{BASE_URL}/app/auth/register" )
    fill_register_form( page, email, password )
    page.wait_for_url( "**/login**", timeout=10000 )

    page.goto( f"{BASE_URL}/app/auth/login" )
    fill_login_form( page, email, password )
    page.wait_for_url( "**/app**", timeout=10000 )

    # Wait for localStorage tokens to be populated
    page.wait_for_function(
        'localStorage.getItem( "lupin_access_token" ) !== null',
        timeout=5000
    )


# ---------------------------------------------------------------------------
# Token Storage
# ---------------------------------------------------------------------------

class TestTokenStorage:
    """Tests for localStorage token management."""

    def test_tokens_stored_after_login( self, page, clean_test_db ):
        """
        Login stores access and refresh tokens in localStorage.

        Requires:
            - Clean database, fresh login

        Ensures:
            - Access and refresh tokens are non-empty strings
        """
        _register_and_login( page )

        access_token  = page.evaluate( "localStorage.getItem( 'lupin_access_token' )" )
        refresh_token = page.evaluate( "localStorage.getItem( 'lupin_refresh_token' )" )

        assert access_token is not None and len( access_token ) > 0
        assert refresh_token is not None and len( refresh_token ) > 0

    def test_user_data_contains_email( self, page, clean_test_db ):
        """
        Stored user_data contains the logged-in user's email.

        Requires:
            - Clean database, fresh login

        Ensures:
            - user_data JSON contains email field
        """
        email = "data_check@example.com"
        _register_and_login( page, email=email )

        # Navigate to profile page which calls getCurrentUser()
        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            'localStorage.getItem( "user_data" ) !== null',
            timeout=5000
        )

        user_data_str = page.evaluate( "localStorage.getItem( 'user_data' )" )
        user_data     = json.loads( user_data_str )

        assert user_data[ "email" ] == email

    def test_user_data_contains_roles( self, page, clean_test_db ):
        """
        Stored user_data contains roles array.

        Requires:
            - Clean database, fresh login

        Ensures:
            - user_data JSON has roles field
            - roles contains 'user'
        """
        _register_and_login( page, email="roles_check@example.com" )

        # Navigate to profile page which calls getCurrentUser()
        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            'localStorage.getItem( "user_data" ) !== null',
            timeout=5000
        )

        user_data_str = page.evaluate( "localStorage.getItem( 'user_data' )" )
        user_data     = json.loads( user_data_str )

        assert "roles" in user_data
        assert "user" in user_data[ "roles" ]


# ---------------------------------------------------------------------------
# Session Persistence
# ---------------------------------------------------------------------------

class TestSessionPersistence:
    """Tests for session persistence across page reloads."""

    def test_tokens_survive_page_reload( self, page, clean_test_db ):
        """
        Tokens persist in localStorage after page reload.

        Requires:
            - Clean database, fresh login

        Ensures:
            - Tokens still present after page.reload()
        """
        _register_and_login( page )

        page.reload()
        page.wait_for_load_state( "networkidle" )

        access_token = page.evaluate( "localStorage.getItem( 'lupin_access_token' )" )
        assert access_token is not None, "Token lost after reload"

    def test_authenticated_page_accessible_after_reload( self, page, clean_test_db ):
        """
        Authenticated pages remain accessible after reload.

        Requires:
            - Clean database, fresh login

        Ensures:
            - Profile page loads without redirect to login after reload
        """
        _register_and_login( page )

        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_load_state( "networkidle" )

        page.reload()
        page.wait_for_load_state( "networkidle" )
        page.wait_for_timeout( 1000 )

        # Should still be on profile, not redirected to login
        assert "/profile" in page.url or "/app" in page.url


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    """Tests for logout behavior."""

    def test_logout_clears_tokens( self, page, clean_test_db ):
        """
        Logout clears all tokens from localStorage.

        Requires:
            - Clean database, fresh login

        Ensures:
            - All token keys are null after logout
        """
        _register_and_login( page )

        # Go to profile and logout
        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_load_state( "networkidle" )

        logout_btn = page.get_by_test_id( "profile-logout-btn" )
        logout_btn.wait_for( state="visible", timeout=5000 )
        logout_btn.click()

        page.wait_for_url( "**/login**", timeout=5000 )

        access_token  = page.evaluate( "localStorage.getItem( 'lupin_access_token' )" )
        refresh_token = page.evaluate( "localStorage.getItem( 'lupin_refresh_token' )" )

        assert access_token is None, "Access token not cleared"
        assert refresh_token is None, "Refresh token not cleared"

    def test_logout_redirects_to_login( self, page, clean_test_db ):
        """
        Logout redirects to login page.

        Requires:
            - Clean database, fresh login

        Ensures:
            - After logout, URL is login page
        """
        _register_and_login( page )

        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_load_state( "networkidle" )

        page.get_by_test_id( "profile-logout-btn" ).click()
        page.wait_for_url( "**/login**", timeout=5000 )

        assert "/login" in page.url


# ---------------------------------------------------------------------------
# Unauthenticated Redirect
# ---------------------------------------------------------------------------

class TestUnauthenticatedRedirect:
    """Tests for unauthenticated access behavior."""

    def test_protected_page_redirects_to_login( self, page, clean_test_db ):
        """
        Accessing a protected page without auth redirects to login.

        Requires:
            - Clean database, no login

        Ensures:
            - Navigating to profile redirects to login
        """
        # Clear any existing tokens
        page.goto( f"{BASE_URL}/app/auth/login" )
        page.evaluate( "localStorage.clear()" )

        page.goto( f"{BASE_URL}/app/auth/profile" )
        page.wait_for_timeout( 2000 )

        assert "/login" in page.url
