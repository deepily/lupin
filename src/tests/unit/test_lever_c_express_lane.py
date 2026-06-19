"""
Lever C (express lane) regression test — messaging-coordination plane.

The express lane is the PRIORITY-BASED ordering already implemented in
NotificationFifoQueue.push_notification: `urgent`/`high` notifications are inserted
AHEAD of normal (`medium`/`low`) ones, while FIFO order is preserved within each
class. notify_user enqueues via push_notification, so an interactive high/urgent
ask is served ahead of bulk fleet/commons progress traffic.

This test PINS that ordering so the express lane can't silently regress.
Decision: priority field = express (Rick, 2026-06-02).

Venue: :7999-eligible (pure unit; stubs emission + io_tbl, no DB/WS).
"""

import types

import pytest

import cosa.rest.notification_fifo_queue as nfq


def _queue( monkeypatch ):
    """A NotificationFifoQueue with emission + io_tbl stubbed (no DB / no WebSocket)."""
    monkeypatch.setattr( nfq, "InputAndOutputTable", lambda **k: types.SimpleNamespace() )
    q = nfq.NotificationFifoQueue( websocket_mgr=None, emit_enabled=False )
    monkeypatch.setattr( q, "_emit_notification_added", lambda *a, **k: None )
    monkeypatch.setattr( q, "_log_to_io_tbl", lambda *a, **k: None )
    return q


class TestExpressLaneOrdering:

    def test_high_urgent_jump_ahead_of_normal_fifo_preserved( self, monkeypatch ):
        q = _queue( monkeypatch )
        q.push_notification( message="A", priority="low" )      # normal → end
        q.push_notification( message="B", priority="high" )     # express → front
        q.push_notification( message="C", priority="medium" )   # normal → end
        q.push_notification( message="D", priority="urgent" )   # express → after B
        q.push_notification( message="E", priority="high" )     # express → after D
        order = [ item.message for item in q.queue_list ]
        # express block (B, D, E in FIFO) ahead of normal block (A, C in FIFO)
        assert order == [ "B", "D", "E", "A", "C" ]

    def test_all_normal_is_plain_fifo( self, monkeypatch ):
        q = _queue( monkeypatch )
        for m in ( "x", "y", "z" ):
            q.push_notification( message=m, priority="medium" )
        assert [ i.message for i in q.queue_list ] == [ "x", "y", "z" ]

    def test_single_high_goes_to_front_over_existing_normals( self, monkeypatch ):
        q = _queue( monkeypatch )
        q.push_notification( message="n1", priority="low" )
        q.push_notification( message="n2", priority="medium" )
        q.push_notification( message="hi", priority="urgent" )
        assert [ i.message for i in q.queue_list ] == [ "hi", "n1", "n2" ]
