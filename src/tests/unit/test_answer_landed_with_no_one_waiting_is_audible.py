"""
Option D (row 97ff4426) — a human's answer that lands with nobody waiting must be
AUDIBLE at the moment it happens.

THE DEFECT THIS PINS. When `submit_notification_response` finds no live SSE waiter,
the answer is written, the row is left owed, and the asking seat does not have it.
That line used to print at INFO as:

    No SSE stream waiting for <id> (may have already completed)

⚠️ THE PARENTHESIS IS THE DEFECT, not the absence of a log line. It REASSURES the
reader at the exact moment a human's attention has been spent and thrown away. Two
different causes arrive at this branch and both were silent:
  · the ask's window closed before the human clicked — measured, notification
    6f59eb0a, answered 119s after its 300s expiry;
  · the asking client went away while its ask was still live.

WHY A CONTROL IS REQUIRED HERE. "It warns" is satisfied by a change that warns on
EVERY answer, which would be strictly worse than the defect — a warning that fires
on the happy path teaches the fleet to ignore it. So the happy-path arms below are
not decoration: they are what makes the warning mean something.

Scope: this guard is about AUDIBILITY only. It deliberately does NOT assert
anything about recovery, about `answer_delivered_at`, or about setter (a) — that
is a separate contract question (options A/B/C on the row) and is not settled here.

:7999-eligible — no DB, no server, no network, all mocked. Harness mirrors
test_late_answer_setter_a_wiring.py, which guards the neighbouring wiring.
"""

import sys
import asyncio
import unittest
from unittest.mock import Mock, MagicMock, patch

import cosa.rest.routers.notifications as N
from cosa.rest.routers.notifications import submit_notification_response


UID_STR    = "12345678-1234-5678-1234-567812345678"
LOUD       = "ANSWER LANDED WITH NO ONE WAITING"
REASSURING = "may have already completed"


def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _ctx_db( mock_db ):
    gd = MagicMock()
    gd.return_value.__enter__.return_value = mock_db
    return gd


def _ws_manager():
    ws = Mock()
    ws.emit_to_user_or_listener_sync = Mock( return_value={ "listener_delivered": True } )
    return ws


class TestAnswerLandedWithNoOneWaitingIsAudible( unittest.IsolatedAsyncioTestCase ):

    def _delivered_notif( self, sender_id, job_id=None ):
        notif = Mock(); notif.state = "delivered"; notif.recipient_id = UID_STR
        notif.job_id = job_id; notif.sender_id = sender_id; notif.sender_persona = "tiberius"
        return notif

    async def _submit_capturing_output( self, sender_id, waiter_present ):
        """
        Drive the real handler and return every line it printed.

        Requires:
            - sender_id is the asking session's sender_id string
            - waiter_present says whether a live SSE waiter is registered
        Ensures:
            - returns a list of the printed lines, joined per call
            - leaves pending_responses exactly as it found it
        """
        if waiter_present: N.pending_responses[ UID_STR ] = { "event": asyncio.Event(), "response_data": None }
        else:              N.pending_responses.pop( UID_STR, None )

        notif = self._delivered_notif( sender_id=sender_id, job_id=None )
        repo  = Mock(); repo.get_by_id.return_value = notif; repo.update_response.return_value = True
        said  = []

        try:
            with patch.object( N, "get_db", _ctx_db( Mock() ) ), \
                 patch.object( N, "NotificationRepository", return_value=repo ), \
                 patch.object( N, "get_formatted_time_display", return_value="12:00 EST" ), \
                 patch.object( N, "get_formatted_date_display", return_value="2026-06-01" ), \
                 _patch_fastapi_main( Mock( config_mgr=Mock( get=Mock( return_value=300 ) ) ) ), \
                 patch( "builtins.print", side_effect=lambda *a, **k: said.append( " ".join( str( x ) for x in a ) ) ):
                await submit_notification_response(
                    request_body={ "notification_id": UID_STR, "response_value": "yes" }, ws_manager=_ws_manager() )
        finally:
            N.pending_responses.pop( UID_STR, None )

        return said

    # ---- the defect itself -------------------------------------------------

    async def test_an_answer_with_no_waiter_is_announced_loudly( self ):
        said = await self._submit_capturing_output( "claude.code@x#abcd1234", waiter_present=False )
        loud = [ line for line in said if LOUD in line ]
        self.assertEqual( len( loud ), 1, f"expected exactly one loud line, got {len( loud )}: {said}" )

    async def test_the_loud_line_names_the_notification_and_the_asking_session( self ):
        # A warning nobody can act on is not much better than silence: it has to say
        # WHICH ask was lost and WHOSE it was, or the reader cannot go and recover it.
        said = await self._submit_capturing_output( "claude.code@x#abcd1234", waiter_present=False )
        loud = next( line for line in said if LOUD in line )
        self.assertIn( UID_STR,    loud )
        self.assertIn( "abcd1234", loud )

    async def test_the_reassuring_parenthesis_is_gone( self ):
        # Pins the specific regression: re-adding "may have already completed" would
        # restore the sentence that told the reader nothing was wrong.
        said = await self._submit_capturing_output( "claude.code@x#abcd1234", waiter_present=False )
        self.assertFalse( [ line for line in said if REASSURING in line ], said )

    async def test_a_sender_carrying_no_session_hash_is_still_announced( self ):
        # The hash8 is derived by splitting on "#" — a root session has none. The
        # warning must not silently vanish (or raise) on the one shape that has no id.
        said = await self._submit_capturing_output( "claude.code@x", waiter_present=False )
        loud = [ line for line in said if LOUD in line ]
        self.assertEqual( len( loud ), 1, said )
        self.assertIn( "unknown", loud[ 0 ] )

    # ---- the controls: this is what stops "warn on everything" passing -----

    async def test_the_happy_path_does_not_warn( self ):
        # 🔴 THE DISCRIMINATING ARM. Without it, a change that warned on EVERY answer
        # would satisfy every assertion above while being worse than the defect.
        said = await self._submit_capturing_output( "claude.code@x#abcd1234", waiter_present=True )
        self.assertFalse( [ line for line in said if LOUD in line ], said )

    async def test_the_happy_path_still_says_it_signaled_the_stream( self ):
        # The good path must keep its own line — a fix that silenced BOTH branches
        # would pass the control above for the wrong reason.
        said = await self._submit_capturing_output( "claude.code@x#abcd1234", waiter_present=True )
        self.assertTrue( [ line for line in said if "Signaled SSE stream" in line ], said )


if __name__ == "__main__":
    unittest.main()
