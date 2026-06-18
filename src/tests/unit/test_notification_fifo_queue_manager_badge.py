#!/usr/bin/env python3
"""
Unit — NotificationFifoQueue manager-lineage badge stamp (Tiffany 2026-06-17).

Fixes the spawn-time race root-caused in a16a7281: the manager-ownership badge
was missing on a freshly-spawned worker's focus-bar icon until a full page
refresh, because `manager_persona` rode ONLY the `voice_persona_assigned`
event's payload and that single event raced to a null resolve at the worker's
spawn instant. The fix stamps top-level `manager_persona` onto EVERY CC-sender
emit at the `_emit_notification_added` chokepoint — mirroring the full-load
(senders-visible) hydration — so the worker's NEXT live notification self-heals
the badge with no refresh.

Pins:
    - CC sender (sender_id with '#') → top-level `manager_persona` stamped onto
      the broadcast envelope (resolver dict carried through verbatim)
    - root/unresolved sender → `manager_persona` stamped as None (no badge, but
      the key is present so the client knows it was evaluated)
    - non-CC sender (no '#') → NO bridge read, key NOT added
    - a raising resolver never breaks the emit path (key not added, warning printed)
    - the stamp reaches BOTH the user-targeted and broadcast emit branches

Venue: :7999 (pure unit — io_tbl + WS stubbed; resolver stubbed in sys.modules
so the test never touches a real bridge file).
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

CC_SENDER  = "claude.code@lupin.deepily.ai#newbie01"
NON_CC     = "claude.code@unknown.deepily.ai"
MGR_BADGE  = { "icon": "🦉", "color": "#FFA000", "name": "mr radio", "initial": "M" }


def _stub_resolver( monkeypatch, fn ):
    """
    Inject a fake `cosa.rest.routers.notifications` module exposing
    `_manager_persona_for_sender_id = fn`, so the deferred import inside
    `_stamp_manager_persona` resolves to our stub instead of importing the
    heavy (and at-load-time circular) real router.
    """
    fake = types.ModuleType( "cosa.rest.routers.notifications" )
    fake._manager_persona_for_sender_id = fn
    monkeypatch.setitem( sys.modules, "cosa.rest.routers.notifications", fake )


def _queue( monkeypatch, emit_enabled=True ):
    """NotificationFifoQueue with io_tbl stubbed and a MagicMock WebSocket mgr."""
    monkeypatch.setattr( nfq, "InputAndOutputTable", lambda **k: types.SimpleNamespace() )
    ws = MagicMock()
    q  = nfq.NotificationFifoQueue( websocket_mgr=ws, emit_enabled=emit_enabled, debug=False )
    monkeypatch.setattr( q, "_log_to_io_tbl", lambda *a, **k: None )
    return q, ws


def _emitted_notification( ws ):
    """Pull the notification dict out of whichever emit branch fired."""
    # Broadcast branch: emit( "notification_queue_update", event_data )
    for call in ws.emit.call_args_list:
        if call.args and call.args[ 0 ] == "notification_queue_update":
            return call.args[ 1 ][ "notification" ]
    # User-targeted branch: emit_to_user_or_listener_sync( ..., data=event_data )
    for call in ws.emit_to_user_or_listener_sync.call_args_list:
        if "data" in call.kwargs:
            return call.kwargs[ "data" ][ "notification" ]
    raise AssertionError( "no notification_queue_update emit captured" )


class TestManagerPersonaStamp:

    def test_cc_sender_stamps_resolved_badge_on_broadcast( self, monkeypatch ):
        _stub_resolver( monkeypatch, lambda sid: MGR_BADGE )
        q, ws = _queue( monkeypatch )
        q.push_notification( "worker says hi", sender_id=CC_SENDER, user_id=None )
        notif = _emitted_notification( ws )
        assert notif[ "manager_persona" ] == MGR_BADGE

    def test_cc_sender_stamps_on_user_targeted_branch( self, monkeypatch ):
        # The user_id branch routes through emit_to_user_or_listener_sync — the
        # stamp must reach that envelope too (it's the same event_data dict).
        _stub_resolver( monkeypatch, lambda sid: MGR_BADGE )
        q, ws = _queue( monkeypatch )
        q.push_notification( "worker says hi", sender_id=CC_SENDER, user_id="user-1" )
        notif = _emitted_notification( ws )
        assert notif[ "manager_persona" ] == MGR_BADGE

    def test_root_session_stamps_none( self, monkeypatch ):
        # CC sender whose resolver returns None (root / no spawned_by): the key is
        # present-but-None — evaluated, no badge.
        _stub_resolver( monkeypatch, lambda sid: None )
        q, ws = _queue( monkeypatch )
        q.push_notification( "manager speaks", sender_id=CC_SENDER, user_id=None )
        notif = _emitted_notification( ws )
        assert "manager_persona" in notif
        assert notif[ "manager_persona" ] is None

    def test_non_cc_sender_is_not_stamped( self, monkeypatch ):
        # No '#' → guarded out BEFORE any import/bridge read; key absent.
        called = { "n": 0 }
        def _resolver( sid ):
            called[ "n" ] += 1
            return MGR_BADGE
        _stub_resolver( monkeypatch, _resolver )
        q, ws = _queue( monkeypatch )
        q.push_notification( "system event", sender_id=NON_CC, user_id=None )
        notif = _emitted_notification( ws )
        assert "manager_persona" not in notif
        assert called[ "n" ] == 0, "non-CC sender must skip the resolver entirely"

    def test_raising_resolver_never_breaks_emit( self, monkeypatch, capsys ):
        def _boom( sid ):
            raise RuntimeError( "bridge read exploded" )
        _stub_resolver( monkeypatch, _boom )
        q, ws = _queue( monkeypatch )
        notif_item = q.push_notification( "worker says hi", sender_id=CC_SENDER, user_id=None )
        assert notif_item is not None, "emit path completed despite resolver failure"
        notif = _emitted_notification( ws )
        assert "manager_persona" not in notif
        assert "manager_persona stamp failed" in capsys.readouterr().out

    def test_helper_noop_on_missing_sender_id( self, monkeypatch ):
        # Direct unit of the guard: None sender_id leaves the dict untouched.
        _stub_resolver( monkeypatch, lambda sid: MGR_BADGE )
        q, _ = _queue( monkeypatch )
        d = {}
        q._stamp_manager_persona( d, None )
        assert d == {}


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
