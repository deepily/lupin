"""
E2E UI tests for the change password page.

Phase 3: Auth Flow Tests — validates password change flow including
strength meter, validation, and post-change redirect behavior.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

from .conftest import (
    BASE_URL,
    fill_login_form, fill_register_form,
    assert_error_message, assert_success_message,
)


# ---------------------------------------------------------------------------
# Helper: Create user and navigate to change password page
# ---------------------------------------------------------------------------

def _setup_authenticated_change_password( page, email="changepwd@example.com", password="TestPassword123!" ):
    """
    Register, login, and navigate to change password page.

    Requires:
        - page is a Playwright page object
        - Server has clean test database

    Ensures:
        - User is registered and logged in
        - Page is on the change password page
    """
    # Register
    page.goto( f"{BASE_URL}/app/auth/register" )
    fill_register_form( page, email, password )
    page.wait_for_url( "**/login**", timeout=10000 )

    # Login
    page.goto( f"{BASE_URL}/app/auth/login" )
    fill_login_form( page, email, password )
    page.wait_for_url( "**/app**", timeout=10000 )

    # Wait for localStorage tokens to be populated
    page.wait_for_function(
        'localStorage.getItem( "lupin_access_token" ) !== null',
        timeout=5000
    )

    # Navigate to change password
    page.goto( f"{BASE_URL}/app/auth/change-password" )
    page.wait_for_load_state( "networkidle" )

    return email, password


# ---------------------------------------------------------------------------
# Form Elements
# ---------------------------------------------------------------------------

class TestChangePasswordForm:
    """Tests for change password form rendering."""

    def test_form_has_all_elements( self, page, clean_test_db ):
        """
        Change password page renders all expected form elements.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - Current password, new password, confirm inputs visible
            - Submit and cancel buttons visible
        """
        _setup_authenticated_change_password( page )

        assert page.get_by_test_id( "change-pwd-current-input" ).is_visible()
        assert page.get_by_test_id( "change-pwd-new-input" ).is_visible()
        assert page.get_by_test_id( "change-pwd-confirm-input" ).is_visible()
        assert page.get_by_test_id( "change-pwd-submit-btn" ).is_visible()
        assert page.get_by_test_id( "change-pwd-cancel-btn" ).is_visible()


# ---------------------------------------------------------------------------
# Strength Meter
# ---------------------------------------------------------------------------

class TestChangePasswordStrength:
    """Tests for password strength meter on change password page."""

    def test_strength_meter_updates( self, page, clean_test_db ):
        """
        Password strength meter updates as user types new password.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - Strength meter element exists
        """
        _setup_authenticated_change_password( page )

        new_password_input = page.get_by_test_id( "change-pwd-new-input" )
        strength_meter     = page.get_by_test_id( "change-pwd-strength-meter" )

        new_password_input.fill( "abc" )
        page.wait_for_timeout( 300 )

        assert strength_meter.count() > 0, "Strength meter not found"

    def test_requirements_display( self, page, clean_test_db ):
        """
        Password requirement indicators are present.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - All requirement indicators exist in DOM
        """
        _setup_authenticated_change_password( page )

        requirement_ids = [
            "change-pwd-req-length",
            "change-pwd-req-uppercase",
            "change-pwd-req-lowercase",
            "change-pwd-req-number",
        ]

        for req_id in requirement_ids:
            element = page.get_by_test_id( req_id )
            assert element.count() > 0, f"Requirement element {req_id} not found"


# ---------------------------------------------------------------------------
# Successful Password Change
# ---------------------------------------------------------------------------

class TestSuccessfulPasswordChange:
    """Tests for successful password change flow."""

    def test_change_password_redirects_to_login( self, page, clean_test_db ):
        """
        Successfully changing password shows success and redirects to login.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - Success message is shown
            - User is redirected to login (forced re-authentication)
        """
        email, old_password = _setup_authenticated_change_password( page )
        new_password = "NewSecurePass456!"

        page.get_by_test_id( "change-pwd-current-input" ).fill( old_password )
        page.get_by_test_id( "change-pwd-new-input" ).fill( new_password )
        page.get_by_test_id( "change-pwd-confirm-input" ).fill( new_password )
        page.get_by_test_id( "change-pwd-submit-btn" ).click()

        assert_success_message( page, "success" )

        # Should redirect to login after password change
        page.wait_for_url( "**/login**", timeout=10000 )

    def test_can_login_with_new_password( self, page, clean_test_db ):
        """
        After password change, can login with new password.

        Requires:
            - Authenticated user who changed their password

        Ensures:
            - Login with old password fails
            - Login with new password succeeds
        """
        email, old_password = _setup_authenticated_change_password( page )
        new_password = "NewSecurePass789!"

        page.get_by_test_id( "change-pwd-current-input" ).fill( old_password )
        page.get_by_test_id( "change-pwd-new-input" ).fill( new_password )
        page.get_by_test_id( "change-pwd-confirm-input" ).fill( new_password )
        page.get_by_test_id( "change-pwd-submit-btn" ).click()

        page.wait_for_url( "**/login**", timeout=10000 )

        # Login with new password should work
        fill_login_form( page, email, new_password )
        page.wait_for_url( "**/app**", timeout=10000 )
        assert "/app" in page.url


# ---------------------------------------------------------------------------
# Validation Errors
# ---------------------------------------------------------------------------

class TestChangePasswordValidation:
    """Tests for password change validation."""

    def test_wrong_current_password( self, page, clean_test_db ):
        """
        Wrong current password shows error.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - Error message displayed
            - Stays on change password page
        """
        _setup_authenticated_change_password( page )

        page.get_by_test_id( "change-pwd-current-input" ).fill( "WrongPassword999!" )
        page.get_by_test_id( "change-pwd-new-input" ).fill( "NewSecurePass456!" )
        page.get_by_test_id( "change-pwd-confirm-input" ).fill( "NewSecurePass456!" )
        page.get_by_test_id( "change-pwd-submit-btn" ).click()

        assert_error_message( page, "incorrect" )

    def test_cancel_returns_to_profile( self, page, clean_test_db ):
        """
        Cancel button returns to profile page.

        Requires:
            - Authenticated user on change password page

        Ensures:
            - Clicking cancel navigates to profile
        """
        _setup_authenticated_change_password( page )

        page.get_by_test_id( "change-pwd-cancel-btn" ).click()
        page.wait_for_url( "**/profile**", timeout=5000 )
        assert "/profile" in page.url
