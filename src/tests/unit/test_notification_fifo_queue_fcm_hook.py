#!/usr/bin/env python3
"""
Unit — NotificationFifoQueue FCM wake-trigger hook (S6 §3.3).

The trigger fires on ENQUEUE at the `_emit_notification_added` chokepoint,
which BOTH paths route through (normal-priority `push()` and the urgent/high
insert inside `push_notification()`), independent of WS emission state — the
wake exists precisely for the user whose WebSocket isn't there.

Pins:
    - user-targeted notifications call maybe_send_wake( user_id ) exactly once
    - broadcast (user_id=None) notifications never wake devices
    - no service wired ⇒ silent no-op
    - a raising service never breaks the notification path
    - the hook fires even when WS emission is disabled

Venue: :7999 (pure unit — io_tbl + WS stubbed per existing convention).
"""

import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.notification_fifo_queue as nfq


def _queue( monkeypatch, fcm_wake_service=None, debug=False, verbose=False ):
    """NotificationFifoQueue with io_tbl stubbed and NO WebSocket (emission off)."""
    monkeypatch.setattr( nfq, "InputAndOutputTable", lambda **k: types.SimpleNamespace() )
    q = nfq.NotificationFifoQueue( websocket_mgr=None, emit_enabled=False,
                                   debug=debug, verbose=verbose,
                                   fcm_wake_service=fcm_wake_service )
    monkeypatch.setattr( q, "_log_to_io_tbl", lambda *a, **k: None )
    return q


class TestFcmWakeHook:

    def test_user_targeted_normal_priority_triggers_wake( self, monkeypatch ):
        service = MagicMock()
        q = _queue( monkeypatch, fcm_wake_service=service )
        q.push_notification( "hello", user_id="user-1", priority="medium" )
        service.maybe_send_wake.assert_called_once_with( "user-1" )

    def test_user_targeted_urgent_priority_triggers_wake( self, monkeypatch ):
        # The urgent/high path inserts manually and calls _emit_notification_added
        # directly — the hook must fire there too.
        service = MagicMock()
        q = _queue( monkeypatch, fcm_wake_service=service )
        q.push_notification( "fire!", user_id="user-1", priority="urgent" )
        service.maybe_send_wake.assert_called_once_with( "user-1" )

    def test_broadcast_notification_never_wakes( self, monkeypatch ):
        service = MagicMock()
        q = _queue( monkeypatch, fcm_wake_service=service )
        q.push_notification( "to everyone", user_id=None )
        service.maybe_send_wake.assert_not_called()

    def test_no_service_wired_is_silent_noop( self, monkeypatch ):
        q = _queue( monkeypatch, fcm_wake_service=None )
        notification = q.push_notification( "hello", user_id="user-1" )
        assert notification is not None   # path completed normally

    def test_raising_service_never_breaks_notification_path( self, monkeypatch, capsys ):
        service = MagicMock()
        service.maybe_send_wake.side_effect = RuntimeError( "fcm exploded" )
        q = _queue( monkeypatch, fcm_wake_service=service )
        notification = q.push_notification( "hello", user_id="user-1" )
        assert notification is not None
        assert "FCM wake trigger failed" in capsys.readouterr().out

    def test_hook_fires_even_with_ws_emission_disabled( self, monkeypatch ):
        # _queue() builds with websocket_mgr=None + emit_enabled=False; the
        # wake must fire BEFORE the emission guard returns.
        service = MagicMock()
        q = _queue( monkeypatch, fcm_wake_service=service )
        q.push_notification( "offline user", user_id="user-1" )
        service.maybe_send_wake.assert_called_once()

    def test_wake_status_logged_in_debug_verbose( self, monkeypatch, capsys ):
        service = MagicMock()
        service.maybe_send_wake.return_value = "submitted"
        q = _queue( monkeypatch, fcm_wake_service=service, debug=True, verbose=True )
        q.push_notification( "hello", user_id="user-1" )
        assert "FCM wake trigger for user user-1: submitted" in capsys.readouterr().out

    def test_one_wake_attempt_per_notification( self, monkeypatch ):
        service = MagicMock()
        q = _queue( monkeypatch, fcm_wake_service=service )
        q.push_notification( "one", user_id="user-1" )
        q.push_notification( "two", user_id="user-1" )
        assert service.maybe_send_wake.call_count == 2   # debounce lives in the service, not here


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
