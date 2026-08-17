"""
Unit tests for Notifications API Endpoints (Phase 2.1).

Tests POST /api/notify and POST /api/notify/response endpoints with both
fire-and-forget and response-required modes.
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

# Bootstrap imports
import sys
import os

# Add src to path for imports
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root:
    src_path = os.path.join( lupin_root, 'src' )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

# Import dependencies and router
from cosa.rest.routers.notifications import (
    router,
    get_notification_queue,
    get_websocket_manager
)
from cosa.rest.db.database import get_db
from cosa.rest.middleware.api_key_auth import require_api_key, require_api_key_or_jwt
from cosa.rest import user_service
from fastapi import FastAPI


@pytest.fixture
def app():
    """Create FastAPI app with notifications router."""
    app = FastAPI()
    app.include_router( router )
    yield app
    # Clear dependency overrides after each test
    app.dependency_overrides.clear()


@pytest.fixture
def mock_db_session():
    """
    Create a mock database session for PostgreSQL repository pattern.

    The session mock is configured as a context manager that yields itself,
    mimicking the get_db() behavior.
    """
    mock_session = MagicMock()

    # Create a context manager that yields the mock session
    class MockDbContextManager:
        def __enter__( self ):
            return mock_session
        def __exit__( self, *args ):
            pass

    return MockDbContextManager(), mock_session


class TestNotifyFireAndForget:
    """Test suite for POST /api/notify in fire-and-forget mode (existing behavior)."""

    def test_notify_fire_and_forget_success(self, app, mock_db_session):
        """Test fire-and-forget notification succeeds when user is online."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mocks
        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = True
        mock_ws_instance.get_user_connection_count.return_value = 1
        mock_ws_instance.user_sessions = { "550e8400-e29b-41d4-a716-446655440000": [ "session-1" ] }
        mock_ws_instance.active_connections = { "session-1": Mock() }
        mock_ws_instance.user_to_email = { "550e8400-e29b-41d4-a716-446655440000": "test@example.com" }

        mock_queue_instance = Mock()
        mock_queue_instance.push_notification.return_value = {"id": "notif-123"}

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the NotificationRepository
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        # Override FastAPI dependencies - including API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        # Mock user_service module-level function
        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            # Patch get_db to return our mock context manager
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                # Patch NotificationRepository
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    # Make request with X-API-Key header
                    response = client.post(
                        "/api/notify",
                        params={
                            "message"     : "Test notification",
                            "type"        : "task",
                            "priority"    : "medium",
                            "target_user" : "test@example.com"
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    # Assertions
                    assert response.status_code == 200
                    assert response.json()["status"] == "queued"
                    assert "test@example.com" in response.json()["message"]
                    mock_queue_instance.push_notification.assert_called_once()

        finally:
            # Restore original function
            user_service.get_user_by_email = original_get_user

    def test_notify_fire_and_forget_user_offline(self, app, mock_db_session):
        """Test fire-and-forget notification when user is offline."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mocks
        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = False
        mock_ws_instance.get_user_connection_count.return_value = 0
        mock_ws_instance.user_sessions = {}
        mock_ws_instance.active_connections = {}
        mock_ws_instance.user_to_email = {}

        mock_queue_instance = Mock()
        mock_queue_instance.push_notification.return_value = {"id": "notif-123"}

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the NotificationRepository
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        # Override FastAPI dependencies - including API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        # Mock user_service module-level function
        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            # Patch get_db to return our mock context manager
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                # Patch NotificationRepository
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    response = client.post(
                        "/api/notify",
                        params={
                            "message"     : "Test notification",
                            "type"        : "task",
                            "priority"    : "medium",
                            "target_user" : "test@example.com"
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    assert response.status_code == 200
                    assert response.json()["status"] == "user_not_available"
                    assert response.json()["connection_count"] == 0
                    # Symmetric positive assert (Rachel review nit): persist defaults
                    # True → the forensic DB row IS minted, even on the offline miss.
                    mock_repo_instance.create_notification.assert_called_once()

        finally:
            # Restore original function
            user_service.get_user_by_email = original_get_user

    def test_notify_fire_and_forget_persist_false_skips_db_row(self, app, mock_db_session):
        """Bug e1bbe011: persist=false skips the DB insert (the re-announce
        flood-guard) while leaving live delivery + the offline outcome unchanged.
        Covers the persist=False branch of the fire-and-forget persist block."""
        from unittest.mock import patch
        import uuid as uuid_module

        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        # Offline: with persist=false NO forensic row is written on the miss.
        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = False
        mock_ws_instance.get_user_connection_count.return_value = 0
        mock_ws_instance.user_sessions = {}
        mock_ws_instance.active_connections = {}
        mock_ws_instance.user_to_email = {}

        mock_queue_instance = Mock()
        mock_queue_instance.push_notification.return_value = {"id": "notif-123"}

        db_context_manager, mock_session = mock_db_session

        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    response = client.post(
                        "/api/notify",
                        params={
                            "message"     : "Re-announce retry",
                            "type"        : "alert",
                            "priority"    : "high",
                            "target_user" : "test@example.com",
                            "persist"     : "false",
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    assert response.status_code == 200
                    assert response.json()["status"] == "user_not_available"
                    # The flood-guard: NO forensic DB row was minted on this retry.
                    mock_repo_instance.create_notification.assert_not_called()

        finally:
            user_service.get_user_by_email = original_get_user

    def test_notify_persist_db_error_is_non_fatal(self, app, mock_db_session):
        """persist=True + a DB persist failure is non-fatal — the notify still
        delivers (FIFO queue is the primary mechanism). Covers the persist-block
        `except Exception as db_error` handler."""
        from unittest.mock import patch

        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        # Online so we proceed to queued after the (failed) persist.
        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = True
        mock_ws_instance.get_user_connection_count.return_value = 1
        mock_ws_instance.user_sessions = { "550e8400-e29b-41d4-a716-446655440000": [ "session-1" ] }
        mock_ws_instance.active_connections = { "session-1": Mock() }
        mock_ws_instance.user_to_email = { "550e8400-e29b-41d4-a716-446655440000": "test@example.com" }

        mock_queue_instance = Mock()
        mock_queue_instance.push_notification.return_value = {"id": "notif-123"}

        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            # Force the persist to raise — exercised via asyncio.to_thread.
            def _boom( *args, **kwargs ):
                raise RuntimeError( "PostgreSQL unavailable" )
            with patch( 'cosa.rest.routers.notifications._persist_notification_sync', _boom ):
                client = TestClient( app )
                response = client.post(
                    "/api/notify",
                    params={
                        "message"     : "Persist should fail but not crash",
                        "type"        : "task",
                        "priority"    : "medium",
                        "target_user" : "test@example.com",
                    },
                    headers={"X-API-Key": "claude_code_simple_key"}
                )
                assert response.status_code == 200
                assert response.json()["status"] == "queued"   # delivered despite persist failure
                mock_queue_instance.push_notification.assert_called_once()

        finally:
            user_service.get_user_by_email = original_get_user

    def test_notify_invalid_api_key(self, app):
        """Test notification with invalid API key returns 401."""
        client = TestClient( app )

        response = client.post(
            "/api/notify",
            params={
                "message"     : "Test notification",
                "type"        : "task",
                "priority"    : "medium",
                "target_user" : "test@example.com"
            },
            headers={"X-API-Key": "wrong_key"}
        )

        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"] or "API key" in response.json()["detail"]


def _parse_sse_frames( body ):
    """
    Parse an SSE response body into its decoded `data:` payloads.

    Requires:
        - body is a string of SSE text; every data line carries valid JSON

    Ensures:
        - returns a list of dicts, one per `data: ` line, in emission order
        - non-data lines (comments, blank separators) are ignored

    Raises:
        - json.JSONDecodeError if a data line is not valid JSON
    """
    return [ json.loads( line.split( "data: ", 1 )[ 1 ] )
             for line in body.splitlines() if line.startswith( "data: " ) ]


class TestNotifyResponseRequired:
    """Test suite for POST /api/notify in response-required mode (Phase 2.1)."""

    def test_notify_response_required_validation(self, app):
        """Test response-required mode requires response_type parameter."""
        # Override API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"

        client = TestClient( app )

        response = client.post(
            "/api/notify",
            params={
                "message"           : "Test notification",
                "type"              : "task",
                "priority"          : "high",
                "target_user"       : "test@example.com",
                "response_requested": True
                # Missing response_type
            },
            headers={"X-API-Key": "claude_code_simple_key"}
        )

        assert response.status_code == 400
        assert "response_type is required" in response.json()["detail"]

    def test_notify_response_required_invalid_response_type(self, app):
        """Test response-required mode validates response_type values."""
        # Override API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"

        client = TestClient( app )

        response = client.post(
            "/api/notify",
            params={
                "message"           : "Test notification",
                "type"              : "task",
                "priority"          : "high",
                "target_user"       : "test@example.com",
                "response_requested": True,
                "response_type"     : "invalid_type"
            },
            headers={"X-API-Key": "claude_code_simple_key"}
        )

        assert response.status_code == 400
        assert "Invalid response_type" in response.json()["detail"]

    def test_notify_response_required_open_ended_batch_accepted(self, app, mock_db_session):
        """Test response-required mode accepts open_ended_batch as a valid response_type."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mocks
        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = False
        mock_ws_instance.get_user_connection_count.return_value = 0
        mock_ws_instance.user_sessions = {}
        mock_ws_instance.active_connections = {}
        mock_ws_instance.user_to_email = {}

        mock_queue_instance = Mock()

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the NotificationRepository
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        # Override FastAPI dependencies
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        # Mock user_service module-level function
        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            # Patch get_db to return our mock context manager
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    mock_repo_instance.update_state.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    # open_ended_batch should NOT return 400 validation error
                    response = client.post(
                        "/api/notify",
                        params={
                            "message"           : "Batch questions",
                            "type"              : "task",
                            "priority"          : "high",
                            "target_user"       : "test@example.com",
                            "response_requested": True,
                            "response_type"     : "open_ended_batch",
                            "response_default"  : "defer"
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    # Should pass validation (200 offline-with-default, not 400).
                    # Bug f433fbae D1 (server half, 1cd795c7): the offline branch now
                    # emits a CONSUMABLE SSE stream, not a JSONResponse. `.json()` on
                    # this path is wrong BY DESIGN — assert the two frames instead.
                    assert response.status_code == 200
                    assert response.headers[ "content-type" ].startswith( "text/event-stream" )

                    frames = _parse_sse_frames( response.text )
                    assert len( frames ) == 2
                    ack, offline = frames
                    assert ack[ "status" ] == "ack"
                    assert "notification_id" in ack                  # re-attach handle
                    assert offline[ "status" ] == "offline"
                    assert offline[ "response" ] == "defer"          # the default is DELIVERED
                    assert offline[ "default_used" ] is True         # MARKED as a substitution

        finally:
            user_service.get_user_by_email = original_get_user

    def test_notify_response_required_offline_with_default(self, app, mock_db_session):
        """Test response-required mode returns default immediately when user offline."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mocks
        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = False
        mock_ws_instance.get_user_connection_count.return_value = 0
        mock_ws_instance.user_sessions = {}
        mock_ws_instance.active_connections = {}
        mock_ws_instance.user_to_email = {}

        mock_queue_instance = Mock()

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the NotificationRepository
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        # Override FastAPI dependencies - including API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        # Mock user_service module-level function
        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            # Patch get_db to return our mock context manager
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                # Patch NotificationRepository
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    mock_repo_instance.update_state.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    response = client.post(
                        "/api/notify",
                        params={
                            "message"           : "Test notification",
                            "type"              : "task",
                            "priority"          : "high",
                            "target_user"       : "test@example.com",
                            "response_requested": True,
                            "response_type"     : "yes_no",
                            "response_default"  : "no"
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    # Bug f433fbae D1 (server half, 1cd795c7): the offline branch emits
                    # an SSE ack frame (carrying notification_id for re-attach) followed
                    # by an OfflineEvent whose `response` IS the default and whose
                    # default_used=True is the provenance marker the caller stamps as
                    # `answered: False`. Restoring a `.json()` assertion here would be
                    # the cheap green, and the wrong one.
                    assert response.status_code == 200
                    assert response.headers[ "content-type" ].startswith( "text/event-stream" )

                    frames = _parse_sse_frames( response.text )
                    assert len( frames ) == 2
                    ack, offline = frames
                    assert ack[ "status" ] == "ack"
                    assert "notification_id" in ack                  # re-attach handle
                    assert offline[ "status" ] == "offline"
                    assert offline[ "response" ] == "no"             # the default is DELIVERED
                    assert offline[ "default_used" ] is True         # MARKED as a substitution

        finally:
            # Restore original function
            user_service.get_user_by_email = original_get_user

    def test_notify_response_required_offline_no_default(self, app, mock_db_session):
        """Row 0c3ad4b5: offline + NO default emits a NAMED terminal OfflineEvent
        (default_used=False, response=null) over a 200 SSE stream — NOT a bare 503.

        A 503 reads as 'server down, retry', the opposite of the correct
        offline-user response (stop asking, block the row with a chase). This
        named signal lets the sync ask degrade the way the async notify path
        already does. No default is forged: response stays null."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mocks
        mock_user_service = Mock()
        mock_user_service.get_user_by_email = Mock( return_value={"id": "550e8400-e29b-41d4-a716-446655440000", "email": "test@example.com"} )

        mock_ws_instance = Mock()
        mock_ws_instance.is_user_connected.return_value = False
        mock_ws_instance.get_user_connection_count.return_value = 0
        mock_ws_instance.user_sessions = {}
        mock_ws_instance.active_connections = {}
        mock_ws_instance.user_to_email = {}

        mock_queue_instance = Mock()

        # Setup mock database session — the named-signal path persists
        # (state='expired') + records idempotency, mirroring the with-default branch.
        db_context_manager, mock_session = mock_db_session

        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )

        # Override FastAPI dependencies - including API key auth
        app.dependency_overrides[require_api_key_or_jwt] = lambda: "service_account_123"
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance
        app.dependency_overrides[get_notification_queue] = lambda: mock_queue_instance

        # Mock user_service module-level function
        original_get_user = user_service.get_user_by_email
        user_service.get_user_by_email = mock_user_service.get_user_by_email

        try:
            with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
                with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.create_notification.return_value = mock_notification
                    mock_repo_instance.update_state.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    response = client.post(
                        "/api/notify",
                        params={
                            "message"           : "Test notification",
                            "type"              : "task",
                            "priority"          : "high",
                            "target_user"       : "test@example.com",
                            "response_requested": True,
                            "response_type"     : "yes_no"
                            # No response_default provided
                        },
                        headers={"X-API-Key": "claude_code_simple_key"}
                    )

                    # Row 0c3ad4b5: NOT a 503. A 200 SSE stream — ack (re-attach
                    # handle) then a NAMED OfflineEvent with default_used=False and
                    # response=null: the "user unavailable, no answer to give"
                    # signal a caller can branch on. No default is forged.
                    assert response.status_code == 200
                    assert response.headers[ "content-type" ].startswith( "text/event-stream" )

                    frames = _parse_sse_frames( response.text )
                    assert len( frames ) == 2
                    ack, offline = frames
                    assert ack[ "status" ] == "ack"
                    assert "notification_id" in ack                  # re-attach handle
                    assert offline[ "status" ] == "offline"
                    assert offline[ "response" ] is None             # NO default forged
                    assert offline[ "default_used" ] is False        # named user-unavailable

        finally:
            # Restore original function
            user_service.get_user_by_email = original_get_user


class TestSubmitNotificationResponse:
    """Test suite for POST /api/notify/response endpoint."""

    def test_submit_response_success(self, app, mock_db_session):
        """Test successful response submission."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the notification object that repository returns
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )
        mock_notification.state = "delivered"
        mock_notification.recipient_id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440000" )
        mock_notification.expires_at = None

        mock_ws_instance = AsyncMock()

        # Create mock config_mgr
        mock_config_mgr = MagicMock()
        mock_config_mgr.get.return_value = 300  # Default grace period

        # Override FastAPI dependencies
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance

        # Patch get_db to return our mock context manager
        with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
            # Patch NotificationRepository
            with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                # Patch lupin_app.main.config_mgr by patching the import in the module
                with patch( 'lupin_app.main.config_mgr', mock_config_mgr ):
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.get_by_id.return_value = mock_notification
                    mock_repo_instance.update_response.return_value = mock_notification
                    MockRepo.return_value = mock_repo_instance

                    client = TestClient( app )

                    response = client.post(
                        "/api/notify/response",
                        json={
                            "notification_id" : "550e8400-e29b-41d4-a716-446655440001",
                            "response_value"  : {"answer": "yes"}
                        }
                    )

                    assert response.status_code == 200
                    assert response.json()["status"] == "success"
                    mock_repo_instance.update_response.assert_called_once()

    def test_submit_response_notification_not_found(self, app, mock_db_session):
        """Test response submission for non-existent notification returns 404."""
        from unittest.mock import patch

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        mock_ws_instance = AsyncMock()

        # Override FastAPI dependencies
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance

        # Patch get_db to return our mock context manager
        with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
            # Patch NotificationRepository
            with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                mock_repo_instance = MagicMock()
                mock_repo_instance.get_by_id.return_value = None  # Not found
                MockRepo.return_value = mock_repo_instance

                client = TestClient( app )

                response = client.post(
                    "/api/notify/response",
                    json={
                        "notification_id" : "550e8400-e29b-41d4-a716-446655440099",
                        "response_value"  : {"answer": "yes"}
                    }
                )

                assert response.status_code == 404

    def test_submit_response_already_responded(self, app, mock_db_session):
        """Test response submission for already-responded notification returns 400."""
        from unittest.mock import patch
        import uuid as uuid_module

        # Setup mock database session
        db_context_manager, mock_session = mock_db_session

        # Mock the notification object with state="responded"
        mock_notification = MagicMock()
        mock_notification.id = uuid_module.UUID( "550e8400-e29b-41d4-a716-446655440001" )
        mock_notification.state = "responded"

        mock_ws_instance = AsyncMock()

        # Override FastAPI dependencies
        app.dependency_overrides[get_websocket_manager] = lambda: mock_ws_instance

        # Patch get_db to return our mock context manager
        with patch( 'cosa.rest.routers.notifications.get_db', return_value=db_context_manager ):
            # Patch NotificationRepository
            with patch( 'cosa.rest.routers.notifications.NotificationRepository' ) as MockRepo:
                mock_repo_instance = MagicMock()
                mock_repo_instance.get_by_id.return_value = mock_notification
                MockRepo.return_value = mock_repo_instance

                client = TestClient( app )

                response = client.post(
                    "/api/notify/response",
                    json={
                        "notification_id" : "550e8400-e29b-41d4-a716-446655440001",
                        "response_value"  : {"answer": "yes"}
                    }
                )

                assert response.status_code == 400
                assert "already responded" in response.json()["detail"]


if __name__ == "__main__":
    print( "Run with: pytest src/tests/unit/test_notifications_api.py -v" )
