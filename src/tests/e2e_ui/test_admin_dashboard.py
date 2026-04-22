"""
E2E UI tests for the admin dashboard page.

Phase 5: Admin Flow Tests — validates admin dashboard card rendering,
navigation to sub-pages, email display, and logout behavior.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Dashboard Layout
# ---------------------------------------------------------------------------

class TestAdminDashboardLayout:
    """Tests for admin dashboard page rendering."""

    def test_dashboard_shows_user_email( self, admin_page ):
        """
        Admin dashboard displays the admin user's email.

        Requires:
            - Admin-authenticated session

        Ensures:
            - User email element is visible and contains admin email
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        email_el = admin_page.get_by_test_id( "admin-dash-user-email" )
        email_el.wait_for( state="visible", timeout=5000 )

        assert "e2e_admin@example.com" in email_el.text_content()

    def test_dashboard_shows_all_cards( self, admin_page ):
        """
        Admin dashboard renders all four management cards.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Users, Snapshots, Ratify, and Trust cards are all visible
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        card_ids = [
            "admin-dash-card-users",
            "admin-dash-card-snapshots",
            "admin-dash-card-ratify",
            "admin-dash-card-trust",
        ]

        for card_id in card_ids:
            card = admin_page.get_by_test_id( card_id )
            card.wait_for( state="visible", timeout=5000 )

    def test_dashboard_has_breadcrumb( self, admin_page ):
        """
        Admin dashboard has a home breadcrumb link.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Home breadcrumb is visible
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        breadcrumb = admin_page.get_by_test_id( "admin-dash-breadcrumb-home" )
        assert breadcrumb.count() > 0


# ---------------------------------------------------------------------------
# Dashboard Navigation
# ---------------------------------------------------------------------------

class TestAdminDashboardNavigation:
    """Tests for navigation from admin dashboard cards."""

    def test_users_card_navigates( self, admin_page ):
        """
        Clicking Users card navigates to user management page.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Navigation goes to /app/admin/users
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_page.get_by_test_id( "admin-dash-card-users" ).click()
        admin_page.wait_for_url( "**/users**", timeout=5000 )
        assert "/users" in admin_page.url

    def test_snapshots_card_navigates( self, admin_page ):
        """
        Clicking Snapshots card navigates to snapshots page.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Navigation goes to /app/admin/snapshots
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_page.get_by_test_id( "admin-dash-card-snapshots" ).click()
        admin_page.wait_for_url( "**/snapshots**", timeout=5000 )
        assert "/snapshots" in admin_page.url

    def test_ratify_card_navigates( self, admin_page ):
        """
        Clicking Ratify card navigates to ratification page.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Navigation goes to /app/admin/proxy-ratify
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_page.get_by_test_id( "admin-dash-card-ratify" ).click()
        admin_page.wait_for_url( "**/proxy-ratify**", timeout=5000 )
        assert "/proxy-ratify" in admin_page.url

    def test_trust_card_navigates( self, admin_page ):
        """
        Clicking Trust card navigates to trust dashboard page.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Navigation goes to /app/admin/proxy-dashboard
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_page.get_by_test_id( "admin-dash-card-trust" ).click()
        admin_page.wait_for_url( "**/proxy-dashboard**", timeout=5000 )
        assert "/proxy-dashboard" in admin_page.url


# ---------------------------------------------------------------------------
# Dashboard Logout
# ---------------------------------------------------------------------------

class TestAdminDashboardLogout:
    """Tests for logout from admin dashboard."""

    def test_logout_button_redirects_to_login( self, admin_page ):
        """
        Clicking logout on admin dashboard redirects to login.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Logout clears session and redirects to login
        """
        admin_page.goto( f"{BASE_URL}/app/admin" )
        admin_page.wait_for_load_state( "networkidle" )

        logout_btn = admin_page.get_by_test_id( "admin-dash-logout-btn" )
        logout_btn.wait_for( state="visible", timeout=5000 )
        logout_btn.click()

        admin_page.wait_for_url( "**/login**", timeout=5000 )
        assert "/login" in admin_page.url
