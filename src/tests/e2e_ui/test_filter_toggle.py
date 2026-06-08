"""
E2E UI tests for the notification filter toggle ("Not My Jobs" mode).

Tests the three-mode filter (Own / Others / All), admin-only visibility,
clickable header badges, and toolbar scroll-on-show behavior.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via admin_page / logged_in_page fixtures)
"""

import pytest

from .conftest import BASE_URL, wait_for_ws_connected


NOTIFICATIONS_URL = f"{BASE_URL}/app/notifications"


def goto_notifications( page ):
    """Navigate to notifications page and wait for load."""
    page.goto( NOTIFICATIONS_URL )
    page.wait_for_load_state( "networkidle" )


def goto_notifications_with_ws( page ):
    """Navigate to notifications page and wait for WebSocket auth (admin filter needs this)."""
    page.goto( NOTIFICATIONS_URL )
    page.wait_for_load_state( "networkidle" )
    try:
        wait_for_ws_connected( page, timeout=8000 )
    except Exception:
        pass  # Filter UI initializes from JWT, not WS — proceed even if WS times out
    page.wait_for_timeout( 1000 )  # Allow initializeFilterUI() to complete


# ---------------------------------------------------------------------------
# Filter Visibility (Role-Gating)
# ---------------------------------------------------------------------------

class TestFilterVisibility:
    """Tests that filter UI elements are visible for admins and hidden for regular users."""

    def test_filter_badges_hidden_for_regular_user( self, logged_in_page ):
        """
        Regular users should NOT see filter mode badges in section headers.

        Requires:
            - Authenticated as regular (non-admin) user

        Ensures:
            - Notifications filter badge is not visible
            - Queues filter badge is not visible
        """
        goto_notifications( logged_in_page )

        notif_badge = logged_in_page.get_by_test_id( "notifications-filter-badge" )
        queue_badge = logged_in_page.get_by_test_id( "queues-filter-badge" )

        assert not notif_badge.is_visible(), "Notifications filter badge should be hidden for regular users"
        assert not queue_badge.is_visible(), "Queues filter badge should be hidden for regular users"

    def test_filter_panel_hidden_for_regular_user( self, logged_in_page ):
        """
        Regular users should NOT see the filter settings panel.

        Requires:
            - Authenticated as regular (non-admin) user

        Ensures:
            - Filter settings section is not visible
        """
        goto_notifications( logged_in_page )

        # The filter panel should be hidden (display: none) for regular users
        is_visible = logged_in_page.evaluate(
            '() => { const el = document.getElementById( "filter-settings-section" ); return el && el.style.display !== "none"; }'
        )
        assert not is_visible, "Filter settings panel should be hidden for regular users"

    def test_filter_badges_visible_for_admin( self, admin_page ):
        """
        Admin users should see filter mode badges in section headers.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Notifications filter badge is visible
            - Queues filter badge is visible
        """
        goto_notifications_with_ws( admin_page )

        notif_badge = admin_page.get_by_test_id( "notifications-filter-badge" )
        queue_badge = admin_page.get_by_test_id( "queues-filter-badge" )

        assert notif_badge.is_visible(), "Notifications filter badge should be visible for admin"
        assert queue_badge.is_visible(), "Queues filter badge should be visible for admin"

    def test_filter_panel_has_three_buttons_for_admin( self, admin_page ):
        """
        Admin users should see all three filter buttons in the filter panel.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Own, Others, and All filter buttons exist in DOM
        """
        goto_notifications_with_ws( admin_page )

        assert admin_page.get_by_test_id( "notifications-filter-own-btn" ).count() > 0, "Own button missing"
        assert admin_page.get_by_test_id( "notifications-filter-others-btn" ).count() > 0, "Others button missing"
        assert admin_page.get_by_test_id( "notifications-filter-all-btn" ).count() > 0, "All button missing"


# ---------------------------------------------------------------------------
# Filter Modes (Admin-Only Functional Tests)
# ---------------------------------------------------------------------------

