"""
E2E UI tests for WebSocket authentication handshake.

Phase 7: WebSocket & Real-Time Tests — validates that the browser sends
proper auth_request messages and processes auth_success responses.

Technique: ws.on('framesent', handler) captures outgoing frames. Parse
JSON to verify auth_request structure. ws.on('framereceived', handler)
captures incoming auth_success responses.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

import json

from .conftest import (
    BASE_URL,
    capture_websockets,
    wait_for_ws_connected,
    get_ws_status,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _capture_ws_frames( page ):
    """
    Register WebSocket + frame listeners before navigation.

    Requires:
        - page is a Playwright page object
        - Must be called BEFORE page.goto()

    Ensures:
        - Returns (websockets, sent_frames, received_frames) lists
    """
    websockets      = []
    sent_frames     = []
    received_frames = []

    def on_websocket( ws ):
        websockets.append( ws )
        ws.on( "framesent", lambda payload: sent_frames.append(
            { "url": ws.url, "data": payload }
        ) )
        ws.on( "framereceived", lambda payload: received_frames.append(
            { "url": ws.url, "data": payload }
        ) )

    page.on( "websocket", on_websocket )

    return websockets, sent_frames, received_frames


# ---------------------------------------------------------------------------
# Auth Handshake Sent
# ---------------------------------------------------------------------------

class TestAuthHandshakeSent:
    """Tests for auth_request messages sent by the browser."""

    def test_auth_request_sent_on_queue_ws( self, logged_in_page ):
        """
        Browser sends auth_request on queue WebSocket after connection opens.

        Requires:
            - Authenticated session

        Ensures:
            - At least one framesent on queue WS is a JSON auth_request
        """
        _, sent_frames, _ = _capture_ws_frames( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        # Find auth_request frames sent on queue WS
        queue_auth_frames = []
        for frame in sent_frames:
            if "/ws/queue/" not in frame[ "url" ]:
                continue
            try:
                msg = json.loads( frame[ "data" ] )
                if msg.get( "type" ) == "auth_request":
                    queue_auth_frames.append( msg )
            except ( json.JSONDecodeError, TypeError ):
                continue

        assert len( queue_auth_frames ) > 0, \
            f"No auth_request sent on queue WS. Sent frames: {len( sent_frames )}"

    def test_auth_request_contains_token( self, logged_in_page ):
        """
        Auth request message includes a non-empty token field.

        Requires:
            - Authenticated session

        Ensures:
            - auth_request has 'token' field with non-empty string
        """
        _, sent_frames, _ = _capture_ws_frames( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        for frame in sent_frames:
            if "/ws/queue/" not in frame[ "url" ]:
                continue
            try:
                msg = json.loads( frame[ "data" ] )
                if msg.get( "type" ) == "auth_request":
                    assert "token" in msg, "auth_request missing 'token' field"
                    assert len( msg[ "token" ] ) > 0, "auth_request token is empty"
                    # Token should NOT have Bearer prefix (JS strips it)
                    assert not msg[ "token" ].startswith( "Bearer " ), \
                        "Token should not have Bearer prefix in WS auth"
                    return
            except ( json.JSONDecodeError, TypeError ):
                continue

        assert False, "No auth_request frame found to verify token"

    def test_auth_request_contains_session_id( self, logged_in_page ):
        """
        Auth request message includes a session_id field.

        Requires:
            - Authenticated session

        Ensures:
            - auth_request has 'session_id' field matching localStorage value
        """
        _, sent_frames, _ = _capture_ws_frames( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        stored_session_id = logged_in_page.evaluate(
            "localStorage.getItem( 'notifications_queue_session_id' )"
        )

        for frame in sent_frames:
            if "/ws/queue/" not in frame[ "url" ]:
                continue
            try:
                msg = json.loads( frame[ "data" ] )
                if msg.get( "type" ) == "auth_request":
                    assert "session_id" in msg, "auth_request missing 'session_id'"
                    assert msg[ "session_id" ] == stored_session_id, \
                        f"session_id mismatch: frame={msg[ 'session_id' ]}, localStorage={stored_session_id}"
                    return
            except ( json.JSONDecodeError, TypeError ):
                continue

        assert False, "No auth_request frame found to verify session_id"

    def test_auth_request_contains_subscribed_events( self, logged_in_page ):
        """
        Auth request message includes subscribed_events array.

        Requires:
            - Authenticated session

        Ensures:
            - auth_request has 'subscribed_events' list with expected event types
        """
        _, sent_frames, _ = _capture_ws_frames( logged_in_page )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        wait_for_ws_connected( logged_in_page )

        for frame in sent_frames:
            if "/ws/queue/" not in frame[ "url" ]:
                continue
            try:
                msg = json.loads( frame[ "data" ] )
                if msg.get( "type" ) == "auth_request":
                    assert "subscribed_events" in msg, \
                        "auth_request missing 'subscribed_events'"
                    events = msg[ "subscribed_events" ]
                    assert isinstance( events, list ), \
                        f"subscribed_events should be a list, got: {type( events )}"
                    assert len( events ) > 0, "subscribed_events is empty"
                    # Check for key event types
                    assert "auth_success" in events, \
                        f"'auth_success' not in subscribed_events: {events}"
                    assert "job_state_transition" in events, \
                        f"'job_state_transition' not in subscribed_events: {events}"
                    return
            except ( json.JSONDecodeError, TypeError ):
                continue

        assert False, "No auth_request frame found to verify subscribed_events"


# ---------------------------------------------------------------------------
# Auth Handshake Response
# ---------------------------------------------------------------------------

class TestAuthHandshakeResponse:
    """Tests for server auth_success response handling."""

    def test_auth_success_updates_user_display( self, notifications_page ):
        """
        Auth success response updates the auth status with user identifier.

        Requires:
            - notifications_page fixture (WS connected + authenticated)

        Ensures:
            - auth-status text contains 'Authenticated'
        """
        # Wait for auth_success to propagate
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'auth-status' );
                return el && el.textContent.includes( 'Authenticated' );
            }""",
            timeout=10000
        )

        status = get_ws_status( notifications_page, "auth" )
        assert "Authenticated" in status[ "text" ]

    def test_auth_success_triggers_initial_data_load( self, notifications_page ):
        """
        Auth success triggers loadInitialData which populates queue sections.

        Requires:
            - notifications_page fixture (WS connected + authenticated)

        Ensures:
            - Queue section containers are present (populated by loadInitialData)
        """
        # loadInitialData is called on auth_success — verify it ran by checking
        # that queue containers exist (they're populated by the initial data load)
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( 'auth-status' );
                return el && el.textContent.includes( 'Authenticated' );
            }""",
            timeout=10000
        )

        # Queue section containers should exist after initial data load
        todo_section = notifications_page.get_by_test_id( "notifications-queue-todo" )
        assert todo_section.count() > 0, "Todo queue section missing after auth_success"

    def test_no_auth_redirects_to_login( self, page, clean_test_db ):
        """
        Accessing notifications without authentication redirects to login.

        Requires:
            - Clean database, no login performed

        Ensures:
            - Page redirects to login URL
        """
        # Clear any stale tokens
        page.goto( f"{BASE_URL}/app/auth/login" )
        page.evaluate( "localStorage.clear()" )

        # Try to access notifications without auth
        page.goto( f"{BASE_URL}/app/notifications" )
        page.wait_for_timeout( 3000 )

        assert "/login" in page.url, \
            f"Expected redirect to login, but URL is: {page.url}"
