#!/usr/bin/env python3
"""
Unit — an ASKING client that validates to ZERO events is stored as [], and that
state must be LOUD.

The asymmetry, real in the code and chosen by nobody:

    subscribed_events absent/empty   -> ["*"]   (everything)
    subscribed_events, none valid    -> []      (nothing)

[] is defensible — the client asked for names this server does not publish. What
is not defensible is storing it silently, because the send path's permissive
`.get( session_id, ["*"] )` default NEVER fires for it: the key exists. Every
frame is then dropped while auth reports success.

Row 88347f65 is the receipt for why that matters: five mechanisms and four seats
went into the wrong layer because a drop path logged and a success path did not.
This pins the warning ungated, for the same reason as e73331c5 — the debug flag
being off is exactly the condition under which the state goes unread.

Venue: :7999 (pure unit — WebSocketManager via __new__, no config/server).
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
    mgr.available_events        = { "notification_queue_update", "job_state_transition" }
    return mgr


class TestTheStoredStateIsUnchanged:
    """The fix is the WARNING. These pin that the behaviour did not move."""

    def test_asking_for_nothing_still_gets_everything( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1" )
        assert mgr.session_subscriptions[ "sess-1" ] == [ "*" ]

    def test_asking_only_for_unknown_names_still_stores_empty( self ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", subscribed_events=[ "typo_event" ] )
        assert mgr.session_subscriptions[ "sess-1" ] == []

    def test_the_asymmetry_itself( self ):
        # The two branches side by side, which is the whole point: asking wrongly
        # is punished harder than not asking at all.
        mgr = _manager()
        mgr.connect( MagicMock(), "asks-nothing", "user-1" )
        mgr.connect( MagicMock(), "asks-wrongly", "user-1", subscribed_events=[ "typo_event" ] )
        assert mgr.session_subscriptions[ "asks-nothing" ] == [ "*" ]
        assert mgr.session_subscriptions[ "asks-wrongly" ] == []


class TestZeroValidatedIsLoud:

    def test_zero_validated_warns_and_names_the_rejected_events( self, capsys ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", subscribed_events=[ "typo_event", "another_typo" ] )
        out = capsys.readouterr().out
        assert "ZERO events" in out
        assert "EVERY frame to it will be dropped" in out
        # The rejected names must appear — a warning that does not say WHAT was
        # rejected sends the reader back to the client source to guess.
        assert "typo_event"   in out
        assert "another_typo" in out

    def test_partial_rejection_warns_without_the_zero_alarm( self, capsys ):
        mgr = _manager()
        mgr.connect(
            MagicMock(), "sess-1", "user-1",
            subscribed_events=[ "notification_queue_update", "typo_event" ]
        )
        out = capsys.readouterr().out
        assert "typo_event"  in out
        assert "unknown event" in out
        # NOT the catastrophic branch — this session still receives something.
        assert "ZERO events" not in out
        assert mgr.session_subscriptions[ "sess-1" ] == [ "notification_queue_update" ]


class TestTheWarningDoesNotCryWolf:
    """Negative controls. A warning that always fires carries no information."""

    def test_a_fully_valid_subscription_warns_about_nothing( self, capsys ):
        mgr = _manager()
        mgr.connect(
            MagicMock(), "sess-1", "user-1",
            subscribed_events=[ "notification_queue_update", "job_state_transition" ]
        )
        out = capsys.readouterr().out
        assert "ZERO events"    not in out
        assert "unknown event"  not in out

    def test_a_wildcard_subscription_warns_about_nothing( self, capsys ):
        # "*" is not in available_events and must not be counted as rejected.
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1", subscribed_events=[ "*" ] )
        out = capsys.readouterr().out
        assert "ZERO events"   not in out
        assert "unknown event" not in out
        assert mgr.session_subscriptions[ "sess-1" ] == [ "*" ]

    def test_asking_for_nothing_warns_about_nothing( self, capsys ):
        mgr = _manager()
        mgr.connect( MagicMock(), "sess-1", "user-1" )
        out = capsys.readouterr().out
        assert "ZERO events"   not in out
        assert "unknown event" not in out


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
