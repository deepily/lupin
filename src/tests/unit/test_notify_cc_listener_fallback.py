"""
Unit tests for the cross-user CC-listener fallback in `notify_user`.

Filed 2026-04-27 by USER (session b2ce9133): 3 user_initiated_messages sent
from the UI Claude Code Notifications Panel were persisted with state='created'
but never reached the CC console. Root cause: `notify_user` short-circuits
on `is_user_connected(target_system_id)=False` without trying the
`cc-listener-{job_id}` session — even though that listener IS in the WS
manager's active_connections (under a different shared service-account
user_id, hence the user-id-based connection check misses it).

Fix mirrors the cross-user fallback in send_job_message
(src/cosa/rest/routers/queues.py:986-1004).

These tests pin the new behavior so the regression cannot recur silently.
"""

from unittest.mock import MagicMock, patch
import uuid as _uuid

import pytest


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _build_mocks( *, listener_active: bool, target_user_connected: bool ):
    """Build the mock dependencies for a notify_user invocation.

    Args:
        listener_active: if True, `cc-listener-{job_id}` is in active_connections
        target_user_connected: if True, is_user_connected(target_system_id) returns True
    """
    job_id      = "b2ce9133"
    listener_id = f"cc-listener-{job_id}"

    # WS manager mock
    ws_manager = MagicMock()
    ws_manager.is_user_connected.return_value = target_user_connected
    ws_manager.get_user_connection_count.return_value = 1 if target_user_connected else 0
    ws_manager.user_sessions       = {}
    ws_manager.active_connections  = { listener_id: MagicMock() } if listener_active else {}
    ws_manager.user_to_email       = {}
    ws_manager.emit_to_session_sync = MagicMock()
    ws_manager.emit_to_user_sync    = MagicMock()

    # Helper mock — emit_to_user_or_listener_sync (new canonical dispatch helper).
    # Simulates the real behavior contract: listener_delivered iff `listener_active`,
    # user_delivered iff user_id provided AND target_user_connected.
    def _helper_side_effect( *, user_id, job_id, event, data ):
        user_delivered = bool( user_id ) and target_user_connected
        listener_delivered = bool( job_id ) and listener_active
        return {
            "user_delivered"     : user_delivered,
            "listener_delivered" : listener_delivered,
            "any_delivered"      : user_delivered or listener_delivered,
        }
    ws_manager.emit_to_user_or_listener_sync = MagicMock( side_effect=_helper_side_effect )

    # Notification queue mock
    notification_queue = MagicMock()
    notif_item = MagicMock()
    notif_item.id = "test-notif-id"
    notification_queue.push_notification.return_value = notif_item

    return ws_manager, notification_queue, job_id, listener_id


