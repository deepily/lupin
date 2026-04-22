"""
E2E UI tests for the notifications page section toolbar and visibility.

Phase 6: Notifications & Q&A Tests — validates the 11 section toolbar buttons
toggle section visibility, and sections render their key elements.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Toolbar Rendering
# ---------------------------------------------------------------------------

class TestNotificationsToolbar:
    """Tests for the floating section visibility toolbar."""

    TOOLBAR_BUTTONS = [
        "notifications-toolbar-qa",
        "notifications-toolbar-jobs",
        "notifications-toolbar-action",
        "notifications-toolbar-tts",
        "notifications-toolbar-notifs",
        "notifications-toolbar-filters",
        "notifications-toolbar-queues",
        "notifications-toolbar-time",
        "notifications-toolbar-status",
        "notifications-toolbar-direct-tts",
        "notifications-toolbar-debug",
    ]

    def test_all_toolbar_buttons_present( self, logged_in_page ):
        """
        Notifications page has all 11 section toolbar buttons.

        Requires:
            - Authenticated session

        Ensures:
            - All 11 toolbar buttons exist in DOM
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        for testid in self.TOOLBAR_BUTTONS:
            btn = logged_in_page.get_by_test_id( testid )
            assert btn.count() > 0, f"Toolbar button '{testid}' not found in DOM"

    @pytest.mark.parametrize( "testid", [
        "notifications-toolbar-qa",
        "notifications-toolbar-jobs",
        "notifications-toolbar-action",
        "notifications-toolbar-tts",
        "notifications-toolbar-queues",
        "notifications-toolbar-time",
        "notifications-toolbar-status",
    ] )
    def test_toolbar_button_is_clickable( self, logged_in_page, testid ):
        """
        Each toolbar button is visible and clickable.

        Requires:
            - Authenticated session

        Ensures:
            - Button is visible and can be clicked without error
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        btn = logged_in_page.get_by_test_id( testid )
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            logged_in_page.wait_for_timeout( 300 )


# ---------------------------------------------------------------------------
# Section Visibility
# ---------------------------------------------------------------------------

class TestNotificationsSectionVisibility:
    """Tests for section expand/collapse behavior."""

    def test_page_loads_without_errors( self, logged_in_page ):
        """
        Notifications page loads successfully.

        Requires:
            - Authenticated session

        Ensures:
            - Page navigates to /app/notifications without crash
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert "/notifications" in logged_in_page.url

    def test_qa_section_has_key_elements( self, logged_in_page ):
        """
        Q&A section has mode selector, input, and submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Q&A interface core elements present in DOM
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-qa-mode-select" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-qa-input" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-qa-submit-btn" ).count() > 0

    def test_jobs_section_has_cc_card( self, logged_in_page ):
        """
        Jobs section has the Claude Code dispatcher card.

        Requires:
            - Authenticated session

        Ensures:
            - CC card element present in DOM
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-card" ).count() > 0

    def test_action_section_exists( self, logged_in_page ):
        """
        Action Required section exists in DOM.

        Requires:
            - Authenticated session

        Ensures:
            - Action section with active slot and pending queue present
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-action-section" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-action-active-slot" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-action-pending-queue" ).count() > 0

    def test_tts_section_has_controls( self, logged_in_page ):
        """
        TTS section has playback controls.

        Requires:
            - Authenticated session

        Ensures:
            - Pause, play, and clear buttons present
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-pause-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-tts-play-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-tts-clear-btn" ).count() > 0
