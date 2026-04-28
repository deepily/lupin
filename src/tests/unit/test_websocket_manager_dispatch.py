"""
Unit tests for WebSocketManager.emit_to_user_or_listener_sync — the canonical
dual-emit helper for notifications that may target a CC listener.

Background: A bug filed 2026-04-27 (session 49c27830) revealed that 6 distinct
notification dispatch sites were independently re-implementing the same
"emit to user, with optional cc-listener fallback" pattern, with subtly
different and inconsistent behavior. The helper extracts the pattern; this
test file pins its contract so future migrations can be verified against
deterministic expected behavior.

Plan: ~/.claude/plans/dazzling-napping-frost.md (2026-04-27)
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.websocket_manager import WebSocketManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws_manager(
    *,
    user_online: bool,
    listener_active: bool,
    job_id: str = "b2ce9133",
    user_id: str = "user-uuid-1",
    listener_in_user_sessions: bool = False,
):
    """Build a WebSocketManager with mocked sync emit primitives.

    Args:
        user_online: drives is_user_connected() return value
        listener_active: if True, `cc-listener-{job_id}` is in active_connections
        job_id: the job id used to derive the listener session id
        user_id: the user_id under which the user (and optionally the listener) is keyed
        listener_in_user_sessions: if True, register the cc-listener session under
            `user_sessions[user_id]` to model the local-dev case where the listener
            authenticates with the same credentials as the human user

    The two underlying primitives (emit_to_user_sync, emit_to_session_sync)
    are MagicMocks so each test can verify what was called.
    """
    # Bypass full __init__ — we just need a WebSocketManager-shaped object
    # with the helper, the primitives, and active_connections.
    mgr = WebSocketManager.__new__( WebSocketManager )

    listener_sid           = f"cc-listener-{job_id}"
    mgr.active_connections = { listener_sid: MagicMock() } if listener_active else {}

    # user_sessions is a dict mapping user_id → list of session_ids. The dispatch
    # helper reads it to detect when the listener session is already covered by
    # the user fan-out (the duplicate-emit guard).
    mgr.user_sessions = {}
    if listener_in_user_sessions:
        mgr.user_sessions[ user_id ] = [ listener_sid ]

    # Patch the primitives that the helper calls
    mgr.is_user_connected    = MagicMock( return_value=user_online )
    mgr.emit_to_user_sync    = MagicMock()
    mgr.emit_to_session_sync = MagicMock()

    return mgr


# ---------------------------------------------------------------------------
# Behavior contract — 6 rows from the plan's matrix
# ---------------------------------------------------------------------------

class TestEmitToUserOrListenerSync:

    def test_user_only_when_no_job_id( self ):
        """Online user, no job_id → only the user emit fires."""
        mgr = _make_ws_manager( user_online=True, listener_active=False )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = None,
            event   = "notification_queue_update",
            data    = { "notification": { "id": "n-1" } },
        )

        assert result == { "user_delivered": True, "listener_delivered": False, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        mgr.emit_to_session_sync.assert_not_called()

    def test_both_targets_when_user_online_and_listener_active( self ):
        """Online user + active listener → both emits fire."""
        mgr = _make_ws_manager( user_online=True, listener_active=True )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = { "notification": { "id": "n-2" } },
        )

        assert result == { "user_delivered": True, "listener_delivered": True, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        mgr.emit_to_session_sync.assert_called_once()
        # Listener emit went to the deterministic session id
        assert mgr.emit_to_session_sync.call_args.args[ 0 ] == "cc-listener-b2ce9133"

    def test_only_user_when_listener_inactive( self ):
        """Online user, job_id provided but no listener session → only user emit."""
        mgr = _make_ws_manager( user_online=True, listener_active=False )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        assert result == { "user_delivered": True, "listener_delivered": False, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        mgr.emit_to_session_sync.assert_not_called()

    def test_only_listener_when_user_offline( self ):
        """Offline user + active listener → only listener emit (the bug-fix path)."""
        mgr = _make_ws_manager( user_online=False, listener_active=True )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        assert result == { "user_delivered": False, "listener_delivered": True, "any_delivered": True }
        mgr.emit_to_user_sync.assert_not_called()
        mgr.emit_to_session_sync.assert_called_once()

    def test_neither_when_user_offline_no_job_id( self ):
        """Offline user, no job_id → no emits, all-False result."""
        mgr = _make_ws_manager( user_online=False, listener_active=False )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = None,
            event   = "notification_queue_update",
            data    = {},
        )

        assert result == { "user_delivered": False, "listener_delivered": False, "any_delivered": False }
        mgr.emit_to_user_sync.assert_not_called()
        mgr.emit_to_session_sync.assert_not_called()

    def test_neither_when_user_offline_listener_inactive( self ):
        """Offline user + job_id but no listener → no emits, all-False result."""
        mgr = _make_ws_manager( user_online=False, listener_active=False )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        assert result == { "user_delivered": False, "listener_delivered": False, "any_delivered": False }
        mgr.emit_to_user_sync.assert_not_called()
        mgr.emit_to_session_sync.assert_not_called()

    # -----------------------------------------------------------------------
    # Failure-isolation contract
    # -----------------------------------------------------------------------

    def test_user_emit_failure_does_not_block_listener( self ):
        """If emit_to_user_sync raises, the listener emit still fires + succeeds.
        Errors are logged (but not raised) per sibling sync-helper convention."""
        mgr = _make_ws_manager( user_online=True, listener_active=True )
        mgr.emit_to_user_sync.side_effect = RuntimeError( "user emit crashed" )

        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        # User emit was attempted but failed → user_delivered=False
        # Listener emit should still fire and succeed
        assert result == { "user_delivered": False, "listener_delivered": True, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        mgr.emit_to_session_sync.assert_called_once()

    def test_listener_emit_failure_does_not_block_user( self ):
        """If emit_to_session_sync raises, the user emit still fires + succeeds.
        Errors are logged (but not raised) per sibling sync-helper convention."""
        mgr = _make_ws_manager( user_online=True, listener_active=True )
        mgr.emit_to_session_sync.side_effect = RuntimeError( "listener emit crashed" )

        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        # User emit succeeded; listener emit was attempted but failed
        assert result == { "user_delivered": True, "listener_delivered": False, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        mgr.emit_to_session_sync.assert_called_once()

    # -----------------------------------------------------------------------
    # Edge cases
    # -----------------------------------------------------------------------

    def test_no_user_id_with_active_listener_only( self ):
        """user_id=None, job_id with active listener → only listener emits.
        (Hypothetical use case for system-wide events with a job context but
        no specific user owner.)"""
        mgr = _make_ws_manager( user_online=False, listener_active=True )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = None,
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = {},
        )

        assert result == { "user_delivered": False, "listener_delivered": True, "any_delivered": True }
        mgr.emit_to_user_sync.assert_not_called()
        mgr.emit_to_session_sync.assert_called_once()
        # is_user_connected should NOT be called when user_id is None
        mgr.is_user_connected.assert_not_called()

    # -----------------------------------------------------------------------
    # Duplicate-emit guard (Bug A — Session c7333045, 2026-04-28)
    # -----------------------------------------------------------------------

    def test_listener_emit_skipped_when_already_in_user_fanout( self ):
        """
        When the cc-listener session is registered under the same user_id as
        the message target (the local-dev case where the listener authenticates
        with the human user's credentials), emit_to_user_sync ALREADY fans out
        to that listener via user_sessions[user_id]. A follow-on
        emit_to_session_sync would deliver the same envelope a second time —
        producing two "Received: ..." echoes and double tmux injection per
        voice message.

        Regression guard: the helper detects the overlap up front and skips
        the targeted listener emit, but still reports listener_delivered=True
        because the user fan-out covered it.
        """
        mgr = _make_ws_manager(
            user_online               = True,
            listener_active           = True,
            listener_in_user_sessions = True,
        )
        result = mgr.emit_to_user_or_listener_sync(
            user_id = "user-uuid-1",
            job_id  = "b2ce9133",
            event   = "notification_queue_update",
            data    = { "notification": { "id": "n-dedup" } },
        )

        # User fan-out fires once and counts as listener delivery too
        assert result == { "user_delivered": True, "listener_delivered": True, "any_delivered": True }
        mgr.emit_to_user_sync.assert_called_once()
        # CRITICAL: listener-targeted emit MUST NOT fire — that's the duplicate
        mgr.emit_to_session_sync.assert_not_called()
