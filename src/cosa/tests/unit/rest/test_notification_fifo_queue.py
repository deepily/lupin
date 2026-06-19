"""
Unit tests for NotificationFifoQueue with comprehensive mocking.

Focused coverage for behaviors that caused the `POST /api/notifications/{id}/played`
500 regression (AttributeError on `_emit_queue_update`) and the accompanying
broadcast contract.

Zero external dependencies — WebSocket manager and InputAndOutputTable are mocked.
"""

import time
import unittest
from unittest.mock import MagicMock, patch


class TestNotificationFifoQueueMarkPlayedEmission( unittest.TestCase ):
    """
    Regression coverage for `_emit_queue_update` on NotificationFifoQueue.

    Requires:
        - `InputAndOutputTable` is patched at import time so construction never
          touches a real database

    Ensures:
        - `mark_played()` runs end-to-end without raising AttributeError
        - `websocket_mgr.emit` is called exactly once with the contract payload
          (`queue_name`, `value`, `unplayed_count`)
        - No-op emission when `websocket_mgr=None` or `emit_enabled=False`
        - `unplayed_count` reflects state AFTER the mark (played items excluded)
    """

    def setUp( self ):
        # Patch InputAndOutputTable so queue construction doesn't hit DB layers.
        self._io_tbl_patch = patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" )
        self._mock_io_tbl_cls = self._io_tbl_patch.start()
        self._mock_io_tbl_cls.return_value = MagicMock()

        from cosa.rest.notification_fifo_queue import NotificationFifoQueue, NotificationItem
        self.NotificationFifoQueue = NotificationFifoQueue
        self.NotificationItem      = NotificationItem

        self.mock_ws = MagicMock()

    def tearDown( self ):
        self._io_tbl_patch.stop()

    def _push( self, queue, message, priority="medium", user_id="u1" ):
        """Helper: push a notification through the public API."""
        return queue.push_notification(
            message=message,
            type="task",
            priority=priority,
            user_id=user_id
        )

    def test_mark_played_does_not_raise_attribute_error( self ):
        """
        Regression: `mark_played` used to call `self._emit_queue_update()`,
        a method that did not exist on NotificationFifoQueue or its parent,
        producing AttributeError → HTTP 500 on `POST /played`.
        """
        queue = self.NotificationFifoQueue( websocket_mgr=self.mock_ws, emit_enabled=True )
        notif = self._push( queue, "test message" )

        # Reset emit mock so we only count the mark_played emission
        self.mock_ws.emit.reset_mock()

        result = queue.mark_played( notif.id_hash )

        self.assertTrue( result, "mark_played should return True for existing notification" )
        self.assertTrue( notif.played, "notification should be flagged as played" )

    def test_mark_played_emits_notification_queue_update( self ):
        """`mark_played` must broadcast a `notification_queue_update` event."""
        queue  = self.NotificationFifoQueue( websocket_mgr=self.mock_ws, emit_enabled=True )
        notif1 = self._push( queue, "first" )
        self._push( queue, "second" )  # leave this one unplayed

        self.mock_ws.emit.reset_mock()
        queue.mark_played( notif1.id_hash )

        # Exactly one emit call from `_emit_queue_update`
        self.assertEqual( self.mock_ws.emit.call_count, 1 )

        event_name, event_data = self.mock_ws.emit.call_args[ 0 ]
        self.assertEqual( event_name, "notification_queue_update" )
        self.assertEqual( event_data[ "queue_name" ],     "notification" )
        self.assertEqual( event_data[ "value" ],          2, "queue still has 2 items after marking one played" )
        self.assertEqual( event_data[ "unplayed_count" ], 1, "only the unplayed item should remain in the count" )

    def test_mark_played_noop_when_websocket_mgr_is_none( self ):
        """No WebSocket manager ⇒ no emission, no exception."""
        queue = self.NotificationFifoQueue( websocket_mgr=None, emit_enabled=True )
        notif = self._push( queue, "test message" )

        # Should not raise AttributeError or any other error
        self.assertTrue( queue.mark_played( notif.id_hash ) )

    def test_mark_played_noop_when_emit_disabled( self ):
        """`emit_enabled=False` ⇒ method runs but does not call emit."""
        queue = self.NotificationFifoQueue( websocket_mgr=self.mock_ws, emit_enabled=False )
        notif = self._push( queue, "test message" )

        self.mock_ws.emit.reset_mock()
        self.assertTrue( queue.mark_played( notif.id_hash ) )
        self.mock_ws.emit.assert_not_called()

    def test_mark_played_unknown_id_returns_false_without_emitting( self ):
        """Unknown id ⇒ return False, do NOT emit (state did not mutate)."""
        queue = self.NotificationFifoQueue( websocket_mgr=self.mock_ws, emit_enabled=True )
        self._push( queue, "real message" )

        self.mock_ws.emit.reset_mock()
        result = queue.mark_played( "bogus-id-does-not-exist" )

        self.assertFalse( result )
        self.mock_ws.emit.assert_not_called()


