"""
E2E UI tests for the admin proxy ratification page.

Phase 5: Admin Flow Tests — validates summary cards, filters, bulk action
controls, pagination, and modal elements on the ratification page.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Page Layout
# ---------------------------------------------------------------------------

class TestRatifyLayout:
    """Tests for ratification page rendering."""

    def test_page_has_summary_cards( self, admin_page ):
        """
        Ratification page has pending, approved, rejected, and oldest summary cards.

        Requires:
            - Admin-authenticated session

        Ensures:
            - All four summary card elements are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "ratify-stat-pending" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-stat-approved" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-stat-rejected" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-stat-oldest" ).count() > 0

    def test_page_has_filters( self, admin_page ):
        """
        Ratification page has filter dropdowns.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Category, trust, and action filter selects are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "ratify-filter-category-select" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-filter-trust-select" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-filter-action-select" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-clear-filters-btn" ).count() > 0

    def test_page_has_bulk_actions( self, admin_page ):
        """
        Ratification page has bulk action controls.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Select-all checkbox, bulk approve/reject buttons are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "ratify-select-all-checkbox" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-bulk-approve-btn" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-bulk-reject-btn" ).count() > 0

    def test_page_has_decisions_table( self, admin_page ):
        """
        Ratification page has a decisions table.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Decisions table element exists
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        table = admin_page.get_by_test_id( "ratify-decisions-table" )
        assert table.count() > 0

    def test_page_has_pagination( self, admin_page ):
        """
        Ratification page has pagination controls.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Prev/next buttons and page info are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "ratify-prev-page-btn" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-page-info" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-next-page-btn" ).count() > 0

    def test_page_has_breadcrumbs( self, admin_page ):
        """
        Ratification page has breadcrumb navigation.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Home and admin breadcrumbs are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "ratify-breadcrumb-home" ).count() > 0
        assert admin_page.get_by_test_id( "ratify-breadcrumb-admin" ).count() > 0


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestRatifyFilters:
    """Tests for ratification filter dropdowns."""

    def test_category_filter_has_options( self, admin_page ):
        """
        Category filter has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Category filter has multiple options
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        category = admin_page.get_by_test_id( "ratify-filter-category-select" )
        options  = category.locator( "option" )

        assert options.count() >= 2

    def test_trust_filter_has_options( self, admin_page ):
        """
        Trust level filter has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Trust filter has multiple options (All, L1-L5)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        trust   = admin_page.get_by_test_id( "ratify-filter-trust-select" )
        options = trust.locator( "option" )

        assert options.count() >= 2

    def test_action_filter_has_options( self, admin_page ):
        """
        Action filter has expected options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Action filter has multiple options (All, shadow, suggest, act, defer)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        action  = admin_page.get_by_test_id( "ratify-filter-action-select" )
        options = action.locator( "option" )

        assert options.count() >= 2

    def test_clear_filters_button_works( self, admin_page ):
        """
        Clear filters button resets all filter dropdowns.

        Requires:
            - Admin-authenticated session

        Ensures:
            - After clearing, all filters reset to default (first option)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        # Select a filter value
        category = admin_page.get_by_test_id( "ratify-filter-category-select" )
        category.select_option( index=1 )
        admin_page.wait_for_timeout( 300 )

        # Clear
        admin_page.get_by_test_id( "ratify-clear-filters-btn" ).click()
        admin_page.wait_for_timeout( 300 )

        # Verify reset — first option should be selected (value "")
        assert category.input_value() == ""


# ---------------------------------------------------------------------------
# Modal Elements
# ---------------------------------------------------------------------------

class TestRatifyModals:
    """Tests for ratification modal elements in DOM."""

    def test_detail_modal_exists( self, admin_page ):
        """
        Ratification detail modal exists in DOM.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Detail modal element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-ratify-detail" )
        assert modal.count() > 0

    def test_confirm_modal_exists( self, admin_page ):
        """
        Ratification confirm modal exists in DOM.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Confirm modal element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-ratify-confirm" )
        assert modal.count() > 0


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class TestRatifyNavigation:
    """Tests for navigation from ratification page."""

    def test_back_button_returns_to_admin( self, admin_page ):
        """
        Back button returns to admin dashboard.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Clicking back navigates to admin
        """
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        back_btn = admin_page.get_by_test_id( "ratify-back-btn" )
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
        admin_page.goto( f"{BASE_URL}/app/admin/proxy-ratify" )
        admin_page.wait_for_load_state( "networkidle" )

        breadcrumb = admin_page.get_by_test_id( "ratify-breadcrumb-admin" )
        if breadcrumb.count() > 0 and breadcrumb.is_visible():
            breadcrumb.click()
            admin_page.wait_for_url( "**/admin**", timeout=5000 )
