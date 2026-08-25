"""
`POST /api/notify` says whether it actually delivered — row `fcc74307`.

THE DEFECT, and it is not the one the row was filed about. john found that a
notification to a disconnected user returns 200 and never arrives, and filed it
as possible data loss. It is not: `persist` defaults True, so the DB row IS
written and IS durable. Cheech then found the real shape at
`notifications.py:1084-1108` — the in-memory FIFO queue is a LIVE-DELIVERY
buffer and the DB row is a FORENSIC record, the two stores are deliberate and
documented, and `GET /notifications/{user_id}` reads only the queue. Nothing
rehydrates the queue from the DB, so an offline user's notification is durably
stored and permanently unreachable through the one endpoint that serves them.

🔴 RICK RULED IT 2026-08-25, ask_multiple_choice, answered:true,
default_used:false: "Keep the design, make the reply honest." The two-store
split stays. The defect worth fixing was that a caller got a 200 with
`user_not_available` buried in the body and no cheap way to tell delivery had
not happened — so callers reasonably read 200 as success.

WHAT THIS PINS: every response from the fire-and-forget path carries a boolean
`delivered` and a `delivery_path`, and `delivered` DISCRIMINATES — True when the
notification reached a live delivery path, False when it did not.

⚠️ WHY THE ASSERTIONS CHECK BOTH ARMS RATHER THAN JUST THE OFFLINE ONE. A test
that only asserts `delivered is False` on the offline path passes just as
happily against a hardcoded False, which would make every online notification
report a failure. The online arm is what gives the offline arm meaning. This is
the same trap the row's own history records: the pre-existing
`test_notification_queue_operations` accepted a 200 and never inspected the
status field, so a 200 carrying `user_not_available` read as success for months.

⚠️ AND `delivered=True` ON THE QUEUED PATH IS NOT A CLAIM THE SOCKET HAS CARRIED
IT. The user is connected and the notification reached the live queue.
`delivered` answers "will this be readable", which is the question a caller
actually has — not "have the bytes landed".

Venue: :7999 bucket — TestClient against a FastAPI app with the router mounted,
every dependency overridden. No database, no WebSocket, no network. Under 2s.

See: row fcc74307 · src/cosa/rest/routers/notifications.py:1076, :1111, :1166
"""

import uuid as uuid_module
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers.notifications import (
    router,
    get_notification_queue,
    get_websocket_manager,
)
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import user_service


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router( router )
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def db_context():
    """A get_db() stand-in: a context manager yielding a mock session."""
    session = MagicMock()

    class _Ctx:
        def __enter__( self ):
            return session
        def __exit__( self, *args ):
            pass

    return _Ctx()


def _post( app, db_context, *, connected ):
    """Drive POST /api/notify once with the user either connected or not, and
    return the parsed JSON body.

    `connected` is the ONLY thing that varies between the two arms — everything
    else is held identical, so a difference in the response is attributable to
    connectedness and to nothing else."""
    ws = Mock()
    ws.is_user_connected.return_value        = connected
    ws.get_user_connection_count.return_value = 1 if connected else 0
    ws.user_sessions       = {}
    ws.active_connections  = {}
    ws.user_to_email       = {}

    queue = Mock()
    queue.push_notification.return_value = { "id": "notif-123" }

    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "service_account_123"
    app.dependency_overrides[ get_websocket_manager ]  = lambda: ws
    app.dependency_overrides[ get_notification_queue ] = lambda: queue

    notification    = MagicMock()
    notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

    original_get_user = user_service.get_user_by_email
    user_service.get_user_by_email = Mock( return_value={
        "id"    : "550e8400-e29b-41d4-a716-446655440000",
        "email" : "test@example.com",
    } )

    try:
        with patch( "cosa.rest.routers.notifications.get_db", return_value=db_context ):
            with patch( "cosa.rest.routers.notifications.NotificationRepository" ) as MockRepo:
                repo = MagicMock()
                repo.create_notification.return_value = notification
                MockRepo.return_value = repo

                response = TestClient( app ).post(
                    "/api/notify",
                    params={
                        "message"     : "Test notification",
                        "type"        : "task",
                        "priority"    : "medium",
                        "target_user" : "test@example.com",
                    },
                    headers={ "X-API-Key": "claude_code_simple_key" },
                )
                assert response.status_code == 200, response.text
                return response.json()
    finally:
        user_service.get_user_by_email = original_get_user