def _run_notify( ws_manager, notification_queue, job_id, **overrides ):
    """Invoke notify_user with mocked dependencies and return the result."""
    import asyncio

    from cosa.rest.routers.notifications import notify_user

    # Mock get_user_by_email to return a deterministic UUID
    target_uuid = "f71f5b8a-00b6-48a9-8284-c97c6f5a7011"

    # Mock NotificationRepository.create_notification to return a fake row
    fake_db_row = MagicMock()
    fake_db_row.id = _uuid.UUID( "00000000-0000-0000-0000-000000000001" )

    fake_repo = MagicMock()
    fake_repo.create_notification.return_value = fake_db_row
    fake_repo.update_state.return_value = None

    # Mock the get_db context manager
    fake_session = MagicMock()
    db_cm = MagicMock()
    db_cm.__enter__ = MagicMock( return_value=fake_session )
    db_cm.__exit__  = MagicMock( return_value=False )

    kwargs = {
        "authenticated_user_id" : "auth-user-id",
        "message"               : "Hello, anybody home?",
        "type"                  : "user_initiated_message",
        "priority"              : "medium",
        "target_user"           : "claude.code@lookml.deepily.ai",
        "response_requested"    : False,
        "response_type"         : None,
        "timeout_seconds"       : 120,
        "response_default"      : None,
        "title"                 : None,
        "sender_id"             : "ricardo.felipe.ruiz@gmail.com",
        "response_options"      : None,
        "abstract"              : None,
        "job_id"                : job_id,
        "queue_name"            : None,
        "suppress_ding"         : False,
        "progress_group_id"     : None,
        "prediction_hint_override": None,
        "display_qualifier_widget": False,
        "session_name"          : None,
        "idempotency_key"       : None,
        "notification_queue"    : notification_queue,
        "ws_manager"            : ws_manager,
    }
    kwargs.update( overrides )

    # Patch targets:
    #   - get_user_by_email: lazy-imported inside notify_user via
    #     `from cosa.rest.user_service import get_user_by_email` — patch at SOURCE.
    #   - NotificationRepository / get_db: imported at module level in
    #     notifications.py — patch at the router's module path.
    #   - fastapi_app.main: lazy-imported inside the function body for the
    #     diagnostic block. Mock via sys.modules so the import succeeds and
    #     app_debug/app_verbose are False (skips the verbose dump).
    with patch( "cosa.rest.user_service.get_user_by_email",
                return_value={ "id": target_uuid, "email": "claude.code@lookml.deepily.ai" } ), \
         patch( "cosa.rest.routers.notifications.NotificationRepository",
                return_value=fake_repo ), \
         patch( "cosa.rest.routers.notifications.get_db",
                return_value=db_cm ), \
         patch.dict( "sys.modules", { "fastapi_app.main": MagicMock( app_debug=False, app_verbose=False ) } ):
        return asyncio.run( notify_user( **kwargs ) )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCcListenerFallback:
    """The user_initiated_message → cc-listener cross-user delivery fallback."""

    def test_cc_listener_fallback_fires_when_target_offline_and_listener_active( self ):
        """
        Repro for the bug filed 2026-04-27 (session b2ce9133):
        target user offline + cc-listener-{job_id} active in WS manager →
        endpoint MUST emit to that listener and return delivered_via_listener.
        """
        ws_manager, notification_queue, job_id, listener_id = _build_mocks(
            listener_active       = True,
            target_user_connected = False,
        )

        result = _run_notify( ws_manager, notification_queue, job_id )

        # Endpoint did NOT short-circuit as user_not_available
        assert result[ "status" ] == "delivered_via_listener", (
            f"Expected delivered_via_listener; got {result.get('status')!r}. "
            "Pre-fix the endpoint short-circuited on is_user_connected=False."
        )
        assert result[ "delivery_path" ]    == "cc-listener"
        assert result[ "listener_session" ] == listener_id

        # Helper was called with the right shape (post-Phase-B migration uses
        # ws_manager.emit_to_user_or_listener_sync as the single chokepoint)
        assert ws_manager.emit_to_user_or_listener_sync.called, (
            "Endpoint must invoke the canonical dispatch helper in the offline branch."
        )
        call_kwargs = ws_manager.emit_to_user_or_listener_sync.call_args.kwargs
        assert call_kwargs[ "user_id" ] is None, (
            "user_id=None is intentional in the offline branch — primary already known offline."
        )
        assert call_kwargs[ "job_id" ] == job_id
        assert call_kwargs[ "event" ]  == "notification_queue_update"
        notif = call_kwargs[ "data" ][ "notification" ]
        assert notif[ "type" ]              == "user_initiated_message"
        assert notif[ "notification_type" ] == "user_initiated_message"
        assert notif[ "job_id" ]            == job_id
        assert notif[ "message" ]           == "Hello, anybody home?"

    def test_user_not_available_when_listener_also_absent( self ):
        """
        When target user is offline AND there's no cc-listener for the job_id,
        the endpoint correctly returns user_not_available (preserves existing
        behavior). The helper IS called (it's the canonical dispatch attempt)
        but reports listener_delivered=False, so the endpoint falls through.
        """
        ws_manager, notification_queue, job_id, _ = _build_mocks(
            listener_active       = False,
            target_user_connected = False,
        )

        result = _run_notify( ws_manager, notification_queue, job_id )

        assert result[ "status" ] == "user_not_available"
        # Helper IS attempted (we have a job_id), but the mock returns all-False
        # because listener_active=False — the endpoint then falls through.
        assert ws_manager.emit_to_user_or_listener_sync.called

    def test_normal_user_path_still_fires_when_target_connected( self ):
        """
        Regression: when target user IS connected, the endpoint goes through
        the normal FIFO push path — the offline-only helper call must NOT fire
        from notify_user directly. (Phase E will migrate the FIFO emission
        path to use the helper internally, but that's a separate layer.)
        """
        ws_manager, notification_queue, job_id, _ = _build_mocks(
            listener_active       = True,   # listener also exists, but normal path takes precedence
            target_user_connected = True,
        )

        result = _run_notify( ws_manager, notification_queue, job_id )

        # Must have gone through FIFO push (status=queued), NOT listener fallback
        assert result[ "status" ] == "queued", (
            f"Expected status=queued via FIFO push; got {result.get('status')!r}. "
            "Connected-user path must take precedence over listener fallback."
        )
        assert notification_queue.push_notification.called
        # The endpoint's offline-branch helper call must NOT have fired
        # (helper is gated on `not is_connected and job_id`).
        assert not ws_manager.emit_to_user_or_listener_sync.called, (
            "Listener fallback must NOT fire when target user is connected — "
            "the FIFO push handles delivery."
        )

    def test_no_job_id_no_listener_attempt( self ):
        """
        When job_id is missing/empty, the listener fallback can't be tried at
        all. The helper is gated on `not is_connected and job_id`, so it must
        not fire. Endpoint goes straight to user_not_available.
        """
        ws_manager, notification_queue, _, _ = _build_mocks(
            listener_active       = False,
            target_user_connected = False,
        )

        result = _run_notify( ws_manager, notification_queue, job_id=None )

        assert result[ "status" ] == "user_not_available"
        # Helper is NOT called when job_id is None (gated condition)
        assert not ws_manager.emit_to_user_or_listener_sync.called

    def test_listener_emit_failure_falls_through_to_user_not_available( self ):
        """
        If the helper reports listener_delivered=False (which can happen if
        the underlying emit_to_session_sync raised an exception inside the
        helper — the helper logs it and returns False), the endpoint falls
        through to user_not_available rather than 500'ing. Persisted DB row
        remains for forensic recovery.
        """
        ws_manager, notification_queue, job_id, _ = _build_mocks(
            listener_active       = True,
            target_user_connected = False,
        )
        # Override the helper mock to simulate the helper having an internal
        # emit failure (which the helper itself swallows + logs, returning
        # all-False per its contract).
        ws_manager.emit_to_user_or_listener_sync = MagicMock( return_value={
            "user_delivered"     : False,
            "listener_delivered" : False,
            "any_delivered"      : False,
        } )

        result = _run_notify( ws_manager, notification_queue, job_id )

        assert result[ "status" ] == "user_not_available", (
            "When the helper reports listener_delivered=False, the endpoint "
            "must gracefully fall through to user_not_available — not raise 500."
        )
        # The helper WAS attempted
        assert ws_manager.emit_to_user_or_listener_sync.called


