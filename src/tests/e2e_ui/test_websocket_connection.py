"""
E2E UI tests for browser-side WebSocket connection lifecycle.

Phase 7: WebSocket & Real-Time Tests — validates that WebSocket connections
open on page load, URLs are correctly constructed, and status indicators
update in the DOM.

Technique: Register page.on('websocket', handler) BEFORE navigating to
/app/notifications to capture WebSocket URLs. Then wait for status
indicator text/class changes.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from urllib.parse import quote

from .conftest import (
    BASE_URL,
    capture_websockets,
    wait_for_ws_connected,
    get_ws_status,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# WebSocket Connection Establishment
# ---------------------------------------------------------------------------

class TestWebSocketConnectionEstablishment:
    """Tests for WebSocket connections opening on notifications page load."""

    def test_queue_websocket_opens_on_page_load( self, logged_in_page ):
        """
        Queue WebSocket connection opens when notifications page loads.

        Requires:
            - Authenticated session

        Ensures:
            - At least one WebSocket URL contains '/ws/queue/'
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        ws_urls = [ ws.url for ws in websockets ]
        assert any( "/ws/queue/" in url for url in ws_urls ), \
            f"No queue WebSocket found in: {ws_urls}"

    def test_audio_websocket_opens_on_page_load( self, logged_in_page ):
        """
        Audio WebSocket connection opens when notifications page loads.

        Requires:
            - Authenticated session

        Ensures:
            - At least one WebSocket URL contains '/ws/audio/'
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        ws_urls = [ ws.url for ws in websockets ]
        assert any( "/ws/audio/" in url for url in ws_urls ), \
            f"No audio WebSocket found in: {ws_urls}"

    def test_queue_websocket_url_contains_session_id( self, logged_in_page ):
        """
        Queue WebSocket URL includes the session ID from localStorage.

        Requires:
            - Authenticated session

        Ensures:
            - Queue WS URL ends with the session ID stored in localStorage
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        session_id = logged_in_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )
        assert session_id is not None, "Queue session ID not found in localStorage"

        queue_urls = [ ws.url for ws in websockets if "/ws/queue/" in ws.url ]
        assert len( queue_urls ) > 0, "No queue WebSocket captured"
        # Session ID may be URL-encoded (spaces → %20) in the WS URL
        encoded_id = quote( session_id )
        assert session_id in queue_urls[ 0 ] or encoded_id in queue_urls[ 0 ], \
            f"Session ID '{session_id}' not found in URL: {queue_urls[ 0 ]}"

    def test_audio_websocket_url_contains_session_id( self, logged_in_page ):
        """
        Audio WebSocket URL includes the session ID from localStorage.

        Requires:
            - Authenticated session

        Ensures:
            - Audio WS URL ends with the session ID stored in localStorage
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        session_id = logged_in_page.evaluate(
            "localStorage.getItem( 'notifications_audio_session_id' )"
        )
        assert session_id is not None, "Audio session ID not found in localStorage"

        audio_urls = [ ws.url for ws in websockets if "/ws/audio/" in ws.url ]
        assert len( audio_urls ) > 0, "No audio WebSocket captured"
        # Session ID may be URL-encoded (spaces → %20) in the WS URL
        encoded_id = quote( session_id )
        assert session_id in audio_urls[ 0 ] or encoded_id in audio_urls[ 0 ], \
            f"Session ID '{session_id}' not found in URL: {audio_urls[ 0 ]}"

    def test_queue_websocket_url_uses_ws_protocol( self, logged_in_page ):
        """
        Queue WebSocket URL uses ws:// protocol (not http://).

        Requires:
            - Authenticated session

        Ensures:
            - Queue WS URL starts with 'ws://' (or 'wss://' for HTTPS)
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        queue_urls = [ ws.url for ws in websockets if "/ws/queue/" in ws.url ]
        assert len( queue_urls ) > 0, "No queue WebSocket captured"
        assert queue_urls[ 0 ].startswith( "ws://" ) or queue_urls[ 0 ].startswith( "wss://" ), \
            f"Expected ws:// protocol, got: {queue_urls[ 0 ]}"

    def test_both_websockets_open_concurrently( self, logged_in_page ):
        """
        Both queue and audio WebSockets open on page load.

        Requires:
            - Authenticated session

        Ensures:
            - At least 2 WebSocket connections captured
            - One queue and one audio WebSocket present
        """
        websockets = capture_websockets( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        ws_urls    = [ ws.url for ws in websockets ]
        has_queue  = any( "/ws/queue/" in url for url in ws_urls )
        has_audio  = any( "/ws/audio/" in url for url in ws_urls )

        assert has_queue, f"No queue WebSocket in: {ws_urls}"
        assert has_audio, f"No audio WebSocket in: {ws_urls}"


# ---------------------------------------------------------------------------
# WebSocket Status Indicators
# ---------------------------------------------------------------------------

class TestWebSocketStatusIndicators:
    """Tests for DOM status indicator updates after WebSocket connection."""

    def test_queue_status_shows_connected( self, notifications_page ):
        """
        Queue WS status indicator shows 'Connected' after page load.

        Requires:
            - notifications_page fixture (WS already connected)

        Ensures:
            - queue-ws-status text contains 'Connected'
        """
        status = get_ws_status( notifications_page, "queue" )
        assert "Connected" in status[ "text" ], \
            f"Expected 'Connected', got: {status[ 'text' ]}"

    def test_audio_status_shows_connected( self, notifications_page ):
        """
        Audio WS status indicator shows 'Connected' after page load.

        Requires:
            - notifications_page fixture (WS already connected)

        Ensures:
            - audio-ws-status text contains 'Connected'
        """
        # Audio WS may take slightly longer
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'audio-ws-status' );
                return el && el.textContent.includes( 'Connected' );
            }""",
            timeout=10000
        )

        status = get_ws_status( notifications_page, "audio" )
        assert "Connected" in status[ "text" ], \
            f"Expected 'Connected', got: {status[ 'text' ]}"

    def test_auth_status_shows_authenticated( self, notifications_page ):
        """
        Auth status indicator shows 'Authenticated' after WS auth handshake.

        Requires:
            - notifications_page fixture (WS already connected and authenticated)

        Ensures:
            - auth-status text contains 'Authenticated'
        """
        # Wait for auth_success WS message to update status
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'auth-status' );
                return el && el.textContent.includes( 'Authenticated' );
            }""",
            timeout=10000
        )

        status = get_ws_status( notifications_page, "auth" )
        assert "Authenticated" in status[ "text" ], \
            f"Expected 'Authenticated', got: {status[ 'text' ]}"

    def test_queue_status_has_good_class( self, notifications_page ):
        """
        Queue WS status indicator has 'status-good' CSS class when connected.

        Requires:
            - notifications_page fixture (WS already connected)

        Ensures:
            - queue-ws-status element has class 'status-good'
        """
        status = get_ws_status( notifications_page, "queue" )
        assert "status-good" in status[ "class_name" ], \
            f"Expected 'status-good', got: {status[ 'class_name' ]}"

    def test_auth_status_has_success_class( self, notifications_page ):
        """
        Auth status indicator has success-type CSS class after authentication.

        Requires:
            - notifications_page fixture (WS already connected and authenticated)

        Ensures:
            - auth-status element has 'status-good' or 'status-success' class
        """
        # Wait for auth_success WS message to update the class
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'auth-status' );
                return el && ( el.className.includes( 'good' ) || el.className.includes( 'success' ) );
            }""",
            timeout=10000
        )

        status = get_ws_status( notifications_page, "auth" )
        assert "status-good" in status[ "class_name" ] or "status-success" in status[ "class_name" ], \
            f"Expected 'status-good' or 'status-success', got: {status[ 'class_name' ]}"
