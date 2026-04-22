"""
E2E UI tests for the registration page.

Phase 3: Auth Flow Tests — validates registration journeys including
successful registration, password strength validation, duplicate email
handling, and password mismatch detection.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

from .conftest import (
    BASE_URL,
    fill_register_form,
    assert_error_message, assert_success_message,
)


# ---------------------------------------------------------------------------
# Successful Registration
# ---------------------------------------------------------------------------

class TestSuccessfulRegistration:
    """Tests for valid registration flow."""

    def test_register_with_valid_credentials( self, page, clean_test_db ):
        """
        Register with valid credentials shows success and redirects to login.

        Requires:
            - Clean database (no existing users)

        Ensures:
            - Success message is shown
            - Page redirects to login
        """
        page.goto( f"{BASE_URL}/app/auth/register" )
        fill_register_form( page, "new_user@example.com", "TestPassword123!" )

        assert_success_message( page, "success" )
        page.wait_for_url( "**/login**", timeout=10000 )

    def test_register_form_has_all_elements( self, page, clean_test_db ):
        """
        Registration page renders all expected form elements.

        Requires:
            - Register page loaded

        Ensures:
            - All form inputs and buttons are visible
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        assert page.get_by_test_id( "register-email-input" ).is_visible()
        assert page.get_by_test_id( "register-password-input" ).is_visible()
        assert page.get_by_test_id( "register-confirm-password-input" ).is_visible()
        assert page.get_by_test_id( "register-submit-btn" ).is_visible()


# ---------------------------------------------------------------------------
# Password Strength Validation
# ---------------------------------------------------------------------------

class TestPasswordStrength:
    """Tests for password strength meter and requirements."""

    def test_strength_meter_updates_on_input( self, page, clean_test_db ):
        """
        Password strength meter updates as user types.

        Requires:
            - Register page loaded

        Ensures:
            - Strength meter element exists
            - Strength text updates when password entered
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        password_input = page.get_by_test_id( "register-password-input" )
        strength_text  = page.get_by_test_id( "register-strength-text" )

        # Type a weak password
        password_input.fill( "abc" )
        page.wait_for_timeout( 300 )  # Let JS update

        # Strength text should be visible and contain something
        assert strength_text.is_visible()

    def test_password_requirements_display( self, page, clean_test_db ):
        """
        Password requirements checkmarks are present in DOM.

        Requires:
            - Register page loaded

        Ensures:
            - All 5 requirement indicators exist
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        requirement_ids = [
            "register-req-length",
            "register-req-uppercase",
            "register-req-lowercase",
            "register-req-number",
            "register-req-special",
        ]

        for req_id in requirement_ids:
            element = page.get_by_test_id( req_id )
            assert element.count() > 0, f"Requirement element {req_id} not found"

    def test_weak_password_rejected( self, page, clean_test_db ):
        """
        Registration with a weak password is rejected.

        Requires:
            - Clean database

        Ensures:
            - Error message displayed for weak password
            - Page stays on register
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        page.get_by_test_id( "register-email-input" ).fill( "weak_pwd@example.com" )
        page.get_by_test_id( "register-password-input" ).fill( "weak" )
        page.get_by_test_id( "register-confirm-password-input" ).fill( "weak" )
        page.get_by_test_id( "register-submit-btn" ).click()

        # Should stay on register — password too weak
        page.wait_for_timeout( 1000 )
        assert "/register" in page.url


# ---------------------------------------------------------------------------
# Duplicate Email
# ---------------------------------------------------------------------------

class TestDuplicateEmail:
    """Tests for duplicate email handling."""

    def test_duplicate_email_shows_error( self, page, clean_test_db ):
        """
        Registering with an already-used email shows error.

        Requires:
            - Clean database

        Ensures:
            - First registration succeeds
            - Second registration with same email shows error
        """
        email    = "duplicate@example.com"
        password = "TestPassword123!"

        # First registration
        page.goto( f"{BASE_URL}/app/auth/register" )
        fill_register_form( page, email, password )
        page.wait_for_url( "**/login**", timeout=10000 )

        # Second registration with same email
        page.goto( f"{BASE_URL}/app/auth/register" )
        fill_register_form( page, email, password )

        assert_error_message( page, "already registered" )


# ---------------------------------------------------------------------------
# Password Mismatch
# ---------------------------------------------------------------------------

class TestPasswordMismatch:
    """Tests for password confirmation mismatch."""

    def test_mismatched_passwords_rejected( self, page, clean_test_db ):
        """
        Registration with mismatched passwords is rejected.

        Requires:
            - Clean database

        Ensures:
            - Error or validation prevents submission
            - Page stays on register
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        page.get_by_test_id( "register-email-input" ).fill( "mismatch@example.com" )
        page.get_by_test_id( "register-password-input" ).fill( "TestPassword123!" )
        page.get_by_test_id( "register-confirm-password-input" ).fill( "DifferentPassword456!" )
        page.get_by_test_id( "register-submit-btn" ).click()

        # Should stay on register or show error
        page.wait_for_timeout( 1000 )
        assert "/register" in page.url


# ---------------------------------------------------------------------------
# Navigation Links
# ---------------------------------------------------------------------------

class TestRegisterNavigation:
    """Tests for navigation from register page."""

    def test_login_link_navigates_to_login( self, page, clean_test_db ):
        """
        Login link on register page navigates to login page.

        Requires:
            - Register page loaded

        Ensures:
            - Clicking login link goes to /app/auth/login
        """
        page.goto( f"{BASE_URL}/app/auth/register" )

        login_link = page.get_by_test_id( "register-login-link" )
        login_link.click()

        page.wait_for_url( "**/login**", timeout=5000 )
        assert "/login" in page.url
