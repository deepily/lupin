"""
E2E UI tests for WebSocket session ID persistence in localStorage.

Phase 7: WebSocket & Real-Time Tests — validates session ID creation,
format, persistence across page reloads, and display in the DOM.

Technique: page.evaluate("localStorage.getItem(...)") to read session IDs,
page.reload() to verify persistence, and DOM element inspection for display.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page / notifications_page fixtures)
"""

import re
from urllib.parse import quote

from .conftest import (
    BASE_URL,
    wait_for_ws_connected,
    capture_websockets,
)


# ---------------------------------------------------------------------------
# Session ID Creation
# ---------------------------------------------------------------------------

class TestSessionIdCreation:
    """Tests for WebSocket session ID creation in localStorage."""

    def test_queue_session_id_stored_in_localstorage( self, notifications_page ):
        """
        Queue session ID is stored in localStorage after page load.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - notifications_queue_session_id key exists and is non-empty
        """
        session_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert session_id is not None, "Queue session ID not in localStorage"
        assert len( session_id ) > 0, "Queue session ID is empty"

    def test_audio_session_id_stored_in_localstorage( self, notifications_page ):
        """
        Audio session ID is stored in localStorage after page load.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - notifications_audio_session_id key exists and is non-empty
        """
        session_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_audio_session_id' )"
        )
        assert session_id is not None, "Audio session ID not in localStorage"
        assert len( session_id ) > 0, "Audio session ID is empty"

    def test_session_id_format_matches_pattern( self, notifications_page ):
        """
        Session IDs follow the 'adjective_animal' word format.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - Queue session ID matches pattern: lowercase_word_lowercase_word
        """
        session_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert session_id is not None, "Queue session ID not in localStorage"

        # Format: "adjective animal" (two lowercase words separated by space or underscore)
        pattern = r"^[a-z]+[ _][a-z]+$"
        assert re.match( pattern, session_id ), \
            f"Session ID '{session_id}' does not match pattern '{pattern}'"

    def test_queue_and_audio_session_ids_are_different( self, notifications_page ):
        """
        Queue and audio session IDs are distinct values.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - Queue and audio session IDs are not the same string
        """
        queue_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        audio_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_audio_session_id' )"
        )
        assert queue_id is not None and audio_id is not None, \
            "Session IDs missing from localStorage"
        assert queue_id != audio_id, \
            f"Queue and audio session IDs should differ, both are: {queue_id}"


# ---------------------------------------------------------------------------
# Session ID Persistence
# ---------------------------------------------------------------------------

class TestSessionIdPersistence:
    """Tests for session ID survival across page reloads."""

    def test_session_id_survives_page_reload( self, notifications_page ):
        """
        Queue session ID persists in localStorage after page reload.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - Same session ID present after reload
        """
        original_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert original_id is not None

        notifications_page.reload()
        notifications_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( notifications_page )

        reloaded_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert reloaded_id == original_id, \
            f"Session ID changed after reload: '{original_id}' → '{reloaded_id}'"

    def test_session_id_survives_navigation_away_and_back( self, notifications_page ):
        """
        Session ID persists when navigating away from and back to notifications.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - Same session ID present after navigate away + return
        """
        original_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert original_id is not None

        # Navigate away to profile
        notifications_page.goto( f"{BASE_URL}/app/auth/profile" )
        notifications_page.wait_for_load_state( "networkidle" )

        # Navigate back to notifications
        notifications_page.goto( f"{BASE_URL}/app/notifications" )
        notifications_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( notifications_page )

        returned_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert returned_id == original_id, \
            f"Session ID changed after navigation: '{original_id}' → '{returned_id}'"

    def test_session_id_reused_in_websocket_url_after_reload( self, notifications_page ):
        """
        WebSocket URL uses the same session ID after page reload.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - Captured WS URL contains the original session ID
        """
        original_id = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert original_id is not None

        # Capture WebSockets before reload
        websockets = capture_websockets( notifications_page )

        notifications_page.reload()
        notifications_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( notifications_page )

        queue_urls = [ ws.url for ws in websockets if "/ws/queue/" in ws.url ]
        assert len( queue_urls ) > 0, "No queue WebSocket captured after reload"
        # Session ID may be URL-encoded (spaces → %20) in the WS URL
        encoded_id = quote( original_id )
        assert original_id in queue_urls[ 0 ] or encoded_id in queue_urls[ 0 ], \
            f"Original session ID '{original_id}' not in reconnected URL: {queue_urls[ 0 ]}"


# ---------------------------------------------------------------------------
# Session ID Display
# ---------------------------------------------------------------------------

class TestSessionIdDisplay:
    """Tests for session ID display in the notifications page DOM."""

    def test_queue_session_displayed_in_status_section( self, notifications_page ):
        """
        Queue session ID is displayed in the system status section.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - #queue-session element contains a non-dash value
        """
        displayed = notifications_page.evaluate(
            "document.getElementById( 'queue-session' ).textContent"
        )
        assert displayed is not None and displayed != "-", \
            f"Queue session not displayed, got: '{displayed}'"

    def test_audio_session_displayed_in_status_section( self, notifications_page ):
        """
        Audio session ID is displayed in the system status section.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - #audio-session element contains a non-dash value
        """
        displayed = notifications_page.evaluate(
            "document.getElementById( 'audio-session' ).textContent"
        )
        assert displayed is not None and displayed != "-", \
            f"Audio session not displayed, got: '{displayed}'"

    def test_displayed_session_matches_localstorage( self, notifications_page ):
        """
        Displayed queue session ID matches the value in localStorage.

        Requires:
            - notifications_page fixture (WS connected)

        Ensures:
            - DOM display matches localStorage value exactly
        """
        stored = notifications_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        displayed = notifications_page.evaluate(
            "document.getElementById( 'queue-session' ).textContent"
        )
        assert stored == displayed, \
            f"localStorage '{stored}' != displayed '{displayed}'"