class TestFilterModes:
    """Tests that filter mode buttons change state correctly."""

    def test_default_filter_mode_is_own( self, admin_page ):
        """
        Default filter mode should be 'own' (My Jobs Only).

        Requires:
            - Authenticated as admin user
            - No saved filter preference in localStorage

        Ensures:
            - Own button has 'active' class
            - Badge displays 'Mine'
        """
        goto_notifications_with_ws( admin_page )

        own_btn = admin_page.get_by_test_id( "notifications-filter-own-btn" )
        has_active = own_btn.evaluate( 'el => el.classList.contains( "active" )' )
        assert has_active, "Own button should be active by default"

        badge = admin_page.get_by_test_id( "notifications-filter-badge" )
        badge_text = badge.text_content()
        assert "Mine" in badge_text, f"Badge should show 'Mine', got: '{badge_text}'"

    def test_click_others_button_changes_mode( self, admin_page ):
        """
        Clicking 'Not My Jobs' button activates others mode.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Others button gets 'active' class
            - Own button loses 'active' class
            - Badge displays 'Not Mine'
        """
        goto_notifications_with_ws( admin_page )

        admin_page.get_by_test_id( "notifications-filter-others-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        others_btn = admin_page.get_by_test_id( "notifications-filter-others-btn" )
        own_btn    = admin_page.get_by_test_id( "notifications-filter-own-btn" )

        assert others_btn.evaluate( 'el => el.classList.contains( "active" )' ), "Others button should be active"
        assert not own_btn.evaluate( 'el => el.classList.contains( "active" )' ), "Own button should not be active"

        badge = admin_page.get_by_test_id( "notifications-filter-badge" )
        assert "Not Mine" in badge.text_content(), "Badge should show 'Not Mine'"

    def test_click_all_button_changes_mode( self, admin_page ):
        """
        Clicking 'All Users' button activates all mode.

        Requires:
            - Authenticated as admin user

        Ensures:
            - All button gets 'active' class
            - Badge displays 'All Users'
        """
        goto_notifications_with_ws( admin_page )

        admin_page.get_by_test_id( "notifications-filter-all-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        all_btn = admin_page.get_by_test_id( "notifications-filter-all-btn" )
        assert all_btn.evaluate( 'el => el.classList.contains( "active" )' ), "All button should be active"

        badge = admin_page.get_by_test_id( "notifications-filter-badge" )
        assert "All Users" in badge.text_content(), "Badge should show 'All Users'"

    def test_both_badges_update_in_sync( self, admin_page ):
        """
        Both header badges update simultaneously when filter mode changes.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Notifications badge and Queues badge show same mode
        """
        goto_notifications_with_ws( admin_page )

        admin_page.get_by_test_id( "notifications-filter-others-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        notif_badge = admin_page.get_by_test_id( "notifications-filter-badge" ).text_content()
        queue_badge = admin_page.get_by_test_id( "queues-filter-badge" ).text_content()

        assert notif_badge == queue_badge, f"Badges out of sync: '{notif_badge}' vs '{queue_badge}'"
        assert "Not Mine" in notif_badge, "Both badges should show 'Not Mine'"

    def test_filter_mode_persists_across_reload( self, admin_page ):
        """
        Filter mode preference survives page reload via localStorage.

        Requires:
            - Authenticated as admin user

        Ensures:
            - Set mode to 'others', reload page, mode restored to 'others'
        """
        goto_notifications_with_ws( admin_page )

        # Set to others mode
        admin_page.get_by_test_id( "notifications-filter-others-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        # Reload
        admin_page.reload()
        admin_page.wait_for_load_state( "networkidle" )
        admin_page.wait_for_timeout( 1500 )  # Allow initializeFilterUI to restore

        # Verify mode persisted
        others_btn = admin_page.get_by_test_id( "notifications-filter-others-btn" )
        has_active = others_btn.evaluate( 'el => el.classList.contains( "active" )' )
        assert has_active, "Others button should still be active after reload"

        badge = admin_page.get_by_test_id( "notifications-filter-badge" )
        assert "Not Mine" in badge.text_content(), "Badge should still show 'Not Mine' after reload"


# ---------------------------------------------------------------------------
# Badge Click-to-Scroll Interaction
# ---------------------------------------------------------------------------

class TestFilterBadgeInteraction:
    """Tests that clicking header badges shows and scrolls to the filter panel."""

    def test_badge_click_shows_filter_panel( self, admin_page ):
        """
        Clicking a header badge shows the filter panel if it was hidden.

        Requires:
            - Authenticated as admin user
            - Filter panel hidden via toolbar toggle

        Ensures:
            - Filter panel becomes visible after badge click
        """
        goto_notifications_with_ws( admin_page )

        # Hide filter panel via toolbar button
        filter_toolbar_btn = admin_page.get_by_test_id( "notifications-toolbar-filters" )
        filter_toolbar_btn.click()
        admin_page.wait_for_timeout( 500 )

        # Verify panel is hidden
        is_hidden = admin_page.evaluate(
            '() => document.getElementById( "filter-settings-section" ).classList.contains( "section-hidden" )'
        )
        assert is_hidden, "Filter panel should be hidden after toolbar toggle"

        # Click badge to show panel
        admin_page.get_by_test_id( "notifications-filter-badge" ).click()
        admin_page.wait_for_timeout( 500 )

        # Verify panel is now visible
        is_visible = admin_page.evaluate(
            '() => !document.getElementById( "filter-settings-section" ).classList.contains( "section-hidden" )'
        )
        assert is_visible, "Filter panel should be visible after badge click"


# ---------------------------------------------------------------------------
# Toolbar Scroll-on-Show
# ---------------------------------------------------------------------------

class TestToolbarScrollOnShow:
    """Tests that showing a section via toolbar scrolls it into the viewport."""

    def test_toolbar_show_scrolls_section_into_view( self, admin_page ):
        """
        Clicking a toolbar button to show a hidden section scrolls it into view.

        Requires:
            - Authenticated as admin user

        Ensures:
            - After showing a section, it is within the viewport
        """
        goto_notifications_with_ws( admin_page )

        # Hide debug section, scroll to top
        debug_btn = admin_page.get_by_test_id( "notifications-toolbar-debug" )
        debug_btn.click()
        admin_page.wait_for_timeout( 300 )

        admin_page.evaluate( 'window.scrollTo( 0, 0 )' )
        admin_page.wait_for_timeout( 300 )

        # Show debug section (it's at the bottom)
        debug_btn.click()
        # The show path calls scrollIntoViewIfNeeded → scrollIntoView({behavior:'smooth'}),
        # which settles ASYNCHRONOUSLY. POLL until the section is in the viewport rather
        # than asserting at a fixed wait mid-animation: the old 500ms snapshot was flaky —
        # it caught the section still in-flight near the viewport's bottom edge (probe:
        # top≈672/720 at 500ms, settling to top≈246 by ~1s). wait_for_function raises
        # TimeoutError (→ test failure with teeth) if it never enters the viewport.
        admin_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'section-debug' );
                if ( !el ) return false;
                const rect = el.getBoundingClientRect();
                return rect.top >= 0 && rect.top < window.innerHeight;
            }""",
            timeout=5000
        )
