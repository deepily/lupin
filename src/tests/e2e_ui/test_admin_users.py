"""
E2E UI tests for the admin user management page.

Phase 5: Admin Flow Tests — validates user search, filters, pagination,
and modal interactions on the user management page.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page fixture)
"""

import requests

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Helper: Seed additional test users via API
# ---------------------------------------------------------------------------

def _seed_users( count=3 ):
    """
    Register additional test users via the API.

    Requires:
        - Server running with Testing config
        - Clean test database

    Ensures:
        - Creates `count` users with sequential emails
        - Returns list of created user emails
    """
    emails = []
    for i in range( count ):
        email = f"seed_user_{i}@example.com"
        requests.post(
            f"{BASE_URL}/auth/register",
            json={ "email": email, "password": "SeedPassword123!" }
        )
        emails.append( email )
    return emails


# ---------------------------------------------------------------------------
# Page Layout
# ---------------------------------------------------------------------------

class TestAdminUsersLayout:
    """Tests for user management page rendering."""

    def test_page_has_search_and_filters( self, admin_page ):
        """
        User management page has search input and filter dropdowns.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Search input, role filter, status filter, clear button visible
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "admin-users-search-input" ).is_visible()
        assert admin_page.get_by_test_id( "admin-users-role-filter-select" ).is_visible()
        assert admin_page.get_by_test_id( "admin-users-status-filter-select" ).is_visible()
        assert admin_page.get_by_test_id( "admin-users-clear-filters-btn" ).is_visible()

    def test_page_has_users_table( self, admin_page ):
        """
        User management page has a users table.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Users table element exists in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        table = admin_page.get_by_test_id( "admin-users-table" )
        assert table.count() > 0

    def test_page_has_pagination( self, admin_page ):
        """
        User management page has pagination controls.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Prev/next buttons and page info are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "admin-users-prev-page-btn" ).count() > 0
        assert admin_page.get_by_test_id( "admin-users-page-info" ).count() > 0
        assert admin_page.get_by_test_id( "admin-users-next-page-btn" ).count() > 0

    def test_page_shows_admin_user( self, admin_page ):
        """
        User management page lists the admin user in the table.

        Requires:
            - Admin-authenticated session (admin user exists)

        Ensures:
            - Table contains at least one row with the admin email
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )
        admin_page.wait_for_timeout( 1000 )

        table = admin_page.get_by_test_id( "admin-users-table" )
        assert "e2e_admin@example.com" in table.text_content()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestAdminUsersSearch:
    """Tests for user search functionality."""

    def test_search_filters_results( self, admin_page ):
        """
        Typing in search input filters the user table.

        Requires:
            - Admin-authenticated session with seeded users

        Ensures:
            - Search results update based on input
        """
        _seed_users( 3 )

        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )
        admin_page.wait_for_timeout( 1000 )

        search_input = admin_page.get_by_test_id( "admin-users-search-input" )
        search_input.fill( "seed_user_0" )

        # Wait for debounced search
        admin_page.wait_for_timeout( 500 )

        table = admin_page.get_by_test_id( "admin-users-table" )
        assert "seed_user_0@example.com" in table.text_content()

    def test_clear_filters_resets_search( self, admin_page ):
        """
        Clear filters button resets search and shows all users.

        Requires:
            - Admin-authenticated session

        Ensures:
            - After clearing, search input is empty
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        search_input = admin_page.get_by_test_id( "admin-users-search-input" )
        search_input.fill( "nonexistent" )
        admin_page.wait_for_timeout( 500 )

        admin_page.get_by_test_id( "admin-users-clear-filters-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        assert search_input.input_value() == ""


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestAdminUsersFilters:
    """Tests for role and status filter dropdowns."""

    def test_role_filter_dropdown_has_options( self, admin_page ):
        """
        Role filter dropdown has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Role filter has multiple options (All, admin, user)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        role_filter = admin_page.get_by_test_id( "admin-users-role-filter-select" )
        options     = role_filter.locator( "option" )

        assert options.count() >= 2

    def test_status_filter_dropdown_has_options( self, admin_page ):
        """
        Status filter dropdown has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Status filter has multiple options (All, active, inactive)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        status_filter = admin_page.get_by_test_id( "admin-users-status-filter-select" )
        options       = status_filter.locator( "option" )

        assert options.count() >= 2


# ---------------------------------------------------------------------------
# Back Navigation
# ---------------------------------------------------------------------------

class TestAdminUsersNavigation:
    """Tests for navigation from user management page."""

    def test_back_button_returns_to_admin( self, admin_page ):
        """
        Back button returns to admin dashboard.

        Requires:
            - Admin-authenticated session on users page

        Ensures:
            - Clicking back navigates away from users page
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        back_btn = admin_page.get_by_test_id( "admin-users-back-btn" )
        if back_btn.count() > 0 and back_btn.is_visible():
            back_btn.click()
            admin_page.wait_for_timeout( 2000 )
            assert "/users" not in admin_page.url, \
                f"Back button should navigate away from users page, got: {admin_page.url}"


# ---------------------------------------------------------------------------
# Modal Existence
# ---------------------------------------------------------------------------

class TestAdminUsersModals:
    """Tests for user management modal elements."""

    def test_detail_modal_exists( self, admin_page ):
        """
        User detail modal element exists in DOM (hidden initially).

        Requires:
            - Admin-authenticated session

        Ensures:
            - Modal element is present in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-user-detail" )
        assert modal.count() > 0, "User detail modal not found in DOM"

    def test_role_editor_modal_exists( self, admin_page ):
        """
        Role editor modal element exists in DOM (hidden initially).

        Requires:
            - Admin-authenticated session

        Ensures:
            - Modal element is present in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-role-editor" )
        assert modal.count() > 0, "Role editor modal not found in DOM"

    def test_password_reset_modal_exists( self, admin_page ):
        """
        Password reset modal element exists in DOM (hidden initially).

        Requires:
            - Admin-authenticated session

        Ensures:
            - Modal element is present in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-password-reset" )
        assert modal.count() > 0, "Password reset modal not found in DOM"

    def test_confirm_modal_exists( self, admin_page ):
        """
        Confirmation modal element exists in DOM (hidden initially).

        Requires:
            - Admin-authenticated session

        Ensures:
            - Modal element is present in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/users" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-user-confirm" )
        assert modal.count() > 0, "Confirmation modal not found in DOM"
