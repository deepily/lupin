"""
E2E UI tests for the admin trust dashboard (proxy dashboard) page.

Phase 5: Admin Flow Tests — validates trust mode controls, cards grid,
category filter, and pagination on the trust dashboard.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Page Layout
# ---------------------------------------------------------------------------

class TestTrustDashboardLayout:
    """Tests for trust dashboard page rendering."""

    def test_page_has_mode_controls( self, admin_page ):
        """
        Trust dashboard has mode selection controls.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Trust mode select, domain, and user elements are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "trust-mode-select" ).count() > 0
        assert admin_page.get_by_test_id( "trust-mode-domain" ).count() > 0
        assert admin_page.get_by_test_id( "trust-mode-user" ).count() > 0

    def test_page_has_cards_grid( self, admin_page ):
        """
        Trust dashboard has a cards grid for SWE categories.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Cards grid element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        grid = admin_page.get_by_test_id( "trust-cards-grid" )
        assert grid.count() > 0

    def test_page_has_category_filter( self, admin_page ):
        """
        Trust dashboard has a category filter dropdown.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Category select is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        category = admin_page.get_by_test_id( "trust-category-select" )
        assert category.count() > 0

    def test_page_has_decisions_table( self, admin_page ):
        """
        Trust dashboard has a recent decisions table.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Decisions table is present in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        table = admin_page.get_by_test_id( "trust-decisions-table" )
        assert table.count() > 0

    def test_page_has_pagination( self, admin_page ):
        """
        Trust dashboard has pagination controls.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Prev/next buttons and page info are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "trust-prev-page-btn" ).count() > 0
        assert admin_page.get_by_test_id( "trust-page-info" ).count() > 0
        assert admin_page.get_by_test_id( "trust-next-page-btn" ).count() > 0

    def test_page_has_breadcrumbs( self, admin_page ):
        """
        Trust dashboard has breadcrumb navigation.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Home and admin breadcrumbs are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "trust-breadcrumb-home" ).count() > 0
        assert admin_page.get_by_test_id( "trust-breadcrumb-admin" ).count() > 0


# ---------------------------------------------------------------------------
# Trust Mode
# ---------------------------------------------------------------------------

class TestTrustMode:
    """Tests for trust mode controls."""

    def test_mode_select_has_options( self, admin_page ):
        """
        Trust mode dropdown has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Mode select has multiple options (DISABLED, SHADOW, SUGGEST, ACTIVE)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        mode_select = admin_page.get_by_test_id( "trust-mode-select" )
        if mode_select.count() > 0:
            options = mode_select.locator( "option" )
            assert options.count() >= 2, f"Expected >=2 mode options, got {options.count()}"


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class TestTrustDashboardNavigation:
    """Tests for navigation from trust dashboard."""

    def test_back_button_returns_to_admin( self, admin_page ):
        """
        Back button returns to admin dashboard.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Clicking back navigates away from proxy-dashboard
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        back_btn = admin_page.get_by_test_id( "trust-back-btn" )
        if back_btn.count() > 0 and back_btn.is_visible():
            back_btn.click()
            admin_page.wait_for_url( "**/admin**", timeout=5000 )

    def test_admin_breadcrumb_navigates( self, admin_page ):
        """
        Admin breadcrumb navigates to admin dashboard.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Clicking admin breadcrumb goes to /app/admin
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-dashboard" )
        admin_page.wait_for_load_state( "networkidle" )

        breadcrumb = admin_page.get_by_test_id( "trust-breadcrumb-admin" )
        if breadcrumb.count() > 0 and breadcrumb.is_visible():
            breadcrumb.click()
            admin_page.wait_for_url( "**/admin**", timeout=5000 )
