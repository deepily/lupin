"""
Unit tests for the /api/dm router logic (cosa.rest.routers.dm) — to genuine 100%
line + branch + function on every non-`# pragma: no cover` symbol:

    DmSendRequest / DmRespondRequest (models)
    _persist_dm_send_sync (boundary-mocked get_db + repo)
    execute_dm_send (injected resolver/persist/queue — no DB, no FastAPI)
    _serialize_dm
    execute_dm_get (bad-uuid 400 / not-found 404 / wrong-user 404 / non-DM 404 / 200)
    execute_dm_list (bad-since 400 / thread view / inbox view / limit clamp hi+lo / since passthrough)

The async route handlers (post_dm_send, post_dm_respond, get_dm, list_dms) are
`# pragma: no cover` thin I/O wiring — exercised by integration/smoke, not here.

Design: src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class TestDmRespondRequest( unittest.TestCase ):

    def test_requires_reply_to_and_thread_id( self ):
        """reply_to + thread_id are MANDATORY on a respond (unlike send)."""
        from cosa.rest.routers.dm import DmRespondRequest
        from pydantic import ValidationError

        # Missing both threading fields → invalid.
        with self.assertRaises( ValidationError ):
            DmRespondRequest( sender_session_id="s", body="b", recipient_persona="María" )

        # Empty reply_to (min_length=1) → invalid.
        with self.assertRaises( ValidationError ):
            DmRespondRequest( sender_session_id="s", body="b", reply_to="", thread_id="t" )

    def test_valid_respond_body_round_trips_fields( self ):
        from cosa.rest.routers.dm import DmRespondRequest
        req = DmRespondRequest(
            sender_session_id = "asker-1",
            body             = "yes — commit f4e0370",
            reply_to         = "m-7",
            thread_id        = "th-7",
            recipient_persona = "Tiberius",
            sender_persona    = "Clayton",
            sender_icon       = "😎",
        )
        self.assertEqual( req.reply_to, "m-7" )
        self.assertEqual( req.thread_id, "th-7" )
        self.assertEqual( req.recipient_persona, "Tiberius" )


def _send_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        sender_session_id  = "asker-session-aaaa",
        body              = "ready for review",
        recipient_persona = "María",
        sender_persona    = "Clayton",
        sender_icon       = "😎",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


# ─────────────────────────────────────────────────────────────────────────────
# _persist_dm_send_sync — boundary-mock get_db + NotificationRepository
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistDmSendSync( unittest.TestCase ):

    def test_persists_ai_to_ai_row_and_returns_str_id( self ):
        from cosa.rest.routers import dm as dm_mod

        created = MagicMock()
        created.id = uuid.UUID( "22222222-2222-2222-2222-222222222222" )
        repo = MagicMock()
        repo.create_notification.return_value = created

        # Context-manager get_db() -> session
        cm = MagicMock()
        cm.__enter__.return_value = "SESSION"
        cm.__exit__.return_value  = False

        with patch.object( dm_mod, "get_db", return_value=cm ), \
             patch.object( dm_mod, "NotificationRepository", return_value=repo ) as repo_cls:
            out = dm_mod._persist_dm_send_sync(
                sender_id         = "sender::x",
                recipient_user_id = "11111111-1111-1111-1111-111111111111",
                message           = "hello",
                direction         = "ai_to_ai",
                sender_persona    = "Clayton",
                sender_icon       = "😎",
                reply_to          = "m-1",
                thread_id         = "t-1",
                job_id            = "abcdef12",
            )

        self.assertEqual( out, "22222222-2222-2222-2222-222222222222" )
        repo_cls.assert_called_once_with( "SESSION" )
        ck = repo.create_notification.call_args.kwargs
        self.assertEqual( ck[ "direction" ], "ai_to_ai" )
        self.assertEqual( ck[ "recipient_id" ], uuid.UUID( "11111111-1111-1111-1111-111111111111" ) )
        self.assertEqual( ck[ "type" ], "user_initiated_message" )
        self.assertEqual( ck[ "thread_id" ], "t-1" )


# ─────────────────────────────────────────────────────────────────────────────
# execute_dm_send — pure core (injected resolver/persist/queue)
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteDmSend( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.routers.dm import execute_dm_send
        self.execute_dm_send = execute_dm_send
        self.queue        = MagicMock()
        self.persist      = MagicMock( return_value="db-123" )
        self.build_sender = lambda s: f"sender::{s}"

    def _run( self, resolve_result, body=None, new_id="fixed-msg-id" ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body or _send_body(),
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value=resolve_result ),
            build_sender_id       = self.build_sender,
            persist_fn            = self.persist,
            new_id_fn             = lambda: new_id,
        )

    def test_unresolved_recipient_returns_422_no_side_effects( self ):
        out = self._run( { "http_status": 422, "detail": { "error": "recipient_not_found" } } )
        self.assertEqual( out[ "http_status" ], 422 )
        self.persist.assert_not_called()
        self.queue.push_notification.assert_not_called()

    def test_happy_path_persists_and_pushes_ai_to_ai( self ):
        out = self._run( { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" } )
        self.assertEqual( out[ "http_status" ], 201 )
        self.assertEqual( out[ "message_id" ], "db-123" )
        self.assertEqual( out[ "thread_id" ], "fixed-msg-id" )
        self.assertTrue( out[ "dispatched" ] )
        pk = self.persist.call_args.kwargs
        self.assertEqual( pk[ "direction" ], "ai_to_ai" )
        self.assertEqual( pk[ "job_id" ], "abcdef12" )
        self.assertEqual( pk[ "sender_id" ], "sender::asker-session-aaaa" )

    def test_supplied_thread_id_preserved( self ):
        out = self._run(
            { "http_status": 200, "session_id": "sess0001xxxx", "persona_name": "María" },
            body = _send_body( thread_id="conv-99", reply_to="msg-7" ),
        )
        self.assertEqual( out[ "thread_id" ], "conv-99" )
        self.assertEqual( self.persist.call_args.kwargs[ "reply_to" ], "msg-7" )

    def test_persist_none_falls_back_to_generated_id( self ):
        self.persist.return_value = None
        out = self._run( { "http_status": 200, "session_id": "sess0002xxxx", "persona_name": None } )
        self.assertEqual( out[ "message_id" ], "fixed-msg-id" )
        self.assertEqual( self.queue.push_notification.call_args.kwargs[ "id" ], "fixed-msg-id" )

    def test_default_new_id_fn_branch( self ):
        """new_id_fn=None path: exercises the default uuid4 lambda assignment."""
        out = self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = _send_body( thread_id="keep-thread" ),
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value={ "http_status": 200, "session_id": "abcdef1234", "persona_name": "X" } ),
            build_sender_id       = self.build_sender,
            persist_fn            = self.persist,
        )  # new_id_fn omitted → default branch
        self.assertEqual( out[ "thread_id" ], "keep-thread" )


# ─────────────────────────────────────────────────────────────────────────────
# _serialize_dm
# ─────────────────────────────────────────────────────────────────────────────

def _notif( **kw ):
    base = dict(
        id             = uuid.UUID( "33333333-3333-3333-3333-333333333333" ),
        thread_id      = "th-1",
        reply_to       = "m-0",
        sender_id      = "claude.code@lupin#aaaa",
        sender_persona = "Tiberius",
        sender_icon    = "👑",
        message        = "the body",
        direction      = "ai_to_ai",
        state          = "created",
        job_id         = "abcd1234",
        recipient_id   = uuid.UUID( "11111111-1111-1111-1111-111111111111" ),
        created_at     = datetime( 2026, 6, 17, 1, 0, 0, tzinfo=timezone.utc ),
    )
    base.update( kw )
    return SimpleNamespace( **base )


class TestSerializeDm( unittest.TestCase ):

    def test_serializes_all_fields_with_iso_timestamp( self ):
        from cosa.rest.routers.dm import _serialize_dm
        out = _serialize_dm( _notif() )
        self.assertEqual( out[ "message_id" ], "33333333-3333-3333-3333-333333333333" )
        self.assertEqual( out[ "body" ], "the body" )
        self.assertEqual( out[ "thread_id" ], "th-1" )
        self.assertEqual( out[ "created_at" ], "2026-06-17T01:00:00+00:00" )

    def test_none_created_at_serializes_to_none( self ):
        from cosa.rest.routers.dm import _serialize_dm
        out = _serialize_dm( _notif( created_at=None ) )
        self.assertIsNone( out[ "created_at" ] )


# ─────────────────────────────────────────────────────────────────────────────
# execute_dm_get
# ─────────────────────────────────────────────────────────────────────────────

_USER = "11111111-1111-1111-1111-111111111111"


class TestExecuteDmGet( unittest.TestCase ):

    def _run( self, message_id, fetched, user=_USER ):
        from cosa.rest.routers.dm import execute_dm_get
        return execute_dm_get(
            message_id            = message_id,
            authenticated_user_id = user,
            fetch_fn              = MagicMock( return_value=fetched ),
        )

    def test_invalid_uuid_returns_400( self ):
        out = self._run( "not-a-uuid", None )
        self.assertEqual( out[ "http_status" ], 400 )

    def test_not_found_returns_404( self ):
        out = self._run( "33333333-3333-3333-3333-333333333333", None )
        self.assertEqual( out[ "http_status" ], 404 )

    def test_wrong_recipient_returns_404( self ):
        other = _notif( recipient_id=uuid.UUID( "99999999-9999-9999-9999-999999999999" ) )
        out = self._run( "33333333-3333-3333-3333-333333333333", other )
        self.assertEqual( out[ "http_status" ], 404 )

    def test_non_dm_direction_returns_404( self ):
        not_dm = _notif( direction="ai_to_human" )
        out = self._run( "33333333-3333-3333-3333-333333333333", not_dm )
        self.assertEqual( out[ "http_status" ], 404 )

    def test_found_dm_returns_200_serialized( self ):
        out = self._run( "33333333-3333-3333-3333-333333333333", _notif() )
        self.assertEqual( out[ "http_status" ], 200 )
        self.assertEqual( out[ "body" ], "the body" )
        self.assertEqual( out[ "sender_persona" ], "Tiberius" )


# ─────────────────────────────────────────────────────────────────────────────
# execute_dm_list
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteDmList( unittest.TestCase ):

    def _run( self, thread_id=None, since=None, limit=50 ):
        from cosa.rest.routers.dm import execute_dm_list
        self.thread_fn = MagicMock( return_value=[ _notif( message="a" ), _notif( message="b" ) ] )
        self.inbox_fn  = MagicMock( return_value=[ _notif( message="inbox" ) ] )
        return execute_dm_list(
            thread_id             = thread_id,
            since                 = since,
            limit                 = limit,
            authenticated_user_id = _USER,
            thread_fn             = self.thread_fn,
            inbox_fn              = self.inbox_fn,
        )

    def test_bad_since_returns_400( self ):
        out = self._run( since="not-a-timestamp" )
        self.assertEqual( out[ "http_status" ], 400 )

    def test_thread_view_uses_thread_fn( self ):
        out = self._run( thread_id="th-9" )
        self.assertEqual( out[ "http_status" ], 200 )
        self.assertEqual( out[ "count" ], 2 )
        self.assertEqual( out[ "thread_id" ], "th-9" )
        self.thread_fn.assert_called_once()
        self.inbox_fn.assert_not_called()
        self.assertEqual( self.thread_fn.call_args.kwargs[ "thread_id" ], "th-9" )

    def test_inbox_view_uses_inbox_fn( self ):
        out = self._run( thread_id=None )
        self.assertEqual( out[ "count" ], 1 )
        self.inbox_fn.assert_called_once()
        self.thread_fn.assert_not_called()

    def test_since_parsed_and_passed_through( self ):
        out = self._run( thread_id="th-1", since="2026-06-17T00:00:00+00:00" )
        passed = self.thread_fn.call_args.kwargs[ "since" ]
        self.assertEqual( passed, datetime( 2026, 6, 17, 0, 0, 0, tzinfo=timezone.utc ) )
        self.assertEqual( out[ "since" ], "2026-06-17T00:00:00+00:00" )

    def test_limit_clamped_to_max( self ):
        self._run( thread_id="th-1", limit=10_000 )
        self.assertEqual( self.thread_fn.call_args.kwargs[ "limit" ], 200 )

    def test_limit_clamped_to_min( self ):
        self._run( thread_id="th-1", limit=0 )
        self.assertEqual( self.thread_fn.call_args.kwargs[ "limit" ], 1 )


if __name__ == "__main__":
    unittest.main()
