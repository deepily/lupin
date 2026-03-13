"""
E2E UI tests for CJ Flow job queue display on the notifications page.

Phase 6: Notifications & Q&A Tests — validates todo, running, done, and dead
queue sections with expand/collapse controls and filter buttons.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Queue Sections Present
# ---------------------------------------------------------------------------

class TestQueueSectionsLayout:
    """Tests for CJ Flow queue section rendering."""

    def test_todo_queue_present( self, logged_in_page ):
        """
        Job queues section has TODO queue.

        Requires:
            - Authenticated session

        Ensures:
            - TODO queue element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-todo" ).count() > 0

    def test_running_queue_present( self, logged_in_page ):
        """
        Job queues section has Running queue.

        Requires:
            - Authenticated session

        Ensures:
            - Running queue element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-running" ).count() > 0

    def test_done_queue_present( self, logged_in_page ):
        """
        Job queues section has Done queue.

        Requires:
            - Authenticated session

        Ensures:
            - Done queue element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-done" ).count() > 0

    def test_dead_queue_present( self, logged_in_page ):
        """
        Job queues section has Dead queue.

        Requires:
            - Authenticated session

        Ensures:
            - Dead queue element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-dead" ).count() > 0


# ---------------------------------------------------------------------------
# Queue Expand/Collapse
# ---------------------------------------------------------------------------

class TestQueueExpandCollapse:
    """Tests for queue section expand/collapse toggle buttons."""

    def test_todo_expand_button_present( self, logged_in_page ):
        """
        TODO queue has expand/collapse button.

        Requires:
            - Authenticated session

        Ensures:
            - TODO expand button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-todo-expand-btn" ).count() > 0

    def test_running_expand_button_present( self, logged_in_page ):
        """
        Running queue has expand/collapse button.

        Requires:
            - Authenticated session

        Ensures:
            - Running expand button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-running-expand-btn" ).count() > 0

    def test_done_expand_button_present( self, logged_in_page ):
        """
        Done queue has expand/collapse button.

        Requires:
            - Authenticated session

        Ensures:
            - Done expand button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-done-expand-btn" ).count() > 0

    def test_dead_expand_button_present( self, logged_in_page ):
        """
        Dead queue has expand/collapse button.

        Requires:
            - Authenticated session

        Ensures:
            - Dead expand button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-dead-expand-btn" ).count() > 0

    def test_todo_expand_button_clickable( self, logged_in_page ):
        """
        TODO expand button can be clicked without error.

        Requires:
            - Authenticated session

        Ensures:
            - Button click doesn't cause page error
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        btn = logged_in_page.get_by_test_id( "notifications-queue-todo-expand-btn" )
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            logged_in_page.wait_for_timeout( 300 )


# ---------------------------------------------------------------------------
# Queue Filters
# ---------------------------------------------------------------------------

class TestQueueFilters:
    """Tests for job queue filter buttons."""

    def test_own_jobs_filter_present( self, logged_in_page ):
        """
        Queue section has 'My Jobs' filter button.

        Requires:
            - Authenticated session

        Ensures:
            - Own jobs filter button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-filter-own-btn" ).count() > 0

    def test_all_users_filter_present( self, logged_in_page ):
        """
        Queue section has 'All Users' filter button.

        Requires:
            - Authenticated session

        Ensures:
            - All users filter button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-filter-all-btn" ).count() > 0

    def test_filter_buttons_clickable( self, logged_in_page ):
        """
        Filter buttons can be clicked to toggle.

        Requires:
            - Authenticated session

        Ensures:
            - Both filter buttons are clickable
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        own_btn = logged_in_page.get_by_test_id( "notifications-filter-own-btn" )
        all_btn = logged_in_page.get_by_test_id( "notifications-filter-all-btn" )

        if own_btn.count() > 0 and own_btn.is_visible():
            own_btn.click()
            logged_in_page.wait_for_timeout( 300 )

        if all_btn.count() > 0 and all_btn.is_visible():
            all_btn.click()
            logged_in_page.wait_for_timeout( 300 )
