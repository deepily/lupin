"""
Unit tests for the canonical user+admin WebSocket dual-emit pattern.

Verifies the Session 248e740e refactor that introduced
WebSocketManager.emit_to_user_and_admins_sync as the single canonical method
for queue and job state events. Before the refactor, every caller had to
remember to call BOTH emit_to_user_sync AND emit_to_admins_sync — and three
sites in routers/queues.py forgot the second call, stranding cards in admin
browsers when E2E tests cleaned up paused mock jobs.

These tests lock the contract:
    1. emit_to_user_and_admins_sync delegates to BOTH primitives with the
       right args, deduplicating the owner from the admin broadcast.
    2. emit_job_state_transition (the helper used by 28 callers across the
       queue stack) uses the canonical method when a user_id is provided,
       and falls back to a true broadcast otherwise.

Strategy:
    Use unittest.mock.MagicMock( spec=WebSocketManager ) as the receiver and
    call the method as an unbound function so we never construct a real
    WebSocketManager (which requires the LUPIN_CONFIG_MGR_CLI_ARGS env var
    and a valid config on disk). For emit_job_state_transition we pass a
    MagicMock as the websocket_mgr arg and assert against its method calls.

Reference: ~/.claude/plans/crystalline-crafting-cake.md (Session 248e740e
WebSocket emit refactor plan).
"""

import os
import sys
from unittest.mock import MagicMock, ANY

import pytest


# Bootstrap LUPIN_ROOT and add src/ to sys.path so cosa.* imports resolve
lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
src_path   = os.path.join( lupin_root, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )


# ---------------------------------------------------------------------------
# Canonical dual-emit method tests
# ---------------------------------------------------------------------------

class TestEmitToUserAndAdminsSync:
    """
    Lock the contract on WebSocketManager.emit_to_user_and_admins_sync.

    The method is called as an unbound function with a MagicMock self so we
    don't have to instantiate a real WebSocketManager (which requires config).
    """

    def _call_method( self, mock_self, user_id, event, data ):
        """Invoke the unbound canonical method with the given mock self."""
        from cosa.rest.websocket_manager import WebSocketManager
        WebSocketManager.emit_to_user_and_admins_sync( mock_self, user_id, event, data )

    def test_calls_emit_to_user_sync_with_correct_args( self ):
        """Owner gets the event via emit_to_user_sync with the exact triple."""
        mock_self = MagicMock()
        user_id   = "owner-uuid-123"
        event     = "job_removed"
        data      = { "job_id": "abc", "queue": "todo", "timestamp": "2026-04-11T12:00:00" }

        self._call_method( mock_self, user_id, event, data )

        mock_self.emit_to_user_sync.assert_called_once_with( user_id, event, data )

    def test_calls_emit_to_admins_sync_with_correct_args( self ):
        """Admins get the event via emit_to_admins_sync with the owner excluded."""
        mock_self = MagicMock()
        user_id   = "owner-uuid-456"
        event     = "job_state_transition"
        data      = { "job_id": "def", "from_state": "queued", "to_state": "paused" }

        self._call_method( mock_self, user_id, event, data )

        mock_self.emit_to_admins_sync.assert_called_once_with(
            event, data, exclude_user_id=user_id
        )

    def test_calls_both_primitives_exactly_once( self ):
        """Neither primitive is called more than once per invocation."""
        mock_self = MagicMock()

        self._call_method( mock_self, "user-789", "job_removed", { "job_id": "x" } )

        assert mock_self.emit_to_user_sync.call_count   == 1
        assert mock_self.emit_to_admins_sync.call_count == 1

    def test_calls_user_emit_before_admin_emit( self ):
        """
        Order is fixed: owner first, then admins. Predictable ordering matters
        for failure semantics — if the owner emit raises, admins shouldn't have
        already received the event in a state where the owner missed it.
        """
        mock_self = MagicMock()
        call_log  = []

        mock_self.emit_to_user_sync.side_effect   = lambda *a, **kw: call_log.append( "user" )
        mock_self.emit_to_admins_sync.side_effect = lambda *a, **kw: call_log.append( "admins" )

        self._call_method( mock_self, "u", "job_removed", {} )

        assert call_log == [ "user", "admins" ]

    def test_passes_payload_dict_unchanged( self ):
        """The data dict reaches both primitives unmodified."""
        mock_self = MagicMock()
        payload   = {
            "job_id"     : "complex-id",
            "queue"      : "todo",
            "metadata"   : { "agent_type": "mock", "nested": [ 1, 2, 3 ] },
            "timestamp"  : "2026-04-11T12:34:56-04:00",
        }

        self._call_method( mock_self, "u", "job_state_transition", payload )

        # Both calls should receive the SAME object (not a copy)
        user_args  = mock_self.emit_to_user_sync.call_args
        admin_args = mock_self.emit_to_admins_sync.call_args

        assert user_args.args[ 2 ] is payload
        assert admin_args.args[ 1 ] is payload

    def test_empty_payload_is_legal( self ):
        """An empty dict payload is allowed (some events have no metadata)."""
        mock_self = MagicMock()
        self._call_method( mock_self, "u", "job_removed", {} )
        mock_self.emit_to_user_sync.assert_called_once_with( "u", "job_removed", {} )
        mock_self.emit_to_admins_sync.assert_called_once_with(
            "job_removed", {}, exclude_user_id="u"
        )

    def test_owner_excluded_via_keyword_argument( self ):
        """
        The exclude_user_id MUST be passed as a kwarg matching the user_id, so
        emit_to_admins_sync's existing dedup logic kicks in. A positional pass
        would silently break the existing primitive's signature contract.
        """
        mock_self = MagicMock()
        self._call_method( mock_self, "owner-id", "job_removed", { "job_id": "x" } )

        admin_call = mock_self.emit_to_admins_sync.call_args
        assert "exclude_user_id" in admin_call.kwargs
        assert admin_call.kwargs[ "exclude_user_id" ] == "owner-id"


