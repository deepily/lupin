"""
Unit tests for execute_dm_send — notification-native AI↔AI DM core logic.

Covers the pure-logic path (resolver + persist + queue are injected, so no DB /
no FastAPI): recipient-unresolved 422 pass-through, the happy-path persist+push
with direction='ai_to_ai' + provenance + threading, thread_id defaulting, and
the default new_id_fn (uuid) branch. A separate class exercises the
_persist_dm_send_sync DB-boundary wrapper with get_db / NotificationRepository
patched.

Design:
    src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md (/api/dm/send namespace)
    src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md
"""

import unittest
import uuid
from unittest.mock import MagicMock, patch


def _make_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        asker_session_id = "asker-session-aaaa",
        body             = "ready for review",
        recipient_persona = "María",
        sender_persona    = "Rio",
        sender_icon       = "🌊",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


class TestExecuteDmSend( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.routers.dm import execute_dm_send
        self.execute_dm_send = execute_dm_send
        self.queue       = MagicMock()
        self.persist     = MagicMock( return_value="db-123" )
        self.build_sender = lambda s: f"sender::{s}"

    def _run( self, resolve_result, body=None, new_id="fixed-msg-id" ):
        return self.execute_dm_send(
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

    def test_default_new_id_fn_generates_uuid_thread_id( self ):
        """No new_id_fn supplied → the default uuid generator seeds a fresh thread_id."""
        out = self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = _make_body(),                 # no thread_id → new thread
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value={
                "http_status": 200, "session_id": "sess0003xxxx", "persona_name": "María",
            } ),
            build_sender_id       = self.build_sender,
            persist_fn            = self.persist,
            # new_id_fn omitted → exercises `new_id_fn = lambda: str( uuid.uuid4() )`
        )
        # message_id is the db id; thread_id is a freshly-generated uuid (not the db id)
        self.assertEqual( out[ "message_id" ], "db-123" )
        thread_id = out[ "thread_id" ]
        self.assertNotEqual( thread_id, "db-123" )
        # a parseable uuid4 string proves the default generator ran
        self.assertEqual( str( uuid.UUID( thread_id ) ), thread_id )


class TestPersistDmSendSync( unittest.TestCase ):
    """The DB-boundary wrapper: get_db context + NotificationRepository are patched."""

    def test_creates_ai_to_ai_row_and_returns_str_id( self ):
        from cosa.rest.routers import dm

        recipient_uuid = str( uuid.uuid4() )
        created        = MagicMock()
        created.id     = "row-id-42"
        repo           = MagicMock()
        repo.create_notification.return_value = created

        # get_db() is used as a context manager: `with get_db() as session:`
        ctx = MagicMock()
        ctx.__enter__.return_value = "the-session"
        ctx.__exit__.return_value  = False

        with patch.object( dm, "get_db", return_value=ctx ) as mock_get_db, \
             patch.object( dm, "NotificationRepository", return_value=repo ) as mock_repo_cls:
            out = dm._persist_dm_send_sync(
                sender_id         = "sender::s",
                recipient_user_id = recipient_uuid,
                message           = "hello",
                direction         = "ai_to_ai",
                sender_persona    = "Rio",
                sender_icon       = "🌊",
                reply_to          = "msg-1",
                thread_id         = "conv-1",
                job_id            = "abcdef12",
            )

        self.assertEqual( out, "row-id-42" )                    # str( created.id )
        mock_get_db.assert_called_once_with()
        mock_repo_cls.assert_called_once_with( "the-session" )
        ck = repo.create_notification.call_args.kwargs
        self.assertEqual( ck[ "direction" ], "ai_to_ai" )
        self.assertEqual( ck[ "type" ], "user_initiated_message" )
        self.assertEqual( ck[ "priority" ], "medium" )
        self.assertEqual( ck[ "recipient_id" ], uuid.UUID( recipient_uuid ) )
        self.assertEqual( ck[ "sender_id" ], "sender::s" )
        self.assertEqual( ck[ "message" ], "hello" )
        self.assertEqual( ck[ "job_id" ], "abcdef12" )
        self.assertEqual( ck[ "sender_persona" ], "Rio" )
        self.assertEqual( ck[ "sender_icon" ], "🌊" )
        self.assertEqual( ck[ "reply_to" ], "msg-1" )
        self.assertEqual( ck[ "thread_id" ], "conv-1" )


if __name__ == "__main__":
    unittest.main()
