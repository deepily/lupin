"""
Option B (row 97ff4426) — `answer_delivered_at` is stamped when the consumer TAKES
the frame, never when the responder merely wakes it.

WHAT MOVED, AND WHY. Setter (a) used to stamp the mark in the respond handler, the
moment `event.set()` fired, justified in its own comment as "the asking coroutine
WILL consume the value — a genuine receipt." WILL IS FUTURE TENSE. Setting an event
is a PREDICTION that the stream resumes, not evidence that it did.

WHAT THE FIELD MEANS, settled from its ONE reader rather than from preference: the
owed predicate `response_requested AND responded_at IS NOT NULL AND
answer_delivered_at IS NULL` decides whether catch-up hands the answer back. So the
mark means THE ASKING SEAT HAS IT, STOP HANDING IT BACK — not "this ask is
finished". Rio measured the fact that fixes the location: post-yield code runs when
the consumer DRAINS and does NOT run when it BREAKS EARLY, because GeneratorExit is
raised at the yield.

⚠️ AND NOT `finally`, WHICH IS THE TEMPTING PLACE — it is the only code that
survives a disconnect. It also runs on all three paths (drained, timed out, walked
away), so it would stamp the walked-away case, which is precisely the one that
still needs re-delivery. test_a_consumer_that_walks_away_leaves_the_answer_owed is
what makes that concrete: move the stamp into `finally` and it goes red while every
other case here stays green.

THIS DRIVES THE REAL GENERATOR, NOT A STAND-IN. It calls the real `notify_user`,
takes the real StreamingResponse, and advances its real `body_iterator` — the same
object uvicorn advances in production. A hand-rolled async generator would have
proved something about the fixture instead.

:7999-eligible — no DB, no server, no network.
"""

import sys
import json
import uuid
import asyncio
import unittest
from unittest.mock import Mock, MagicMock, patch

from fastapi.responses import StreamingResponse

import cosa.rest.routers.notifications as N
from cosa.rest.routers.notifications import notify_user, submit_notification_response


UID_STR = "12345678-1234-5678-1234-567812345678"
EMAIL   = "someone@example.com"


def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _ctx_db( mock_db ):
    gd = MagicMock()
    gd.return_value.__enter__.return_value = mock_db
    return gd


def _ws_manager():
    ws = Mock()
    ws.is_user_connected             = Mock( return_value=True )
    ws.get_user_connection_count     = Mock( return_value=1 )
    ws.user_sessions                 = {}
    ws.active_connections            = {}
    ws.user_to_email                 = {}
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": True } )
    ws.emit_to_user_sync             = Mock()
    return ws


def _frame( chunk ):
    return json.loads( chunk.split( "data: ", 1 )[ 1 ].strip() )


class TestTheAnswerMarkWaitsForTheConsumer( unittest.IsolatedAsyncioTestCase ):

    def _repo( self ):
        repo = Mock()
        repo.create_notification.return_value = Mock( id=uuid.uuid4() )
        return repo

    async def _open_ask( self, repo ):
        """
        Fire a real response-required ask and return its live SSE body_iterator.

        Ensures:
            - returns ( body_iterator, notification_id ) with the generator parked
              on the answer, exactly as it sits in production between the ack frame
              and the human's click
            - the notification_id comes from the ack FRAME, not from the mock, so
              the test cannot pass by agreeing with itself
        """
        with patch( "cosa.rest.user_service.get_user_by_email", return_value={ "id": UID_STR } ), \
             patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             _patch_fastapi_main( Mock( app_debug=False, app_verbose=False ) ), \
             patch( "builtins.print" ):
            out = await notify_user(
                authenticated_user_id="svc", message="Hello", type="custom",
                direction="ai_to_human", priority="medium", target_user=EMAIL,
                response_requested=True, response_type="yes_no", timeout_seconds=120,
                response_default=None, human_only=False, title=None, sender_id=None,
                response_options=None, abstract=None, job_id=None, queue_name=None,
                suppress_ding=False, progress_group_id=None, prediction_hint_override=None,
                display_qualifier_widget=False, session_name=None, idempotency_key=None,
                notification_queue=Mock(), ws_manager=_ws_manager(),
            )

        self.assertIsInstance( out, StreamingResponse )
        it  = out.body_iterator
        ack = _frame( await it.__anext__() )      # generator is now parked on the answer
        self.assertEqual( ack[ "status" ], "ack" )
        return it, ack[ "notification_id" ]

    def _answer( self, notification_id ):
        # Stands in for the human's click WITHOUT going through the respond handler,
        # so these two cases speak only to WHERE the mark is taken, not to how the
        # answer arrives. The responder's own half is guarded separately below.
        N.pending_responses[ notification_id ][ "response_data" ] = "yes"
        N.pending_responses[ notification_id ][ "event" ].set()

    # ---- the two consumer behaviours ---------------------------------------

    async def test_a_consumer_that_drains_the_stream_gets_the_answer_marked( self ):
        repo = self._repo()
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch( "builtins.print" ):
            it, nid = await self._open_ask( repo )
            try:
                self._answer( nid )
                self.assertEqual( _frame( await it.__anext__() )[ "status" ], "responded" )
                # The consumer asking for the NEXT item is what takes the frame. That
                # is the receipt, and it is where the stamp now lives.
                with self.assertRaises( StopAsyncIteration ):
                    await it.__anext__()
            finally:
                N.pending_responses.pop( nid, None )

        repo.mark_answer_delivered.assert_called_once()

    async def test_a_consumer_that_walks_away_leaves_the_answer_owed( self ):
        # 🔴 THE ARM THAT DECIDES THE LOCATION. Put the stamp in the generator's
        # `finally` and this goes red while every other case here stays green.
        repo = self._repo()
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch( "builtins.print" ):
            it, nid = await self._open_ask( repo )
            try:
                self._answer( nid )
                self.assertEqual( _frame( await it.__anext__() )[ "status" ], "responded" )
                await it.aclose()                 # the client goes away mid-stream
            finally:
                N.pending_responses.pop( nid, None )

        repo.mark_answer_delivered.assert_not_called()

    # ---- the responder's half ----------------------------------------------

    async def test_the_responder_no_longer_stamps_on_intent( self ):
        # Waking the waiter is a PREDICTION that the stream resumes. The old contract
        # treated it as a receipt; this pins that it no longer does — while keeping
        # the wake itself, which the stream still needs.
        N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None }
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR
        notif.job_id = None; notif.sender_id = "claude.code@x#abcd1234"; notif.sender_persona = "krishna"
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True

        try:
            with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
                 patch.object( N, "NotificationRepository", return_value=repo ), \
                 patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
                 patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
                 _patch_fastapi_main( Mock( config_mgr=Mock( get=Mock( return_value=300 ) ) ) ), \
                 patch( "builtins.print" ):
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" },
                    ws_manager=_ws_manager() )

            self.assertTrue( N.pending_responses[ UID_STR ][ "event" ].is_set() )   # the wake stays
            repo.mark_answer_delivered.assert_not_called()                          # the receipt does not
        finally:
            N.pending_responses.pop( UID_STR, None )


if __name__ == "__main__":
    unittest.main()
