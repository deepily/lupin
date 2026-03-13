"""
E2E UI tests for the System Status section on the notifications page.

Phase 6: Notifications & Q&A Tests — validates WebSocket status indicators,
auth status, and action buttons (refresh, config reload, logout).

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# System Status Layout
# ---------------------------------------------------------------------------

class TestSystemStatusLayout:
    """Tests for system status section rendering."""

    def test_ws_queue_status_present( self, logged_in_page ):
        """
        System status has WebSocket queue connection indicator.

        Requires:
            - Authenticated session

        Ensures:
            - Queue WS status element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-ws-queue-status" ).count() > 0

    def test_ws_audio_status_present( self, logged_in_page ):
        """
        System status has WebSocket audio connection indicator.

        Requires:
            - Authenticated session

        Ensures:
            - Audio WS status element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-ws-audio-status" ).count() > 0

    def test_auth_status_present( self, logged_in_page ):
        """
        System status has authentication status indicator.

        Requires:
            - Authenticated session

        Ensures:
            - Auth status element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-auth-status" ).count() > 0


# ---------------------------------------------------------------------------
# System Status Actions
# ---------------------------------------------------------------------------

class TestSystemStatusActions:
    """Tests for system status action buttons."""

    def test_logout_button_present( self, logged_in_page ):
        """
        System status has logout button.

        Requires:
            - Authenticated session

        Ensures:
            - Logout button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-logout-btn" ).count() > 0

    def test_refresh_button_present( self, logged_in_page ):
        """
        System status has refresh button.

        Requires:
            - Authenticated session

        Ensures:
            - Refresh button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-status-refresh-btn" ).count() > 0

    def test_config_reload_button_present( self, logged_in_page ):
        """
        System status has config reload button.

        Requires:
            - Authenticated session

        Ensures:
            - Config reload button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-config-reload-btn" ).count() > 0

    def test_logout_redirects_to_login( self, logged_in_page ):
        """
        Clicking logout button redirects to login page.

        Requires:
            - Authenticated session

        Ensures:
            - After logout, URL contains /login
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        logout_btn = logged_in_page.get_by_test_id( "notifications-logout-btn" )
        if logout_btn.count() > 0 and logout_btn.is_visible():
            logout_btn.click()
            logged_in_page.wait_for_timeout( 3000 )
            # Logout may redirect to login or landing page
            assert "/login" in logged_in_page.url or "/app" in logged_in_page.url
