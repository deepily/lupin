#!/usr/bin/env python3
"""
Unit — WebSocketManager client-type marker + mobile-liveness helper (F-S6-1).

The FCM wake trigger (S6 §3.3) keys on "no live MOBILE queue-WS": the queue-WS
auth path records `client_type` from auth_request into the side map
`session_client_types` (user_sessions stores bare session-id strings — the
spec's side-map clause), and `has_live_mobile_session` answers the trigger.

Pins:
    - exactly "mobile" marks a mobile session; anything else (absent, casing,
      junk) is "web" — a desktop browser can never suppress the phone's wake
    - disconnect cleans the side map
    - liveness requires an ACTIVE connection — `register_session_user`
      pre-registrations without a socket don't count

Venue: :7999 (pure unit — WebSocketManager built via __new__, no config/server).
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.websocket_manager import WebSocketManager


def _manager():
    """WebSocketManager without the config-heavy __init__ (existing test convention)."""
    mgr = WebSocketManager.__new__( WebSocketManager )
    mgr.active_connections      = {}
    mgr.session_to_user         = {}
    mgr.user_sessions           = {}
    mgr.user_to_email           = {}
    mgr.session_is_admin        = {}
    mgr.session_client_types    = {}
    mgr.session_timestamps      = {}
    mgr.session_subscriptions   = {}
    mgr.main_loop               = None
    mgr.single_session_per_user = False
    mgr.available_events        = { "notification_queue_update" }
    return mgr


class TestClientTypeRecording:

    def test_mobile_marker_recorded( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", client_type="mobile" )
        assert mgr.session_client_types[ "sess-1" ] == "mobile"

    def test_absent_marker_means_web( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1" )
        assert mgr.session_client_types[ "sess-1" ] == "web"

    def test_non_mobile_value_pinned_to_web( self ):
        # Exact-match pin: casing or junk never counts as mobile
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", client_type="Mobile" )
        mgr.connect( MagicMock(), "sess-2", "user-1", client_type="tablet" )
        assert mgr.session_client_types[ "sess-1" ] == "web"
        assert mgr.session_client_types[ "sess-2" ] == "web"

    def test_disconnect_cleans_side_map( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", client_type="mobile" )
        mgr.disconnect( "sess-1" )
        assert "sess-1" not in mgr.session_client_types

    def test_marker_recorded_for_anonymous_session_too( self ):
        # The audio WS connects without user_id at first — the side map entry
        # still exists (as web) and is cleaned on disconnect.
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-audio" )
        assert mgr.session_client_types[ "sess-audio" ] == "web"


class TestHasLiveMobileSession:

    def test_true_for_live_mobile_session( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-m", "user-1", client_type="mobile" )
        assert mgr.has_live_mobile_session( "user-1" ) is True

    def test_false_for_unknown_user( self ):
        mgr = _manager()
        assert mgr.has_live_mobile_session( "ghost" ) is False

    def test_false_when_only_web_sessions( self ):
        # The "one listening channel" pin: a live desktop browser must NOT
        # suppress the phone's wake.
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-w", "user-1" )
        assert mgr.has_live_mobile_session( "user-1" ) is False

    def test_false_after_mobile_disconnects( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-m", "user-1", client_type="mobile" )
        mgr.disconnect( "sess-m" )
        assert mgr.has_live_mobile_session( "user-1" ) is False

    def test_false_for_connectionless_preregistration( self ):
        # register_session_user creates user_sessions entries WITHOUT a socket;
        # liveness requires presence in active_connections.
        mgr = _manager()
        mgr.register_session_user( "sess-pre", "user-1" )
        mgr.session_client_types[ "sess-pre" ] = "mobile"   # even if somehow marked
        assert mgr.has_live_mobile_session( "user-1" ) is False

    def test_true_when_mobile_among_mixed_sessions( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-w", "user-1" )
        mgr.connect( MagicMock(), "sess-m", "user-1", client_type="mobile" )
        assert mgr.has_live_mobile_session( "user-1" ) is True

    def test_other_users_mobile_does_not_leak( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-m", "user-2", client_type="mobile" )
        mgr.connect( MagicMock(), "sess-w", "user-1" )
        assert mgr.has_live_mobile_session( "user-1" ) is False


class TestSessionInfoExposesClientType:

    def test_session_info_reports_mobile( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-m", "user-1", client_type="mobile" )
        assert mgr.get_session_info( "sess-m" )[ "client_type" ] == "mobile"

    def test_session_info_reports_web_for_unmarked( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-w", "user-1" )
        assert mgr.get_session_info( "sess-w" )[ "client_type" ] == "web"

    def test_session_info_defaults_web_when_side_map_lacks_entry( self ):
        # Defensive default at the read: a connection registered outside
        # connect() (e.g. legacy/test paths) still reports a concrete type.
        mgr = _manager()
        mgr.active_connections[ "sess-x" ] = MagicMock()
        assert mgr.get_session_info( "sess-x" )[ "client_type" ] == "web"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
