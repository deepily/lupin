"""
E2E UI tests for Job History section on the notifications page.

CJ Flow Persistence Phase 6: Validates the 5th collapsible "Job History"
section with time window dropdown, expand/collapse, and count badge.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Job History Section Present
# ---------------------------------------------------------------------------

class TestJobHistorySectionLayout:
    """Tests for Job History section rendering on notifications page."""

    def test_history_section_present( self, logged_in_page ):
        """
        Job queues section has Job History queue category.

        Requires:
            - Authenticated session

        Ensures:
            - Job History queue category element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-history" ).count() > 0

    def test_history_expand_btn_present( self, logged_in_page ):
        """
        Job History section has an expand button.

        Requires:
            - Authenticated session

        Ensures:
            - Expand button element exists within history section
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-history-expand-btn" ).count() > 0

    def test_history_time_window_select( self, logged_in_page ):
        """
        Job History section has a time window dropdown with 4 options.

        Requires:
            - Authenticated session

        Ensures:
            - Time window select element exists
            - Has 4 options: 7 days, 14 days, 30 days, All
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        select = logged_in_page.get_by_test_id( "history-time-window-select" )
        assert select.count() > 0

        options = select.locator( "option" )
        assert options.count() == 4

    def test_history_collapsed_by_default( self, logged_in_page ):
        """
        Job History jobs container is collapsed by default.

        Requires:
            - Authenticated session

        Ensures:
            - Jobs container has 'collapsed' CSS class
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        container = logged_in_page.get_by_test_id( "notifications-queue-history-jobs" )
        assert container.count() > 0
        assert "collapsed" in container.get_attribute( "class" )

    def test_history_expand_loads_content( self, logged_in_page ):
        """
        Clicking expand button removes collapsed class from jobs container.

        Requires:
            - Authenticated session

        Ensures:
            - After clicking expand, container no longer has 'collapsed' class
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        expand_btn = logged_in_page.get_by_test_id( "notifications-queue-history-expand-btn" )
        expand_btn.click()

        container = logged_in_page.get_by_test_id( "notifications-queue-history-jobs" )
        # Wait briefly for the toggle to take effect
        logged_in_page.wait_for_timeout( 500 )
        assert "collapsed" not in ( container.get_attribute( "class" ) or "" )

    def test_history_count_badge( self, logged_in_page ):
        """
        Job History section has a count badge element.

        Requires:
            - Authenticated session

        Ensures:
            - Count badge element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        badge = logged_in_page.locator( "#history-count-badge" )
        assert badge.count() > 0