# ---------------------------------------------------------------------------
# emit_job_state_transition refactor tests
# ---------------------------------------------------------------------------

class TestEmitJobStateTransitionUsesCanonical:
    """
    After the Session 248e740e refactor, emit_job_state_transition calls the
    canonical dual-emit method when given a user_id, and falls back to a true
    broadcast (emit) when given None. The old two-call pattern is gone.
    """

    def test_uses_canonical_method_when_user_id_provided( self ):
        """With a user_id, the helper calls emit_to_user_and_admins_sync exactly once."""
        from cosa.rest.queue_util import emit_job_state_transition

        mock_ws = MagicMock()
        emit_job_state_transition(
            mock_ws,
            job_id     = "job-abc",
            from_state = "queued",
            to_state   = "running",
            user_id    = "owner-xyz",
            metadata   = None,  # avoid persistence side effects
        )

        # Canonical method called exactly once with the expected args
        mock_ws.emit_to_user_and_admins_sync.assert_called_once()
        call    = mock_ws.emit_to_user_and_admins_sync.call_args
        assert call.args[ 0 ] == "owner-xyz"
        assert call.args[ 1 ] == "job_state_transition"

        # Payload structure
        payload = call.args[ 2 ]
        assert payload[ "job_id" ]     == "job-abc"
        assert payload[ "from_state" ] == "queued"
        assert payload[ "to_state" ]   == "running"
        assert "timestamp" in payload

    def test_does_not_call_old_two_method_pattern_when_user_id_provided( self ):
        """
        Regression guard: the old pattern (emit_to_user_sync followed by
        emit_to_admins_sync at the queue_util level) is gone. Only the
        canonical method should be called from this helper.
        """
        from cosa.rest.queue_util import emit_job_state_transition

        mock_ws = MagicMock()
        emit_job_state_transition(
            mock_ws, "job-1", "queued", "running",
            user_id="owner-1", metadata=None,
        )

        # The helper itself should NOT call the underlying primitives directly
        # — the canonical method handles that internally.
        mock_ws.emit_to_user_sync.assert_not_called()
        mock_ws.emit_to_admins_sync.assert_not_called()

    def test_falls_back_to_broadcast_when_no_user_id( self ):
        """
        Without a user_id, the helper still falls back to a true broadcast via
        websocket_mgr.emit() — preserves the legacy unscoped path.
        """
        from cosa.rest.queue_util import emit_job_state_transition

        mock_ws = MagicMock()
        emit_job_state_transition(
            mock_ws, "job-broadcast", "queued", "running",
            user_id=None, metadata=None,
        )

        mock_ws.emit.assert_called_once()
        call = mock_ws.emit.call_args
        assert call.args[ 0 ] == "job_state_transition"
        assert call.args[ 1 ][ "job_id" ] == "job-broadcast"

        # Canonical method should NOT be called when there's no user_id
        mock_ws.emit_to_user_and_admins_sync.assert_not_called()

    def test_handles_websocket_mgr_none_silently( self ):
        """
        When websocket_mgr is None, the helper short-circuits the WS emission
        block (does not raise). This is the legacy contract for headless
        contexts (smoke tests, scripts) that don't have a manager available.
        """
        from cosa.rest.queue_util import emit_job_state_transition

        # Should not raise
        emit_job_state_transition(
            None, "job-headless", "queued", "running",
            user_id="u", metadata=None,
        )

    def test_swallows_exception_from_canonical_method( self ):
        """
        If the canonical method raises (e.g. main_loop unavailable), the helper
        catches and logs the error rather than propagating. This preserves the
        existing fire-and-forget contract for queue events.
        """
        from cosa.rest.queue_util import emit_job_state_transition

        mock_ws = MagicMock()
        mock_ws.emit_to_user_and_admins_sync.side_effect = RuntimeError( "main_loop missing" )

        # Should not raise
        emit_job_state_transition(
            mock_ws, "job-err", "queued", "running",
            user_id="u", metadata=None,
        )

    def test_includes_metadata_in_payload_when_provided( self ):
        """When metadata is supplied, it lands in the payload as 'metadata'."""
        from cosa.rest.queue_util import emit_job_state_transition

        mock_ws  = MagicMock()
        metadata = { "agent_type": "mock", "user_email": "owner@example.com", "scheduled_at": None }

        emit_job_state_transition(
            mock_ws, "job-meta", "queued", "running",
            user_id="u", metadata=metadata,
        )

        payload = mock_ws.emit_to_user_and_admins_sync.call_args.args[ 2 ]
        assert payload[ "metadata" ] == metadata


# ---------------------------------------------------------------------------
# Smoke: the canonical method actually exists and is bound on the class
# ---------------------------------------------------------------------------

class TestCanonicalMethodExists:
    """
    Catch the obvious 'method not added' regression at import time. If this
    test fails, the WebSocketManager edit didn't land.
    """

    def test_canonical_method_present_on_class( self ):
        from cosa.rest.websocket_manager import WebSocketManager
        assert hasattr( WebSocketManager, "emit_to_user_and_admins_sync" )

    def test_canonical_method_is_callable( self ):
        from cosa.rest.websocket_manager import WebSocketManager
        assert callable( getattr( WebSocketManager, "emit_to_user_and_admins_sync" ) )
