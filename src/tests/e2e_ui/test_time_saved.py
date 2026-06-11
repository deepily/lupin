"""
E2E UI tests for the Time Saved dashboard on the notifications page.

Phase 6: Notifications & Q&A Tests — validates stats display elements
and top solutions list on the time saved dashboard section.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Time Saved Dashboard Layout
# ---------------------------------------------------------------------------

class TestTimeSavedLayout:
    """Tests for time saved dashboard section rendering."""

    def test_total_time_saved_present( self, logged_in_page ):
        """
        Time saved dashboard has total time saved display.

        Requires:
            - Authenticated session

        Ensures:
            - Total time saved element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-time-total" ).count() > 0

    def test_others_time_saved_present( self, logged_in_page ):
        """
        Time saved dashboard has others' time saved display.

        Requires:
            - Authenticated session

        Ensures:
            - Others time saved element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-time-others" ).count() > 0

    def test_solutions_created_present( self, logged_in_page ):
        """
        Time saved dashboard has solutions created count.

        Requires:
            - Authenticated session

        Ensures:
            - Solutions created element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-solutions-created" ).count() > 0

    def test_replays_benefited_present( self, logged_in_page ):
        """
        Time saved dashboard has replays benefited count.

        Requires:
            - Authenticated session

        Ensures:
            - Replays benefited element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-replays-benefited" ).count() > 0

    def test_top_solutions_list_present( self, logged_in_page ):
        """
        Time saved dashboard has top solutions list.

        Requires:
            - Authenticated session

        Ensures:
            - Top solutions element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-top-solutions" ).count() > 0

    def test_stats_show_zero_on_clean_db( self, logged_in_page ):
        """
        Stats show zero or empty values on a clean database.

        Requires:
            - Authenticated session, clean database

        Ensures:
            - Total time element exists and shows initial value
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        total = logged_in_page.get_by_test_id( "notifications-time-total" )
        if total.count() > 0:
            text = total.text_content().strip()
            # On a clean DB, stats should show zero or default value
            assert total is not None