# ===========================================================================
# Phase C migration tests — lifecycle broadcasts route through the helper
# ===========================================================================

class TestLifecycleBroadcastsViaHelper:
    """
    Phase C migration (2026-04-27): the notification_expired (SSE timeout)
    and notification_responded (response submission) broadcasts now route
    through the canonical dispatch helper so CC listeners on the same job_id
    receive the lifecycle events. Pre-migration these only fired emit_to_user
    on the email-resolved user_id, missing the listener registered under a
    shared service-account user_id.
    """

    def test_notification_responded_helper_signature_is_intact( self ):
        """
        Structural check (no async invocation needed): inspect the source of
        submit_notification_response to confirm the notification_responded
        broadcast invokes emit_to_user_or_listener_sync with both user_id AND
        job_id, NOT the legacy emit_to_user single-arg call. Mirrors the
        notification_expired structural test below.

        End-to-end async-invocation testing is intentionally NOT done here —
        it's blocked by pre-existing module-state pollution where some tests
        in the full suite leave sys.modules['fastapi_app.main'] in a state
        that breaks defensive patch.dict isolation. (Same pattern documented
        in 90-phase1-execution-log.md from 2026-04-26 for the timezone test.)
        Real invocation will be exercised at integration-test tier when the
        v1.0.0 image rebuild lands.
        """
        import inspect
        from cosa.rest.routers.notifications import submit_notification_response

        src = inspect.getsource( submit_notification_response )

        assert "emit_to_user_or_listener_sync" in src, (
            "submit_notification_response must use the canonical dispatch "
            "helper (Phase C migration). If a future refactor reverts to "
            "emit_to_user, this test catches it."
        )

        # The notification_responded call site must pass job_id (regression
        # guard — pre-migration it called emit_to_user(recipient_id, ...)
        # with no listener routing).
        lines = src.split( "\n" )
        responded_idx = next(
            ( i for i, l in enumerate( lines ) if '"notification_responded"' in l ),
            None
        )
        assert responded_idx is not None, "notification_responded event emit not found"
        # Look in a window around the responded event for the helper call
        window = "\n".join( lines[ max(0, responded_idx-10) : responded_idx+5 ] )
        assert "emit_to_user_or_listener_sync" in window, (
            f"notification_responded must use emit_to_user_or_listener_sync helper. "
            f"Window:\n{window}"
        )
        assert "job_id" in window, (
            f"notification_responded helper call must pass job_id for cross-user "
            f"listener delivery. Window:\n{window}"
        )

    def test_notification_expired_helper_signature_is_intact( self ):
        """
        Structural check (no async-SSE invocation needed): inspect the source
        of notify_user to confirm the notification_expired branch invokes
        emit_to_user_or_listener_sync with both user_id AND job_id, NOT the
        legacy emit_to_user single-arg call. Catches the case where a future
        refactor accidentally reverts the helper migration.

        End-to-end SSE-timeout invocation is exercised at integration-test
        tier (out of scope for this unit test layer because it requires
        wiring asyncio.Event + StreamingResponse + actual time advancement).
        """
        import inspect
        from cosa.rest.routers.notifications import notify_user

        src = inspect.getsource( notify_user )

        # Must contain the helper-based notification_expired emission
        assert "emit_to_user_or_listener_sync" in src, (
            "notify_user must use the canonical helper for dispatch (Phase B/C migration)."
        )

        # The notification_expired call site must pass job_id (regression
        # guard — pre-migration it called emit_to_user(target_system_id, ...)
        # with no listener routing).
        # Find the line containing "notification_expired" and verify the
        # surrounding helper call passes job_id.
        lines = src.split( "\n" )
        expired_line_idx = next(
            ( i for i, l in enumerate( lines ) if '"notification_expired"' in l ),
            None
        )
        assert expired_line_idx is not None, "notification_expired event emit not found"
        # Look in a window around the expired event for the helper call
        window = "\n".join( lines[ max(0, expired_line_idx-10) : expired_line_idx+5 ] )
        assert "emit_to_user_or_listener_sync" in window, (
            f"notification_expired must use emit_to_user_or_listener_sync helper. "
            f"Window:\n{window}"
        )
        assert "job_id" in window, (
            f"notification_expired helper call must pass job_id for cross-user "
            f"listener delivery. Window:\n{window}"
        )
