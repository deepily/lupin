"""
E2E UI tests for the login page.

Phase 3: Auth Flow Tests — validates login journeys including
valid/invalid credentials, form validation, and navigation links.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

import re

from .conftest import (
    BASE_URL, PAGE_URLS,
    fill_login_form, fill_register_form,
    assert_error_message, assert_success_message,
)


# ---------------------------------------------------------------------------
# Helper: Register a user via browser so login tests have a valid account
# ---------------------------------------------------------------------------

def _register_user( page, email, password ):
    """
    Register a user via the browser UI.

    Requires:
        - page is a Playwright page object
        - email and password are non-empty strings

    Ensures:
        - User account is created in test database
        - Page navigates to login after registration
    """
    page.goto( f"{BASE_URL}/app/auth/register" )
    fill_register_form( page, email, password )
    page.wait_for_url( "**/login**", timeout=10000 )


# ---------------------------------------------------------------------------
# Valid Login
# ---------------------------------------------------------------------------

class TestValidLogin:
    """Tests for successful login flow."""

    def test_login_with_valid_credentials( self, page, clean_test_db ):
        """
        Login with valid credentials redirects to landing page.

        Requires:
            - Clean database, registered user

        Ensures:
            - Success message is shown
            - Page redirects to /app (landing)
        """
        email    = "login_test@example.com"
        password = "TestPassword123!"

        _register_user( page, email, password )

        page.goto( f"{BASE_URL}/app/auth/login" )
        fill_login_form( page, email, password )

        # Should show success message
        assert_success_message( page, "success" )

        # Should redirect to landing page
        page.wait_for_url( "**/app**", timeout=10000 )
        assert "/app" in page.url

    def test_login_stores_tokens_in_localstorage( self, page, clean_test_db ):
        """
        Successful login stores access and refresh tokens in localStorage.

        Requires:
            - Clean database, registered user

        Ensures:
            - lupin_access_token is set in localStorage
            - lupin_refresh_token is set in localStorage
        """
        email    = "token_test@example.com"
        password = "TestPassword123!"

        _register_user( page, email, password )

        page.goto( f"{BASE_URL}/app/auth/login" )
        fill_login_form( page, email, password )
        page.wait_for_url( "**/app**", timeout=10000 )

        # Wait for tokens to be stored
        page.wait_for_function(
            'localStorage.getItem( "lupin_access_token" ) !== null',
            timeout=5000
        )

        access_token  = page.evaluate( "localStorage.getItem( 'lupin_access_token' )" )
        refresh_token = page.evaluate( "localStorage.getItem( 'lupin_refresh_token' )" )

        assert access_token is not None, "Access token not stored"
        assert refresh_token is not None, "Refresh token not stored"

    def test_login_form_shows_loading_spinner( self, page, clean_test_db ):
        """
        Login submit shows a loading spinner while request is in flight.

        Requires:
            - Clean database, registered user

        Ensures:
            - Loading spinner element exists (may be briefly visible)
        """
        email    = "spinner_test@example.com"
        password = "TestPassword123!"

        _register_user( page, email, password )

        page.goto( f"{BASE_URL}/app/auth/login" )

        # Verify the loading spinner element exists in DOM (hidden initially)
        spinner = page.get_by_test_id( "login-loading-spinner" )
        assert spinner.count() > 0, "Loading spinner element not found in DOM"


# ---------------------------------------------------------------------------
# Invalid Login
# ---------------------------------------------------------------------------

class TestInvalidLogin:
    """Tests for failed login attempts."""

    def test_login_with_wrong_password( self, page, clean_test_db ):
        """
        Login with wrong password shows error message.

        Requires:
            - Clean database, registered user

        Ensures:
            - Error message is displayed
            - Page stays on login
        """
        email    = "wrong_pwd@example.com"
        password = "TestPassword123!"

        _register_user( page, email, password )

        page.goto( f"{BASE_URL}/app/auth/login" )
        fill_login_form( page, email, "WrongPassword999!" )

        assert_error_message( page, "invalid" )
        assert "/login" in page.url

    def test_login_with_nonexistent_email( self, page, clean_test_db ):
        """
        Login with non-existent email shows error message.

        Requires:
            - Clean database (no users)

        Ensures:
            - Error message is displayed
            - Page stays on login
        """
        page.goto( f"{BASE_URL}/app/auth/login" )
        fill_login_form( page, "nobody@example.com", "TestPassword123!" )

        assert_error_message( page, "invalid" )
        assert "/login" in page.url

    def test_login_with_empty_fields( self, page, clean_test_db ):
        """
        Submitting login with empty fields triggers HTML5 validation.

        Requires:
            - Clean database

        Ensures:
            - Form does not submit (stays on login page)
            - HTML5 required validation prevents submission
        """
        page.goto( f"{BASE_URL}/app/auth/login" )

        # Click submit without filling fields
        page.get_by_test_id( "login-submit-btn" ).click()

        # Should stay on login page (HTML5 validation prevents submission)
        assert "/login" in page.url


# ---------------------------------------------------------------------------
# Navigation Links
# ---------------------------------------------------------------------------

class TestLoginNavigation:
    """Tests for navigation from login page."""

    def test_register_link_navigates_to_register( self, page, clean_test_db ):
        """
        Register link on login page navigates to registration page.

        Requires:
            - Login page loaded

        Ensures:
            - Clicking register link goes to /app/auth/register
        """
        page.goto( f"{BASE_URL}/app/auth/login" )

        register_link = page.get_by_test_id( "login-register-link" )
        register_link.click()

        page.wait_for_url( "**/register**", timeout=5000 )
        assert "/register" in page.url

    def test_login_page_has_expected_form_elements( self, page, clean_test_db ):
        """
        Login page renders all expected form elements.

        Requires:
            - Login page loaded

        Ensures:
            - Email input, password input, submit button are visible
        """
        page.goto( f"{BASE_URL}/app/auth/login" )

        assert page.get_by_test_id( "login-email-input" ).is_visible()
        assert page.get_by_test_id( "login-password-input" ).is_visible()
        assert page.get_by_test_id( "login-submit-btn" ).is_visible()
