"""
E2E UI tests for the profile page.

Phase 3: Auth Flow Tests — validates profile page displays user info
correctly, shows admin section for admins, and provides proper navigation.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Profile Display
# ---------------------------------------------------------------------------

class TestProfileDisplay:
    """Tests for profile page data display."""

    def test_profile_shows_user_email( self, logged_in_page ):
        """
        Profile page displays the logged-in user's email.

        Requires:
            - Authenticated page (logged_in_page fixture)

        Ensures:
            - User email is visible on profile page
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        email_element = logged_in_page.get_by_test_id( "profile-user-email" )
        email_element.wait_for( state="visible", timeout=5000 )

        email_text = email_element.text_content()
        assert "e2e_test@example.com" in email_text

    def test_profile_shows_user_id( self, logged_in_page ):
        """
        Profile page displays the user ID.

        Requires:
            - Authenticated page

        Ensures:
            - User ID element is visible and non-empty
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        user_id = logged_in_page.get_by_test_id( "profile-user-id" )
        user_id.wait_for( state="visible", timeout=5000 )

        assert user_id.text_content().strip() != ""

    def test_profile_shows_user_roles( self, logged_in_page ):
        """
        Profile page displays user roles.

        Requires:
            - Authenticated page

        Ensures:
            - Roles element is visible
            - Contains 'user' role
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        roles = logged_in_page.get_by_test_id( "profile-user-roles" )
        roles.wait_for( state="visible", timeout=5000 )

        assert "user" in roles.text_content().lower()

    def test_profile_shows_account_status( self, logged_in_page ):
        """
        Profile page displays account status.

        Requires:
            - Authenticated page

        Ensures:
            - Account status element is visible
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        status = logged_in_page.get_by_test_id( "profile-account-status" )
        status.wait_for( state="visible", timeout=5000 )

        assert status.text_content().strip() != ""


# ---------------------------------------------------------------------------
# Admin Section Visibility
# ---------------------------------------------------------------------------

class TestProfileAdminSection:
    """Tests for admin-only section visibility."""

    def test_regular_user_does_not_see_admin_section( self, logged_in_page ):
        """
        Regular user does not see admin section on profile page.

        Requires:
            - Authenticated as regular user (no admin role)

        Ensures:
            - Admin section is hidden or not visible
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )
        logged_in_page.wait_for_timeout( 1000 )

        admin_section = logged_in_page.get_by_test_id( "profile-admin-section" )

        # Admin section should be hidden for regular users
        assert not admin_section.is_visible()

    def test_admin_user_sees_admin_section( self, admin_page ):
        """
        Admin user sees admin section with management links.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Admin section is visible
            - Admin navigation buttons are visible
        """
        admin_page.goto( f"{BASE_URL}/app/auth/profile" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_section = admin_page.get_by_test_id( "profile-admin-section" )
        admin_section.wait_for( state="visible", timeout=5000 )

        assert admin_page.get_by_test_id( "profile-admin-dashboard-btn" ).is_visible()
        assert admin_page.get_by_test_id( "profile-admin-users-btn" ).is_visible()
        assert admin_page.get_by_test_id( "profile-admin-snapshots-btn" ).is_visible()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class TestProfileNavigation:
    """Tests for profile page navigation actions."""

    def test_change_password_button( self, logged_in_page ):
        """
        Change password button navigates to change password page.

        Requires:
            - Authenticated page on profile

        Ensures:
            - Clicking change password navigates to /app/auth/change-password
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        change_pwd_btn = logged_in_page.get_by_test_id( "profile-change-pwd-btn" )
        change_pwd_btn.wait_for( state="visible", timeout=5000 )
        change_pwd_btn.click()

        logged_in_page.wait_for_url( "**/change-password**", timeout=5000 )
        assert "/change-password" in logged_in_page.url

    def test_logout_button_clears_session( self, logged_in_page ):
        """
        Logout button clears tokens and redirects to login.

        Requires:
            - Authenticated page on profile

        Ensures:
            - Clicking logout redirects to login page
            - Tokens are cleared from localStorage
        """
        logged_in_page.goto( f"{BASE_URL}/app/auth/profile" )
        logged_in_page.wait_for_load_state( "networkidle" )

        logout_btn = logged_in_page.get_by_test_id( "profile-logout-btn" )
        logout_btn.wait_for( state="visible", timeout=5000 )
        logout_btn.click()

        logged_in_page.wait_for_url( "**/login**", timeout=5000 )

        access_token = logged_in_page.evaluate( "localStorage.getItem( 'lupin_access_token' )" )
        assert access_token is None, "Access token should be cleared after logout"
