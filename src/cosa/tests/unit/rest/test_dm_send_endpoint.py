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

import datetime
import unittest
import uuid
from unittest.mock import MagicMock, patch


# A fixed instant for deterministic EDT-stamp assertions: 21:28:46 UTC → 17:28:46 EDT.
_JUNE_UTC          = datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )
_EXPECTED_EDT_STAMP = "[2026.06.11 at 17:28:46]"


def _make_body( **overrides ):
    from cosa.rest.routers.dm import DmSendRequest
    fields = dict(
        sender_session_id = "asker-session-aaaa",
        body             = "ready for review",
        recipient_persona = "María",
        sender_persona    = "Rio",
        sender_icon       = "🌊",
        # REQUIRED since step 2 of row 12b5a766 (2026-07-27): an absent
        # sender_project is a 422 on the write path. These cases exercise
        # threading / endpoint wiring, not the project seam, so they need a VALID
        # request to reach the behavior under test. The reject contract itself is
        # pinned in src/tests/unit/test_dm_sender_project_required.py.
        sender_project    = "lupin",
    )
    fields.update( overrides )
    return DmSendRequest( **fields )


class TestExecuteDmSend( unittest.TestCase ):

    def setUp( self ):
        from cosa.rest.routers.dm import execute_dm_send
        self.execute_dm_send = execute_dm_send
        self.queue       = MagicMock()
        self.persist     = MagicMock( return_value="db-123" )
        # 2-arg seam (row 12b5a766): the core now hands the CALLER's project through.
        self.build_sender = lambda s, project=None: f"sender::{s}"

    def _run( self, resolve_result, body=None, new_id="fixed-msg-id", now_fn=None ):
        return self.execute_dm_send(
            authenticated_user_id = "user-uuid-1",
            body                  = body or _make_body(),
            notification_queue    = self.queue,
            resolve_recipient_fn  = MagicMock( return_value=resolve_result ),
            build_sender_id       = self.build_sender,
            persist_fn            = self.persist,
            new_id_fn             = lambda: new_id,
            now_fn                = now_fn,
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
        }, now_fn=lambda: _JUNE_UTC )

        self.assertEqual( out[ "http_status" ], 201 )
        self.assertEqual( out[ "message_id" ], "db-123" )      # db id wins over generated
        self.assertEqual( out[ "thread_id" ], "fixed-msg-id" ) # no thread_id supplied → new thread
        self.assertEqual( out[ "recipient_session" ], "abcdef1234567890" )
        self.assertEqual( out[ "recipient_persona" ], "María" )
        self.assertTrue( out[ "dispatched" ] )

        # The body is EDT-prefixed; the original text rides intact after the stamp.
        expected_body = f"{_EXPECTED_EDT_STAMP} ready for review"

        # persist call
        pk = self.persist.call_args.kwargs
        self.assertEqual( pk[ "direction" ], "ai_to_ai" )
        self.assertEqual( pk[ "message" ], expected_body )
        self.assertEqual( pk[ "sender_persona" ], "Rio" )
        self.assertEqual( pk[ "sender_icon" ], "🌊" )
        self.assertEqual( pk[ "thread_id" ], "fixed-msg-id" )
        self.assertEqual( pk[ "job_id" ], "abcdef12" )          # recipient session [:8]
        self.assertEqual( pk[ "sender_id" ], "sender::asker-session-aaaa" )

        # push call — SAME stamped body the recipient sees (persist + push identical).
        nk = self.queue.push_notification.call_args.kwargs
        self.assertEqual( nk[ "direction" ], "ai_to_ai" )
        self.assertEqual( nk[ "message" ], expected_body )
        self.assertEqual( nk[ "message" ], pk[ "message" ] )
        self.assertEqual( nk[ "job_id" ], "abcdef12" )
        self.assertEqual( nk[ "id" ], "db-123" )
        self.assertEqual( nk[ "sender_persona" ], "Rio" )
        self.assertEqual( nk[ "thread_id" ], "fixed-msg-id" )

    def test_edt_prefix_matches_arbiter_wrap_and_no_double_stamp( self ):
        """
        The DM stamp is VISUALLY IDENTICAL to the arbiter ping's wrap of the same
        instant (drift-lock), lands exactly once (no double-stamp), and leaves the
        original body intact — threading/persona untouched.
        """
        from cosa.utils.edt_timestamp import format_outreach_ts, resolve_tz

        self._run(
            { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" },
            now_fn = lambda: _JUNE_UTC,
        )
        sent = self.queue.push_notification.call_args.kwargs[ "message" ]

        # Drift-lock: DM body == arbiter caller's f"[{inner}] {body}" for the same instant.
        tz, _ = resolve_tz( "America/New_York" )
        arbiter_style = f"[{format_outreach_ts( _JUNE_UTC, tz )}] ready for review"
        self.assertEqual( sent, arbiter_style )
        self.assertEqual( sent, f"{_EXPECTED_EDT_STAMP} ready for review" )

        # No double-stamp: exactly one bracketed prefix.
        self.assertEqual( sent.count( "] " ), 1 )
        self.assertTrue( sent.startswith( "[" ) )

    def test_already_stamped_body_is_not_re_stamped( self ):
        """Idempotency (bug f49a8b34 / bc8d9d82): an arbiter ping arrives at
        /api/dm/send ALREADY carrying its own "[YYYY.MM.DD at HH:MM:SS]" stamp (the
        arbiter pre-stamps via _route, then pushes through this chokepoint). The DM
        stamp must NOT re-wrap it — no "[push-ts] [compose-ts]" double. The body
        passes through verbatim; persist + push stay identical."""
        already = "[2026.06.11 at 17:28:46] maria is blocking worker bob"
        self._run(
            { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" },
            body   = _make_body( body=already ),
            now_fn = lambda: _JUNE_UTC,
        )
        sent = self.queue.push_notification.call_args.kwargs[ "message" ]
        persisted = self.persist.call_args.kwargs[ "message" ]
        self.assertEqual( sent, already )                  # verbatim — no second stamp prepended
        self.assertEqual( persisted, already )             # persist + push identical
        self.assertNotIn( "] [", sent )                    # no double-bracket
        self.assertEqual( sent.count( " at " ), 1 )        # exactly ONE stamp

    def test_already_stamped_body_with_one_leading_space_is_not_re_stamped( self ):
        """Tolerate one optional leading space before the bracket (anchored at start)
        — still recognized as already-stamped → passed through, not re-wrapped."""
        already = " [2026.06.11 at 17:28:46] MANAGER-DOWN: bob"
        self._run(
            { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" },
            body   = _make_body( body=already ),
            now_fn = lambda: _JUNE_UTC,
        )
        sent = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertEqual( sent, already )
        self.assertNotIn( "] [", sent )

    def test_unstamped_body_still_gets_stamped( self ):
        """No over-correction: a body with NO leading stamp is stamped exactly once
        (preserves f35d37a1's central-stamp intent for human dm_send)."""
        self._run(
            { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" },
            body   = _make_body( body="plain text, no stamp" ),
            now_fn = lambda: _JUNE_UTC,
        )
        sent = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertEqual( sent, f"{_EXPECTED_EDT_STAMP} plain text, no stamp" )
        self.assertEqual( sent.count( " at " ), 1 )

    def test_real_now_default_when_now_fn_omitted( self ):
        """Production path: now_fn omitted → a real bracketed EDT stamp is produced."""
        import re
        self._run( { "http_status": 200, "session_id": "abcdef1234567890", "persona_name": "María" } )
        sent = self.queue.push_notification.call_args.kwargs[ "message" ]
        self.assertTrue( re.match( r"^\[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\] ready for review$", sent ) )

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
