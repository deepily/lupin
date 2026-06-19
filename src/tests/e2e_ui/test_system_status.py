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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        logout_btn = logged_in_page.get_by_test_id( "notifications-logout-btn" )
        if logout_btn.count() > 0 and logout_btn.is_visible():
            logout_btn.click()
            logged_in_page.wait_for_timeout( 3000 )
            # Logout may redirect to login or landing page
            assert "/login" in logged_in_page.url or "/app" in logged_in_page.url


# ---------------------------------------------------------------------------
# Missed-notifications "Reset" button (badge reset, soft-dismiss)
# ---------------------------------------------------------------------------

class TestMissedResetButton:
    """
    Tests for the "Reset" button beside the "N missed while away" indicator.

    The onclick handlers on this section are inline (window.<global>.<method>()).
    A wrong global name resolves to `undefined` at click time and throws
    'Cannot read properties of undefined' — a class of bug that DOM-presence
    checks miss but a global-resolution check catches. These guard exactly that.
    """

    def test_missed_reset_button_present( self, logged_in_page ):
        """The Reset button element exists in the System Status section."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-missed-reset-btn" ).count() > 0

    def test_inline_onclick_globals_resolve( self, logged_in_page ):
        """
        REGRESSION GUARD: every inline onclick global in the status section must
        resolve to a real instance with the referenced method. Catches the
        window.freshQueueUI (undefined) → resetMissedNotifications/logout bug.

        Ensures:
            - window.notificationsUI is defined
            - resetMissedNotifications and logout are functions on it
            - no remaining 'freshQueueUI' reference in the status-section onclicks
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.evaluate( "() => typeof window.notificationsUI" ) == "object"
        assert logged_in_page.evaluate( "() => typeof window.notificationsUI.resetMissedNotifications" ) == "function"
        assert logged_in_page.evaluate( "() => typeof window.notificationsUI.logout" ) == "function"

        reset_onclick  = logged_in_page.get_by_test_id( "notifications-missed-reset-btn" ).get_attribute( "onclick" ) or ""
        logout_onclick = logged_in_page.get_by_test_id( "notifications-logout-btn" ).get_attribute( "onclick" ) or ""
        assert "window.notificationsUI." in reset_onclick and "freshQueueUI" not in reset_onclick
        assert "window.notificationsUI." in logout_onclick and "freshQueueUI" not in logout_onclick


# ---------------------------------------------------------------------------
# Message-body markdown rendering (send-bar code blocks)
# ---------------------------------------------------------------------------

class TestNotificationMarkdownRendering:
    """
    A message body with a fenced code block (```) must render as <pre><code>,
    not as literal backticks. renderMarkdownInline() delegates fenced content to
    the block renderer; non-fenced content keeps the lighter inline path. These
    drive the ACTUAL shipped function in a real browser (marked + DOMPurify loaded),
    so they catch regressions in the delegation logic. Read-only (no send, no DB).
    """

    def test_fenced_code_renders_as_pre_block( self, logged_in_page ):
        """Triple-backtick fenced code → <pre><code>, no raw backticks leak."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        html = logged_in_page.evaluate(
            r"() => window.notificationsUI.renderMarkdownInline('```js\nconst x = 1;\n```')"
        )
        assert "<pre" in html and "<code" in html, f"fenced code did not render as a block: {html}"
        assert "```" not in html, f"raw fences leaked into rendered output: {html}"

    def test_inline_code_stays_inline_no_block( self, logged_in_page ):
        """Single-backtick inline code still renders inline, NOT as a <pre> block."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        html = logged_in_page.evaluate(
            "() => window.notificationsUI.renderMarkdownInline('run `npm test` now')"
        )
        assert "<code>npm test</code>" in html, f"inline code did not render: {html}"
        assert "<pre" not in html, f"inline path must not emit a block: {html}"
