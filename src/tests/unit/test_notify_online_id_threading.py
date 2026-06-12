"""
Unit tests for DB-id threading on the fire-and-forget ONLINE delivery path.

Cold-load hydration fix (2026-06-11, design note
src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md §4):
the multiplexer dedupes hydrated history rows against live WS frames BY ID,
which only works when the live frame's id/id_hash equals the persisted DB row
UUID. The response-required path already threads `id = notification_id` ("Use
database ID for consistency") and the offline cc-listener frame already stamps
`db_notification_id` — the fire-and-forget ONLINE path was the one omission
(push_notification was called without `id=`, minting a fresh uuid4 per frame).

These tests pin BOTH arms of the fix (Tiberius's APPROVE condition):
  1. persist succeeded  → push_notification receives id == the DB row UUID
  2. persist failed     → push_notification receives id=None (NotificationItem
                          falls back to a generated uuid4 — prior behavior) and
                          the push still succeeds (persist is non-fatal by design)

Harness mirrors src/tests/unit/test_notify_cc_listener_fallback.py (the
established router-level notify_user mock pattern — patch get_user_by_email at
source, NotificationRepository/get_db at the router module path, lupin_app.main
via sys.modules).
"""

from unittest.mock import MagicMock, patch
import uuid as _uuid

import pytest


DB_ROW_UUID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _build_mocks():
    """Build mock ws_manager + notification_queue for an ONLINE target user."""
    ws_manager = MagicMock()
    ws_manager.is_user_connected.return_value       = True
    ws_manager.get_user_connection_count.return_value = 1
    ws_manager.user_sessions      = {}
    ws_manager.active_connections = {}
    ws_manager.user_to_email      = {}

    notification_queue = MagicMock()
    notif_item = MagicMock()
    notif_item.id = "queued-item-id"
    notification_queue.push_notification.return_value = notif_item

    return ws_manager, notification_queue


def _run_notify( ws_manager, notification_queue, *, persist_raises: bool ):
    """
    Invoke notify_user (fire-and-forget, target online) with mocked deps.

    Requires:
        - persist_raises selects the persist-failure arm when True

    Ensures:
        - returns the endpoint's response dict
    """
    import asyncio

    from cosa.rest.routers.notifications import notify_user

    target_uuid = "f71f5b8a-00b6-48a9-8284-c97c6f5a7011"

    fake_db_row    = MagicMock()
    fake_db_row.id = _uuid.UUID( DB_ROW_UUID )

    fake_repo = MagicMock()
    if persist_raises:
        fake_repo.create_notification.side_effect = RuntimeError( "simulated DB outage" )
    else:
        fake_repo.create_notification.return_value = fake_db_row
    fake_repo.update_state.return_value = None

    fake_session = MagicMock()
    db_cm = MagicMock()
    db_cm.__enter__ = MagicMock( return_value=fake_session )
    db_cm.__exit__  = MagicMock( return_value=False )

    kwargs = {
        "authenticated_user_id"   : "auth-user-id",
        "message"                 : "[E2E-CARDGAP] simulated arbiter stall warning",
        "type"                    : "alert",
        "priority"                : "medium",
        "target_user"             : "interactive.job.tester@example.com",
        "response_requested"      : False,
        "response_type"           : None,
        "timeout_seconds"         : 120,
        "response_default"        : None,
        "title"                   : None,
        "sender_id"               : "lupin-arbiter-app-8001",
        "response_options"        : None,
        "abstract"                : None,
        "job_id"                  : None,
        "queue_name"              : None,
        "suppress_ding"           : False,
        "progress_group_id"       : None,
        "prediction_hint_override": None,
        "display_qualifier_widget": False,
        "session_name"            : None,
        "idempotency_key"         : None,
        "notification_queue"      : notification_queue,
        "ws_manager"              : ws_manager,
    }

    with patch( "cosa.rest.user_service.get_user_by_email",
                return_value={ "id": target_uuid, "email": "interactive.job.tester@example.com" } ), \
         patch( "cosa.rest.routers.notifications.NotificationRepository",
                return_value=fake_repo ), \
         patch( "cosa.rest.routers.notifications.get_db",
                return_value=db_cm ), \
         patch.dict( "sys.modules", { "lupin_app.main": MagicMock( app_debug=False, app_verbose=False ) } ):
        return asyncio.run( notify_user( **kwargs ) )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOnlinePathDbIdThreading:
    """Fire-and-forget online delivery threads the persisted DB id into the live frame."""

    def test_persist_success_threads_db_uuid_into_push_notification( self ):
        """
        Arm 1 (the fix): persist succeeded → the live NotificationItem MUST be
        created with id == the DB row UUID, so the WS frame's id/id_hash equals
        the row the multiplexer hydrates on next cold load (id-keyed dedupe).
        Pre-fix, push_notification was called WITHOUT id= and minted a fresh
        uuid4 — the live-frame/DB-row identity split.
        """
        ws_manager, notification_queue = _build_mocks()

        result = _run_notify( ws_manager, notification_queue, persist_raises=False )

        assert result[ "status" ] == "queued"
        assert notification_queue.push_notification.called
        call_kwargs = notification_queue.push_notification.call_args.kwargs
        assert "id" in call_kwargs, (
            "push_notification must receive the id kwarg on the online path "
            "(pre-fix omission = fresh uuid4 per frame, breaking id-keyed dedupe)."
        )
        assert call_kwargs[ "id" ] == DB_ROW_UUID
        # The frame's other identity-adjacent fields are unchanged.
        assert call_kwargs[ "sender_id" ] == "lupin-arbiter-app-8001"
        assert call_kwargs[ "message" ]   == "[E2E-CARDGAP] simulated arbiter stall warning"

    def test_persist_failure_degrades_to_generated_id_and_still_queues( self ):
        """
        Arm 2 (Tiberius's APPROVE condition): persist failed (non-fatal by
        design) → db_notification_id is None → push_notification receives
        id=None, NotificationItem falls back to a generated uuid4 (prior
        behavior), and the notification still queues for live delivery.
        """
        ws_manager, notification_queue = _build_mocks()

        result = _run_notify( ws_manager, notification_queue, persist_raises=True )

        assert result[ "status" ] == "queued", (
            "Persist failure must NOT break live delivery — FIFO queue is the "
            "primary delivery mechanism."
        )
        assert notification_queue.push_notification.called
        call_kwargs = notification_queue.push_notification.call_args.kwargs
        assert call_kwargs[ "id" ] is None, (
            "On persist failure the id kwarg must be None so NotificationItem "
            "generates its own uuid4 (exact prior behavior)."
        )
