"""
Unit tests for the notification `direction` axis + DM provenance/threading fields.

Covers the first-class columns added for notification-native AI<->AI messaging
(cosa-voice token reduction):
  - NotificationItem stores `direction` (default "ai_to_human") + sender_persona /
    sender_icon / reply_to / thread_id, and surfaces them 1:1 in to_dict().
  - NotificationFifoQueue.push_notification forwards all five to the item.
  - NotificationRepository.create_notification forwards all five to self.create.

Design: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md

Zero external dependencies — InputAndOutputTable and the DB session are mocked.
"""

import unittest
import uuid
from unittest.mock import MagicMock, patch


class TestNotificationItemDirection( unittest.TestCase ):
    """NotificationItem direction + DM fields: defaults, explicit values, to_dict 1:1."""

    def setUp( self ):
        from cosa.rest.notification_fifo_queue import NotificationItem
        self.NotificationItem = NotificationItem

    def test_direction_defaults_to_ai_to_human_and_dm_fields_none( self ):
        """Un-set direction defaults to the dominant AI->user case; DM fields None."""
        item = self.NotificationItem( message="hi" )
        self.assertEqual( item.direction, "ai_to_human" )
        self.assertIsNone( item.sender_persona )
        self.assertIsNone( item.sender_icon )
        self.assertIsNone( item.reply_to )
        self.assertIsNone( item.thread_id )

    def test_explicit_direction_and_dm_fields_stored( self ):
        """An ai_to_ai DM carries provenance + threading on the item."""
        item = self.NotificationItem(
            message        = "ready for review",
            direction      = "ai_to_ai",
            sender_persona = "María",
            sender_icon    = "🌸",
            reply_to       = "msg-123",
            thread_id      = "thread-abc",
        )
        self.assertEqual( item.direction,      "ai_to_ai" )
        self.assertEqual( item.sender_persona, "María" )
        self.assertEqual( item.sender_icon,    "🌸" )
        self.assertEqual( item.reply_to,       "msg-123" )
        self.assertEqual( item.thread_id,      "thread-abc" )

    def test_to_dict_surfaces_direction_and_dm_fields_one_to_one( self ):
        """Wire JSON keys map 1:1 to the new columns (external repr == internal)."""
        item = self.NotificationItem(
            message        = "ping",
            direction      = "human_to_ai",
            sender_persona = "Rick",
            sender_icon    = "🎙️",
            reply_to       = "r1",
            thread_id      = "t1",
        )
        d = item.to_dict()
        self.assertEqual( d[ "direction" ],      "human_to_ai" )
        self.assertEqual( d[ "sender_persona" ], "Rick" )
        self.assertEqual( d[ "sender_icon" ],    "🎙️" )
        self.assertEqual( d[ "reply_to" ],       "r1" )
        self.assertEqual( d[ "thread_id" ],      "t1" )

    def test_to_dict_defaults_present_for_standard_notification( self ):
        """A standard (AI->user) notification still carries the keys, with defaults."""
        d = self.NotificationItem( message="build done" ).to_dict()
        self.assertEqual( d[ "direction" ], "ai_to_human" )
        self.assertIsNone( d[ "sender_persona" ] )
        self.assertIsNone( d[ "thread_id" ] )


class TestPushNotificationForwardsDirection( unittest.TestCase ):
    """NotificationFifoQueue.push_notification forwards direction + DM fields."""

    def setUp( self ):
        self._io_tbl_patch = patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" )
        self._io_tbl_patch.start().return_value = MagicMock()
        from cosa.rest.notification_fifo_queue import NotificationFifoQueue
        self.queue = NotificationFifoQueue( websocket_mgr=None, emit_enabled=False )

    def tearDown( self ):
        self._io_tbl_patch.stop()

    def test_push_notification_default_direction( self ):
        item = self.queue.push_notification( message="status", type="progress", priority="low" )
        self.assertEqual( item.direction, "ai_to_human" )

    def test_push_notification_forwards_ai_to_ai_dm_fields( self ):
        item = self.queue.push_notification(
            message        = "lane done",
            type           = "user_initiated_message",
            priority       = "high",
            direction      = "ai_to_ai",
            sender_persona = "María",
            sender_icon    = "🌸",
            reply_to       = "msg-9",
            thread_id      = "th-9",
        )
        self.assertEqual( item.direction,      "ai_to_ai" )
        self.assertEqual( item.sender_persona, "María" )
        self.assertEqual( item.sender_icon,    "🌸" )
        self.assertEqual( item.reply_to,       "msg-9" )
        self.assertEqual( item.thread_id,      "th-9" )


class TestRepositoryCreateForwardsDirection( unittest.TestCase ):
    """NotificationRepository.create_notification forwards direction + DM fields."""

    def setUp( self ):
        from cosa.rest.db.repositories.notification_repository import NotificationRepository
        self.repo = NotificationRepository( MagicMock() )
        self.repo.create = MagicMock( return_value="sentinel-row" )

    def test_create_notification_defaults_direction( self ):
        self.repo.create_notification(
            sender_id    = "claude.code@lupin.deepily.ai",
            recipient_id = uuid.uuid4(),
            message      = "m",
            type         = "task",
            priority     = "medium",
        )
        kwargs = self.repo.create.call_args.kwargs
        self.assertEqual( kwargs[ "direction" ], "ai_to_human" )
        self.assertIsNone( kwargs[ "sender_persona" ] )

    def test_create_notification_forwards_dm_fields( self ):
        result = self.repo.create_notification(
            sender_id      = "claude.code@lupin.deepily.ai",
            recipient_id   = uuid.uuid4(),
            message        = "ready",
            type           = "user_initiated_message",
            priority       = "high",
            direction      = "ai_to_ai",
            sender_persona = "María",
            sender_icon    = "🌸",
            reply_to       = "msg-1",
            thread_id      = "th-1",
        )
        self.assertEqual( result, "sentinel-row" )
        kwargs = self.repo.create.call_args.kwargs
        self.assertEqual( kwargs[ "direction" ],      "ai_to_ai" )
        self.assertEqual( kwargs[ "sender_persona" ], "María" )
        self.assertEqual( kwargs[ "sender_icon" ],    "🌸" )
        self.assertEqual( kwargs[ "reply_to" ],       "msg-1" )
        self.assertEqual( kwargs[ "thread_id" ],      "th-1" )


if __name__ == "__main__":
    unittest.main()
