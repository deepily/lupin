#!/usr/bin/env python3
"""
WebSocket Listener for the Notification Proxy Agent.

Connects to the Lupin FastAPI WebSocket endpoint, authenticates,
subscribes to notification events, and dispatches received events
to a callback handler. Includes exponential backoff reconnection.

References:
    - src/scripts/debug/debug_websocket_auth_validation.py (client pattern)
    - src/cosa/rest/websocket_manager.py (server-side subscription logic)
"""

from cosa.agents.notification_proxy.config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    SUBSCRIBED_EVENTS,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_BACKOFF_FACTOR,
)
from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener


class WebSocketListener( BaseWebSocketListener ):
    """
    Async WebSocket client that logs in, subscribes to notification events and calls back.

    Login, the receive loop, reconnection and stop live in BaseWebSocketListener. This
    class fixes the subscribed events and keeps this listener's plain backoff.

    Requires:
        - email is a valid mock test email
        - session_id follows adjective-noun format
        - on_event is an async callable accepting (event_type, event_data)

    Ensures:
        - Maintains persistent connection with keep-alive ping/pong
        - Reconnects with exponential backoff on disconnection
        - Calls on_event for every received WebSocket message
    """

    LOG_PREFIX = "[Listener]"

    def __init__(
        self,
        email,
        password,
        session_id,
        on_event,
        host    = DEFAULT_SERVER_HOST,
        port    = DEFAULT_SERVER_PORT,
        debug   = False,
        verbose = False
    ):
        """
        Initialize the WebSocket listener.

        Requires:
            - email is a non-empty string
            - password is a non-empty string
            - session_id is a non-empty string
            - on_event is an async callable( event_type: str, event_data: dict )

        Args:
            email: User email for JWT authentication
            password: User password for JWT authentication
            session_id: WebSocket session identifier
            on_event: Async callback for received events
            host: Server hostname
            port: Server port
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            email, password, session_id, on_event, SUBSCRIBED_EVENTS,
            host=host, port=port, debug=debug, verbose=verbose
        )

    def _next_delay( self ):
        """
        Seconds to wait before the next reconnect attempt: plain exponential, capped, no jitter.

        Requires:
            - self._attempt has already been incremented for this retry

        Ensures:
            - returns the smaller of initial * factor ** attempt and the maximum delay
        """
        return min( RECONNECT_INITIAL_DELAY * ( RECONNECT_BACKOFF_FACTOR ** self._attempt ), RECONNECT_MAX_DELAY )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test for WebSocket listener — tests construction only (no server needed)."""
    print( "\n" + "=" * 60 )
    print( "WebSocket Listener Smoke Test" )
    print( "=" * 60 )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Construction
    print( "\n1. Testing listener construction..." )
    try:
        async def mock_handler( event_type, data ):
            pass

        listener = WebSocketListener(
            email      = "test@example.com",
            password   = "test-password",
            session_id = "test proxy",
            on_event   = mock_handler,
            debug      = True
        )
        assert listener.email == "test@example.com"
        assert listener.session_id == "test proxy"
        assert not listener.is_connected
        print( "   ✓ Listener constructed successfully" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Import chain
    print( "\n2. Testing import chain..." )
    try:
        from cosa.agents.notification_proxy.config import SUBSCRIBED_EVENTS, RECONNECT_MAX_ATTEMPTS
        assert len( SUBSCRIBED_EVENTS ) >= 3
        assert RECONNECT_MAX_ATTEMPTS == 10
        print( f"   ✓ Config imports: {len( SUBSCRIBED_EVENTS )} events, max {RECONNECT_MAX_ATTEMPTS} attempts" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Listener Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )
    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
