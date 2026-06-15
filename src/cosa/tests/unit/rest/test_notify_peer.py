"""
Unit tests for execute_notify_peer — notification-native AI↔AI DM core logic.

Covers the pure-logic path (resolver + persist + queue are injected, so no DB /
no FastAPI): recipient-unresolved 422 pass-through, the happy-path persist+push
with direction='ai_to_ai' + provenance + threading, and thread_id defaulting.

Design: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
"""

import unittest
from unittest.mock import MagicMock


def _make_body( **overrides ):
    from cosa.rest.routers.notifications import NotifyPeerRequest
    fields = dict(
        asker_session_id = "asker-session-aaaa",
        body             = "ready for review",
        recipient_persona = "María",
        sender_persona    = "Rio",
        sender_icon       = "🌊",
    )
    fields.update( overrides )
    return NotifyPeerRequest( **fields )


class TestExecuteNotifyPeer( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.routers.notifications import execute_notify_peer
        self.execute_notify_peer = execute_notify_peer
        self.queue       = MagicMock()
        self.persist     = MagicMock( return_value="db-123" )
        self.build_sender = lambda s: f"sender::{s}"

    def _run( self, resolve_result, body=None, new_id="fixed-msg-id" ):
        return self.execute_notify_peer(
            authenticated_user_id = "user-uuid-1",
            body                  = body or _make_body(),
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value=resolve_result ),
            build_sender_id       = self.build_sender,
            persist_fn            = self.persist,
            new_id_fn             = lambda: new_id,
        )

    def test_unresolved_recipient_returns_422_no_side_effects( self ):
        """A 422 from the resolver passes through unchanged; nothing persisted/pushed."""
        out = self._run( { "http_status": 422, "detail": { "error": "recipient_not_found" } } )
        self.assertEqual( out[ "http_status" ], 422 )
        self.assertEqual( out[ "detail" ][ "error" ], "recipient_not_found" )
        self.persist.assert_not_called()
        self.queue.push_notification.assert_not_called()

    def test_happy_path_persists_and_pushes_ai_to_ai( self ):
        """201: persist + push carry direction='ai_to_ai', provenance, job_id routing."""
        out = self._run( {
            "http_status" : 200,
            "session_id"  : "abcdef1234567890",
            "persona_name": "María",
        } )

        self.assertEqual( out[ "http_status" ], 201 )
        self.assertEqual( out[ "message_id" ], "db-123" )      # db id wins over generated
        self.assertEqual( out[ "thread_id" ], "fixed-msg-id" ) # no thread_id supplied → new thread
        self.assertEqual( out[ "recipient_session" ], "abcdef1234567890" )
        self.assertEqual( out[ "recipient_persona" ], "María" )
        self.assertTrue( out[ "dispatched" ] )

        # persist call
        pk = self.persist.call_args.kwargs
        self.assertEqual( pk[ "direction" ], "ai_to_ai" )
        self.assertEqual( pk[ "message" ], "ready for review" )
        self.assertEqual( pk[ "sender_persona" ], "Rio" )
        self.assertEqual( pk[ "sender_icon" ], "🌊" )
        self.assertEqual( pk[ "thread_id" ], "fixed-msg-id" )
        self.assertEqual( pk[ "job_id" ], "abcdef12" )          # recipient session [:8]
        self.assertEqual( pk[ "sender_id" ], "sender::asker-session-aaaa" )

        # push call
        nk = self.queue.push_notification.call_args.kwargs
        self.assertEqual( nk[ "direction" ], "ai_to_ai" )
        self.assertEqual( nk[ "message" ], "ready for review" )
        self.assertEqual( nk[ "job_id" ], "abcdef12" )
        self.assertEqual( nk[ "id" ], "db-123" )
        self.assertEqual( nk[ "sender_persona" ], "Rio" )
        self.assertEqual( nk[ "thread_id" ], "fixed-msg-id" )

    def test_supplied_thread_id_is_preserved( self ):
        """A reply carries an existing thread_id → it is NOT overwritten."""
        out = self._run(
            { "http_status": 200, "session_id": "sess0001xxxx", "persona_name": "María" },
            body = _make_body( thread_id="conv-99", reply_to="msg-7" ),
        )
        self.assertEqual( out[ "thread_id" ], "conv-99" )
        self.assertEqual( self.persist.call_args.kwargs[ "thread_id" ], "conv-99" )
        self.assertEqual( self.persist.call_args.kwargs[ "reply_to" ], "msg-7" )
        self.assertEqual( self.queue.push_notification.call_args.kwargs[ "reply_to" ], "msg-7" )

    def test_persist_returning_none_falls_back_to_generated_message_id( self ):
        """If persistence fails (None id), the generated message_id still routes the push."""
        self.persist.return_value = None
        out = self._run( { "http_status": 200, "session_id": "sess0002xxxx", "persona_name": None } )
        self.assertEqual( out[ "message_id" ], "fixed-msg-id" )
        self.assertEqual( self.queue.push_notification.call_args.kwargs[ "id" ], "fixed-msg-id" )


if __name__ == "__main__":
    unittest.main()