class _SpyLock:
    """
    RLock wrapper that records acquisitions while delegating to a real RLock.

    Requires:
        - used only as a context manager (the `with self._lock:` idiom)

    Ensures:
        - acquire_count increments on every `with` entry
        - locking semantics are preserved (delegates to threading.RLock)
    """

    def __init__( self ):
        import threading
        self._inner        = threading.RLock()
        self.acquire_count = 0

    def __enter__( self ):
        self.acquire_count += 1
        return self._inner.__enter__()

    def __exit__( self, *args ):
        return self._inner.__exit__( *args )


class TestNotificationFifoQueuePushLocking( unittest.TestCase ):
    """
    Pin the F4 thread-safety fix (2026-06-12, async-handlers follow-up):
    NotificationFifoQueue's push()/push_notification() overrides mutate
    queue_list/queue_dict directly, bypassing the parent FifoQueue's locked
    push() — they MUST take the base `self._lock` themselves, because the
    notify route now reaches them from asyncio.to_thread worker threads while
    the consumer thread mutates the same structures.

    Ensures:
        - push() acquires the base lock around its mutation
        - push_notification() urgent path acquires the lock (scan + insert atomic)
        - push_notification() normal path acquires the lock (via overridden push)
    """

    def setUp( self ):
        self._io_tbl_patch = patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" )
        self._mock_io_tbl_cls = self._io_tbl_patch.start()
        self._mock_io_tbl_cls.return_value = MagicMock()

        from cosa.rest.notification_fifo_queue import NotificationFifoQueue, NotificationItem
        self.NotificationFifoQueue = NotificationFifoQueue
        self.NotificationItem      = NotificationItem

    def tearDown( self ):
        self._io_tbl_patch.stop()

    def _queue_with_spy_lock( self ):
        """Helper: build a queue and swap its base RLock for a recording spy."""
        queue       = self.NotificationFifoQueue( websocket_mgr=None, emit_enabled=False )
        spy         = _SpyLock()
        queue._lock = spy
        return queue, spy

    def test_push_acquires_base_lock( self ):
        """The push() override must mutate queue_list/queue_dict under self._lock."""
        queue, spy = self._queue_with_spy_lock()
        item       = self.NotificationItem( message="lock pin", type="task", priority="medium" )

        queue.push( item )

        self.assertGreaterEqual( spy.acquire_count, 1, "push() mutated the queue without taking self._lock" )
        self.assertIn( item.id_hash, queue.queue_dict )
        self.assertEqual( queue.queue_list[ -1 ], item )

    def test_push_notification_urgent_path_acquires_base_lock( self ):
        """The urgent/high insertion path (scan + insert) must run under self._lock."""
        queue, spy = self._queue_with_spy_lock()

        notification = queue.push_notification( message="urgent lock pin", type="alert", priority="urgent" )

        self.assertGreaterEqual( spy.acquire_count, 1, "urgent-path insertion ran without taking self._lock" )
        self.assertIn( notification.id_hash, queue.queue_dict )
        self.assertEqual( queue.queue_list[ 0 ], notification )

    def test_push_notification_normal_path_acquires_base_lock( self ):
        """The normal-priority path (via the push() override) must run under self._lock."""
        queue, spy = self._queue_with_spy_lock()

        notification = queue.push_notification( message="normal lock pin", type="task", priority="medium" )

        self.assertGreaterEqual( spy.acquire_count, 1, "normal-path push ran without taking self._lock" )
        self.assertIn( notification.id_hash, queue.queue_dict )
        self.assertEqual( queue.queue_list[ -1 ], notification )


def isolated_unit_test():
    """
    Run NotificationFifoQueue regression tests in complete isolation.

    Returns:
        Tuple[bool, float, str]: (success, duration, message)
    """
    start_time = time.time()

    suite    = unittest.TestLoader().loadTestsFromTestCase( TestNotificationFifoQueueMarkPlayedEmission )
    runner   = unittest.TextTestRunner( verbosity=2, stream=open( "/dev/null", "w" ) )
    result   = runner.run( suite )
    duration = time.time() - start_time

    success = result.wasSuccessful()
    message = (
        f"Ran {result.testsRun} tests; failures={len( result.failures )}, errors={len( result.errors )}"
    )
    return success, duration, message


if __name__ == "__main__":
    unittest.main( verbosity=2 )
