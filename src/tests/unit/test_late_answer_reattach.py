"""
Section E (MCP re-attach) — unit guards, per src/rnd/v0.1.9/2026.08.01-section-E-verification-plan.md.

⚠️ CALL-SHAPE ONLY — NOT proof the server serves the contract. The client half here is
driven with mocked SSE lines + an injected poll_fn; it proves the CLIENT parses/decides
correctly, never that the server emits the ack frame or that GET /response/{id} returns
what the client parses. That truth-proof is the :8000 integration/e2e tier (Rachel's) —
a green unit E is NOT "the server acks." (Same shape as D-V1.)

Covers: E-a (ack-frame capture + back-compat), E-b (serve-no-ack + route order),
E-c E-V1 (landed predicate), E-V2 (arming signal), E-V3 (budget≤0 edge),
E-V5 (ruling b — NO ack on poll-land).
"""

import uuid
import asyncio
from unittest.mock import Mock, patch

import pytest

from lupin_cli.notifications import notify_user_sync as nus
from lupin_cli.notifications.notify_user_sync import consume_sse_stream
from lupin_cli.notifications.notification_models import RespondedEvent
from cosa.rest.routers import notifications as N


VALID_UUID = "12345678-1234-1234-1234-123456789abc"


# ── E-a: ack-frame capture + back-compat ─────────────────────────────────────
class TestAckFrameCapture:
    def _resp( self, lines ):
        r = Mock(); r.iter_lines.return_value = lines; return r

    def test_captures_ack_id_then_returns_terminal_event( self ):
        resp = self._resp( [
            b'data: {"status": "ack", "notification_id": "N1"}',
            b'data: {"status": "responded", "response": "yes", "default_used": false}',
        ] )
        cap = {}
        event = consume_sse_stream( resp, timeout_seconds=30, ack_capture=cap )
        assert isinstance( event, RespondedEvent )     # ack frame did not swallow the terminal event
        assert cap[ "notification_id" ] == "N1"

    def test_ack_frame_is_additive_backcompat_no_capture( self ):
        # A client that passes NO ack_capture (the pre-E signature) still works — the
        # ack frame is skipped and the terminal event is returned unchanged.
        resp = self._resp( [
            b'data: {"status": "ack", "notification_id": "N1"}',
            b'data: {"status": "responded", "response": "yes", "default_used": false}',
        ] )
        event = consume_sse_stream( resp, timeout_seconds=30 )   # no ack_capture kwarg
        assert isinstance( event, RespondedEvent )
        assert event.response == "yes"


# ── E-b: response-by-id route — pure read, no ack ─────────────────────────────
def _ctx_db( repo ):
    gd = Mock()
    gd.return_value.__enter__ = Mock( return_value=Mock() )
    gd.return_value.__exit__  = Mock( return_value=False )
    return gd


class TestResponseByIdRoute:
    def _row( self, responded_at="2026-08-01T12:00:00+00:00" ):
        n = Mock()
        n.state = "responded"; n.response_value = { "value": "yes" }
        n.responded_at = Mock( isoformat=Mock( return_value=responded_at ) ) if responded_at else None
        return n

    def test_serves_state_and_does_not_ack( self ):
        repo = Mock(); repo.get_by_id.return_value = self._row()
        with patch.object( N, "get_db", _ctx_db( repo ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch.object( N, "get_local_timestamp", return_value="T" ), \
             patch( "builtins.print" ):
            out = asyncio.run( N.get_notification_response(
                authenticated_user_id="svc", notification_id=VALID_UUID ) )
        assert out[ "state" ] == "responded"
        assert out[ "response_value" ] == { "value": "yes" }
        assert out[ "responded_at" ] == "2026-08-01T12:00:00+00:00"
        # PURE READ — serving must never stamp answer_delivered_at (E-b falsifier:
        # move a mark_answer_delivered call into this handler → this assert reddens).
        repo.mark_answer_delivered.assert_not_called()

    def test_404_when_absent( self ):
        repo = Mock(); repo.get_by_id.return_value = None
        with patch.object( N, "get_db", _ctx_db( repo ) ), \
             patch.object( N, "NotificationRepository", return_value=repo ), \
             patch( "builtins.print" ):
            with pytest.raises( Exception ) as ei:
                asyncio.run( N.get_notification_response(
                    authenticated_user_id="svc", notification_id=VALID_UUID ) )
        assert getattr( ei.value, "status_code", None ) == 404

    def test_route_registered_before_user_id( self ):
        paths = [ getattr( r, "path", "" ) for r in N.router.routes ]
        resp = [ i for i, p in enumerate( paths ) if p == "/api/notifications/response/{notification_id}" ]
        uid  = [ i for i, p in enumerate( paths ) if p == "/api/notifications/{user_id}" ]
        assert resp and uid and max( resp ) < min( uid )


# ── E-c: re-attach poll (ruling b — no ack on land) ──────────────────────────
class TestReattachPoll:
    HDRS = { "X-API-Key": "k" }

    def _reattach( self, notification_id, remaining, poll_fn ):
        return nus._reattach_after_stream_death(
            notification_id, remaining, "http://x", self.HDRS,
            poll_fn=poll_fn, poll_interval=0.0
        )

    # E-V1: landed predicate — responded_at IS NOT NULL decides, never response_value alone.
    def test_ev1_responded_at_null_with_value_is_expired_default_never_responded( self ):
        poll_fn = lambda nid: { "responded_at": None, "response_value": { "value": "no" } }
        r = self._reattach( "N1", 5, poll_fn )
        assert r.status == "expired"           # a manufactured default, NOT an answer
        assert r.default_used is True
        assert r.is_timeout is True
        assert r.status != "responded"

    def test_ev1_responded_at_set_is_responded_no_default( self ):
        poll_fn = lambda nid: { "responded_at": "2026-08-01T12:00:00+00:00", "response_value": { "value": "yes" } }
        r = self._reattach( "N1", 5, poll_fn )
        assert r.status == "responded"
        assert r.response_value == "yes"
        assert r.default_used is False

    # E-V2: arming signal.
    def test_ev2_armed_when_poll_fires( self ):
        poll_fn = lambda nid: { "responded_at": "2026-08-01T12:00:00+00:00", "response_value": "yes" }
        r = self._reattach( "N1", 5, poll_fn )
        assert r.reattach_state == "reattach_armed"

    def test_ev2_unavailable_when_no_id_captured( self ):
        r = self._reattach( None, 5, lambda nid: None )
        assert r.reattach_state == "reattach_unavailable"   # surfaced LOUD, not a silent no-op

    # E-V3: budget≤0 still fires at least one terminal poll (not a bare stream_error).
    def test_ev3_budget_zero_still_polls_once_and_expires( self ):
        calls = { "n": 0 }
        def poll_fn( nid ):
            calls[ "n" ] += 1
            return { "responded_at": None, "response_value": None }   # not answered yet
        r = self._reattach( "N1", 0, poll_fn )
        assert calls[ "n" ] >= 1                 # a dying stream at the deadline still checks once
        assert r.status == "expired"
        assert r.is_timeout is True
        assert r.reattach_state == "reattach_armed"

    # E-V5 (ruling b): a LANDED answer is returned but NEVER acked here (no POST fired).
    def test_ev5_no_ack_post_on_land( self ):
        poll_fn = lambda nid: { "responded_at": "2026-08-01T12:00:00+00:00", "response_value": { "value": "yes" } }
        with patch.object( nus, "requests" ) as req:
            r = self._reattach( "N1", 5, poll_fn )
        assert r.status == "responded"
        req.post.assert_not_called()             # ruling b: no ack on land — row stays owed for catch-up