class TestDeliveredDiscriminates:

    def test_offline_reports_not_delivered( self, app, db_context ):
        """THE FIX. A 200 here means ACCEPTED, never delivered, and until now
        the only signal was a status string buried in the body."""
        body = _post( app, db_context, connected=False )

        assert body[ "status" ] == "user_not_available"
        assert body[ "delivered" ] is False, (
            f"offline notification reported delivered={body.get( 'delivered' )!r}; "
            "a caller reading this 200 would believe it arrived."
        )
        assert body[ "delivery_path" ] is None

    def test_online_reports_delivered( self, app, db_context ):
        """THE CONTROL THAT GIVES THE TEST ABOVE ITS MEANING. Without this a
        hardcoded `delivered=False` passes, and every successful notification
        would report a failure."""
        body = _post( app, db_context, connected=True )

        assert body[ "status" ] == "queued"
        assert body[ "delivered" ] is True, (
            f"connected user's notification reported delivered={body.get( 'delivered' )!r}; "
            "the field is not discriminating and is worthless to a caller."
        )
        assert body[ "delivery_path" ] == "queue"

    def test_the_two_arms_actually_differ( self, app, db_context ):
        """Stated as its own assertion rather than left implied across two
        tests: connectedness is the only input that changed, so `delivered`
        must be the thing that moved."""
        offline = _post( app, db_context, connected=False )
        online  = _post( app, db_context, connected=True )

        assert offline[ "delivered" ] != online[ "delivered" ], (
            "delivered reported the same value for a connected and a disconnected "
            "user, so it carries no information."
        )


class TestTheFieldIsAlwaysPresent:

    @pytest.mark.parametrize( "connected", [ True, False ] )
    def test_both_keys_present_on_every_response( self, app, db_context, connected ):
        """A caller must not have to use .get() with a default — an absent key
        would silently read as 'not delivered' and reintroduce the ambiguity
        this row exists to remove."""
        body = _post( app, db_context, connected=connected )

        assert "delivered"     in body, "response is missing the `delivered` key entirely"
        assert "delivery_path" in body, "response is missing the `delivery_path` key entirely"
        assert isinstance( body[ "delivered" ], bool ), (
            f"`delivered` must be a bool so `if not resp['delivered']` is safe; "
            f"got {type( body[ 'delivered' ] ).__name__}"
        )


class TestTheForensicRowIsStillWritten:

    def test_offline_still_mints_the_db_row( self, app, db_context ):
        """The ruling KEPT the design, so the durable record must survive the
        change. If this ever goes red, the row really would be data loss —
        which is what john originally suspected and what the code disproved."""
        ws = Mock()
        ws.is_user_connected.return_value         = False
        ws.get_user_connection_count.return_value = 0
        ws.user_sessions      = {}
        ws.active_connections = {}
        ws.user_to_email      = {}

        queue = Mock()
        app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "service_account_123"
        app.dependency_overrides[ get_websocket_manager ]  = lambda: ws
        app.dependency_overrides[ get_notification_queue ] = lambda: queue

        notification    = MagicMock()
        notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = Mock( return_value={
            "id"    : "550e8400-e29b-41d4-a716-446655440000",
            "email" : "test@example.com",
        } )
        try:
            with patch( "cosa.rest.routers.notifications.get_db", return_value=db_context ):
                with patch( "cosa.rest.routers.notifications.NotificationRepository" ) as MockRepo:
                    repo = MagicMock()
                    repo.create_notification.return_value = notification
                    MockRepo.return_value = repo

                    response = TestClient( app ).post(
                        "/api/notify",
                        params={
                            "message"     : "Test notification",
                            "type"        : "task",
                            "priority"    : "medium",
                            "target_user" : "test@example.com",
                        },
                        headers={ "X-API-Key": "claude_code_simple_key" },
                    )
                    assert response.status_code == 200
                    assert response.json()[ "delivered" ] is False
                    repo.create_notification.assert_called_once(), (
                        "the forensic DB row was NOT written on the offline path — "
                        "this would be real data loss, not just unreachability."
                    )
        finally:
            user_service.get_user_by_email = original_get_user


if __name__ == "__main__":
    print( "Run with: pytest src/tests/unit/test_notify_delivered_field.py -v" )
