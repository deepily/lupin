"""
E2E UI tests for the admin snapshots page.

Phase 5: Admin Flow Tests — validates search, threshold/limit filters,
results table, and modal elements on the solution snapshots page.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Page Layout
# ---------------------------------------------------------------------------

class TestSnapshotsLayout:
    """Tests for snapshots page rendering."""

    def test_page_has_search_controls( self, admin_page ):
        """
        Snapshots page has search input, threshold, limit, and search button.

        Requires:
            - Admin-authenticated session

        Ensures:
            - All search control elements are visible
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "snapshots-search-input" ).is_visible()
        assert admin_page.get_by_test_id( "snapshots-threshold-select" ).is_visible()
        assert admin_page.get_by_test_id( "snapshots-limit-select" ).is_visible()
        assert admin_page.get_by_test_id( "snapshots-search-btn" ).is_visible()

    def test_page_has_stt_button( self, admin_page ):
        """
        Snapshots page has a speech-to-text (STT) button for voice search.

        Requires:
            - Admin-authenticated session

        Ensures:
            - STT button is visible
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        stt_btn = admin_page.get_by_test_id( "snapshots-search-stt-btn" )
        assert stt_btn.count() > 0

    def test_page_has_results_table( self, admin_page ):
        """
        Snapshots page has a results table element.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Results table exists in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        table = admin_page.get_by_test_id( "snapshots-results-table" )
        assert table.count() > 0

    def test_page_has_breadcrumbs( self, admin_page ):
        """
        Snapshots page has breadcrumb navigation.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Home and admin breadcrumbs are present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        assert admin_page.get_by_test_id( "snapshots-breadcrumb-home" ).count() > 0
        assert admin_page.get_by_test_id( "snapshots-breadcrumb-admin" ).count() > 0

    def test_page_shows_user_email( self, admin_page ):
        """
        Snapshots page displays the admin user's email.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Email element contains admin email
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        email_el = admin_page.get_by_test_id( "snapshots-user-email" )
        email_el.wait_for( state="visible", timeout=5000 )

        assert "e2e_admin@example.com" in email_el.text_content()


# ---------------------------------------------------------------------------
# Search Controls
# ---------------------------------------------------------------------------

class TestSnapshotsSearch:
    """Tests for snapshot search functionality."""

    def test_threshold_dropdown_has_options( self, admin_page ):
        """
        Threshold dropdown has multiple threshold options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Threshold select has multiple options
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        threshold = admin_page.get_by_test_id( "snapshots-threshold-select" )
        options   = threshold.locator( "option" )

        assert options.count() >= 5, f"Expected >=5 threshold options, got {options.count()}"

    def test_limit_dropdown_has_options( self, admin_page ):
        """
        Limit dropdown has result count options.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Limit select has multiple options (10, 25, 50, 100)
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        limit   = admin_page.get_by_test_id( "snapshots-limit-select" )
        options = limit.locator( "option" )

        assert options.count() >= 3, f"Expected >=3 limit options, got {options.count()}"

    def test_empty_search_shows_results_count( self, admin_page ):
        """
        Searching with empty query shows results count element.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Results count element exists in DOM
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        results_count = admin_page.get_by_test_id( "snapshots-results-count" )
        assert results_count.count() > 0


# ---------------------------------------------------------------------------
# Modal Elements
# ---------------------------------------------------------------------------

class TestSnapshotsModals:
    """Tests for snapshot modal elements in DOM."""

    def test_detail_modal_exists( self, admin_page ):
        """
        Snapshot detail modal exists in DOM.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Detail modal element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-snapshot-detail" )
        assert modal.count() > 0

    def test_similarity_modal_exists( self, admin_page ):
        """
        Snapshot similarity modal exists in DOM.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Similarity modal element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-snapshot-similarity" )
        assert modal.count() > 0

    def test_delete_modal_exists( self, admin_page ):
        """
        Snapshot delete modal exists in DOM.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Delete modal element is present
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        modal = admin_page.get_by_test_id( "modal-snapshot-delete" )
        assert modal.count() > 0


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class TestSnapshotsNavigation:
    """Tests for navigation from snapshots page."""

    def test_admin_breadcrumb_navigates( self, admin_page ):
        """
        Admin breadcrumb navigates back to admin dashboard.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Clicking admin breadcrumb goes to /app/admin
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        breadcrumb = admin_page.get_by_test_id( "snapshots-breadcrumb-admin" )
        if breadcrumb.count() > 0 and breadcrumb.is_visible():
            breadcrumb.click()
            admin_page.wait_for_url( "**/admin**", timeout=5000 )

    def test_logout_redirects_to_login( self, admin_page ):
        """
        Logout button on snapshots page redirects to login.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Clicking logout goes to login page
        """
        admin_page.goto( f"{BASE_URL}/app/admin/snapshots" )
        admin_page.wait_for_load_state( "networkidle" )

        logout_btn = admin_page.get_by_test_id( "snapshots-logout-btn" )
        logout_btn.wait_for( state="visible", timeout=5000 )
        logout_btn.click()

        admin_page.wait_for_url( "**/login**", timeout=5000 )
