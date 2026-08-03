"""
Late-answer handback — the setter-(a) + emit-routing wiring guards (§4.3).

These two tests were lifted OUT of test_notifications_router_coverage.py so they
land in the SAME commit as the notifications.py wiring they guard (the
`job_id = notification_job_id or asker_hash8` emit line + the SSE-waiter
receipt-gated `_mark_answer_delivered_sync` call). A test that fails only because
its subject has not been committed yet is not a defect — it is a test that arrived
a commit early; keeping it beside its code prevents that.

Self-contained (no cross-test-module imports): mirrors the minimal
notify-router test harness. :7999-eligible — no DB, no server, all mocked.
"""

import sys
import uuid
import asyncio
import unittest
from unittest.mock import Mock, MagicMock, patch

import cosa.rest.routers.notifications as N
from cosa.rest.routers.notifications import submit_notification_response


UID_STR = "12345678-1234-5678-1234-567812345678"


def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _ctx_db( mock_db ):
    gd = MagicMock()
    gd.return_value.__enter__.return_value = mock_db
    return gd


def _ws_manager( listener_delivered=True ):
    ws = Mock()
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": listener_delivered } )
    return ws


class TestSetterAAndRoutingWiring( unittest.IsolatedAsyncioTestCase ):
    """
    C-V4 (routing) + setter-(a) (receipt gate). Red-proofs, both actually run in
    the implementer session: delete `or asker_hash8` → cv4 red; make the mark fire
    unconditionally → the receipt gate red.
    """

    def _delivered_notif( self, sender_id, job_id=None ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR
        notif.job_id = job_id; notif.sender_id = sender_id; notif.sender_persona = "tiberius"
        return notif

    async def _submit( self, ws, repo ):
        with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
             patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
             _patch_fastapi_main( Mock( config_mgr=Mock( get=Mock( return_value=300 ) ) ) ), \
             patch( "builtins.print" ):
            return await submit_notification_response(
                request_body={ "notification_id": UID_STR, "response_value": "yes" }, ws_manager=ws )

    async def test_cv4_emit_routes_on_asker_hash8_when_no_job_id( self ):
        N.pending_responses.pop( UID_STR, None )   # no live SSE waiter
        notif = self._delivered_notif( sender_id="claude.code@x#abcd1234", job_id=None )
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        ws = _ws_manager()
        out = await self._submit( ws, repo )
        self.assertEqual( out[ "status" ], "success" )
        # The emit fell back to the asking session's #hash8 (fact-1 live fix).
        self.assertEqual( ws.emit_to_user_or_listener_sync.call_args.kwargs[ "job_id" ], "abcd1234" )

    async def test_setter_a_marks_delivered_only_when_sse_waiter_woken( self ):
        # WITH a live SSE waiter → the wake IS the receipt → mark_answer_delivered fires.
        N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None }
        notif = self._delivered_notif( sender_id="claude.code@x#abcd1234", job_id="dr-1" )
        repo = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        try:
            await self._submit( _ws_manager(), repo )
            self.assertTrue( N.pending_responses[ UID_STR ][ "event" ].is_set() )
            repo.mark_answer_delivered.assert_called_once()
        finally:
            N.pending_responses.pop( UID_STR, None )


if __name__ == "__main__":
    unittest.main()
