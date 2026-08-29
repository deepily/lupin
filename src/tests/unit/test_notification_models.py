"""
Unit tests for notification Pydantic models (Phase 2.3 + Phase 2.4).

Tests validation logic, field validators, and model methods for:
- NotificationRequest (sync)
- SSE Events (RespondedEvent, ExpiredEvent, OfflineEvent, ErrorEvent)
- NotificationResponse (sync)
- AsyncNotificationRequest (fire-and-forget)
- AsyncNotificationResponse (fire-and-forget)
"""

import pytest
from pydantic import ValidationError

from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationResponse,
    RespondedEvent,
    ExpiredEvent,
    OfflineEvent,
    ErrorEvent,
    AsyncNotificationRequest,
    AsyncNotificationResponse,
    NotificationType,
    NotificationPriority,
    ResponseType,
    resolve_target_user
)


# ============================================================================
# NotificationRequest Tests
# ============================================================================

class TestNotificationRequestValidation:
    """Test NotificationRequest field validation."""

    def test_valid_yes_no_request( self ):
        """Test valid yes/no notification request."""
        request = NotificationRequest(
            message="Approve deployment?",
            response_type=ResponseType.YES_NO,
            response_default="yes"
        )

        assert request.message == "Approve deployment?"
        assert request.response_type == ResponseType.YES_NO
        assert request.response_default == "yes"
        assert request.notification_type == NotificationType.CUSTOM  # default
        assert request.priority == NotificationPriority.MEDIUM  # default
        assert request.timeout_seconds == 120  # default

    def test_valid_open_ended_request( self ):
        """Test valid open-ended notification request."""
        request = NotificationRequest(
            message="Enter API key",
            response_type=ResponseType.OPEN_ENDED,
            response_default="sk-test-key"
        )

        assert request.message == "Enter API key"
        assert request.response_type == ResponseType.OPEN_ENDED
        assert request.response_default == "sk-test-key"

    def test_message_required( self ):
        """Test that message field is required."""
        with pytest.raises( ValidationError ) as exc_info:
            NotificationRequest(
                response_type=ResponseType.YES_NO
                # message missing
            )

        errors = exc_info.value.errors()
        assert any( e['loc'] == ('message',) for e in errors )

    def test_message_not_whitespace( self ):
        """Test that message cannot be whitespace-only."""
        with pytest.raises( ValidationError ) as exc_info:
            NotificationRequest(
                message="   ",  # whitespace only
                response_type=ResponseType.YES_NO
            )

        errors = exc_info.value.errors()
        assert any( 'whitespace' in e['msg'].lower() for e in errors )

    def test_message_stripped( self ):
        """Test that message is stripped of leading/trailing whitespace."""
        request = NotificationRequest(
            message="  Test message  ",
            response_type=ResponseType.YES_NO
        )

        assert request.message == "Test message"

    def test_timeout_min_value( self ):
        """Test timeout must be >= 1."""
        with pytest.raises( ValidationError ):
            NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                timeout_seconds=0  # Invalid
            )

    def test_timeout_max_value( self ):
        """Test timeout must be <= 600."""
        with pytest.raises( ValidationError ):
            NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                timeout_seconds=601  # Invalid
            )

    def test_yes_no_default_must_be_yes_or_no( self ):
        """Test yes/no default must be 'yes' or 'no'."""
        # Invalid default
        with pytest.raises( ValidationError ) as exc_info:
            NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                response_default="maybe"  # Invalid for yes_no
            )

        errors = exc_info.value.errors()
        assert any( 'yes' in e['msg'] or 'no' in e['msg'] for e in errors )

        # Valid defaults
        request_yes = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO,
            response_default="yes"
        )
        assert request_yes.response_default == "yes"

        request_no = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO,
            response_default="no"
        )
        assert request_no.response_default == "no"

    def test_open_ended_default_can_be_any_string( self ):
        """Test open-ended default can be any string."""
        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.OPEN_ENDED,
            response_default="Any custom text here"
        )

        assert request.response_default == "Any custom text here"

    def test_to_api_params_conversion( self ):
        """Test conversion to API query parameters."""
        request = NotificationRequest(
            message="Test notification",
            response_type=ResponseType.YES_NO,
            notification_type=NotificationType.TASK,
            priority=NotificationPriority.HIGH,
            target_user="test@example.com",
            timeout_seconds=60,
            response_default="yes",
            title="Test Title"
        )

        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        assert params["message"] == "Test notification"
        assert params["type"] == "task"
        assert params["priority"] == "high"
        assert params["target_user"] == "test@example.com"
        assert params["response_requested"] == "true"
        assert params["response_type"] == "yes_no"
        assert params["timeout_seconds"] == 60
        assert params["response_default"] == "yes"
        assert params["title"] == "Test Title"
        # api_key no longer in params - goes in HTTP header as X-API-Key

    def test_to_api_params_excludes_none_values( self ):
        """Test that None optional fields are excluded from params."""
        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO,
            target_user="test@example.com"
            # response_default and title are None
        )

        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        assert "response_default" not in params
        assert "title" not in params
        assert "api_key" not in params  # Now in HTTP headers
        assert "idempotency_key" not in params  # bug f433fbae D2: None → omitted

    def test_to_api_params_human_only_sent_only_when_true( self ):
        """human_only rides to_api_params ONLY when True (default omitted) — row 804afce6."""
        on = NotificationRequest(
            message="Self-re-spin now?", response_type=ResponseType.YES_NO,
            target_user="test@example.com", human_only=True,
        )
        assert on.to_api_params()[ "human_only" ] == "true"

        off = NotificationRequest(
            message="ordinary ask", response_type=ResponseType.YES_NO,
            target_user="test@example.com",
        )
        assert "human_only" not in off.to_api_params()

    def test_to_api_params_includes_idempotency_key_when_set( self ):
        """bug f433fbae D2: a set idempotency_key is forwarded so the server can
        de-dup a re-POST of the same ask."""
        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO,
            target_user="test@example.com",
            idempotency_key="11111111-2222-3333-4444-555555555555",
        )
        params = request.to_api_params()
        assert params["idempotency_key"] == "11111111-2222-3333-4444-555555555555"

    def test_to_api_params_raises_when_target_user_none( self ):
        """Test that to_api_params() raises ValueError when target_user is None."""
        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
            # target_user defaults to None
        )

        with pytest.raises( ValueError, match="target_user is None" ):
            request.to_api_params()


# ============================================================================
# SSE Event Model Tests
# ============================================================================

class TestSSEEventModels:
    """Test SSE event model validation."""

    def test_responded_event( self ):
        """Test RespondedEvent model."""
        event = RespondedEvent(
            response="yes",
            default_used=False
        )

        assert event.status == "responded"
        assert event.response == "yes"
        assert event.default_used is False

    def test_expired_event_with_default( self ):
        """Test ExpiredEvent with default value."""
        event = ExpiredEvent(
            response="no",
            default_used=True,
            timeout=True
        )

        assert event.status == "expired"
        assert event.response == "no"
        assert event.default_used is True
        assert event.timeout is True

    def test_expired_event_without_default( self ):
        """Test ExpiredEvent without default value."""
        event = ExpiredEvent(
            response=None,
            default_used=False,
            timeout=True
        )

        assert event.status == "expired"
        assert event.response is None
        assert event.default_used is False

    def test_offline_event( self ):
        """Test OfflineEvent model."""
        event = OfflineEvent(
            response="yes"
        )

        assert event.status == "offline"
        assert event.response == "yes"
        assert event.default_used is True  # Always True for offline

    def test_error_event( self ):
        """Test ErrorEvent model."""
        event = ErrorEvent(
            message="User not found"
        )

        assert event.status == "error"
        assert event.message == "User not found"
        assert event.response is None

    def test_sse_event_validation_fails_on_invalid_status( self ):
        """Test that invalid status values are rejected."""
        # RespondedEvent with wrong status
        with pytest.raises( ValidationError ):
            RespondedEvent(
                status="invalid_status",  # Should be "responded"
                response="yes"
            )


# ============================================================================
# NotificationResponse Tests
# ============================================================================

class TestNotificationResponse:
    """Test NotificationResponse model."""

    def test_success_response( self ):
        """Test successful response."""
        response = NotificationResponse(
            response_value="yes",
            exit_code=0,
            status="responded"
        )

        assert response.response_value == "yes"
        assert response.exit_code == 0
        assert response.status == "responded"
        assert response.success is True
        assert response.is_error is False
        assert response.is_timeout is False

    def test_error_response( self ):
        """Test error response."""
        response = NotificationResponse(
            response_value=None,
            exit_code=1,
            status="connection_error"
        )

        assert response.response_value is None
        assert response.exit_code == 1
        assert response.success is False
        assert response.is_error is True
        assert response.is_timeout is False

    def test_timeout_response( self ):
        """Test timeout response."""
        response = NotificationResponse(
            response_value="no",  # Default value
            exit_code=2,
            status="expired",
            default_used=True,
            is_timeout=True
        )

        assert response.response_value == "no"
        assert response.exit_code == 2
        assert response.success is False
        assert response.is_error is False
        assert response.is_timeout is True
        assert response.default_used is True

    def test_exit_code_validation( self ):
        """Test exit code must be 0, 1, or 2."""
        # Valid exit codes
        for code in [0, 1, 2]:
            response = NotificationResponse( exit_code=code )
            assert response.exit_code == code

        # Invalid exit codes
        for code in [-1, 3, 10]:
            with pytest.raises( ValidationError ):
                NotificationResponse( exit_code=code )

    def test_properties( self ):
        """Test success, is_error, is_timeout properties."""
        # Success
        response_success = NotificationResponse( exit_code=0 )
        assert response_success.success is True
        assert response_success.is_error is False

        # Error
        response_error = NotificationResponse( exit_code=1 )
        assert response_error.success is False
        assert response_error.is_error is True

        # Timeout
        response_timeout = NotificationResponse( exit_code=2 )
        assert response_timeout.success is False
        assert response_timeout.is_error is False


# ============================================================================
# AsyncNotificationRequest Tests (Phase 2.4)
# ============================================================================

class TestAsyncNotificationRequestValidation:
    """Test AsyncNotificationRequest field validation."""

    def test_valid_async_request( self ):
        """Test valid async notification request."""
        request = AsyncNotificationRequest(
            message="Build completed successfully",
            notification_type=NotificationType.TASK,
            priority=NotificationPriority.MEDIUM
        )

        assert request.message == "Build completed successfully"
        assert request.notification_type == NotificationType.TASK
        assert request.priority == NotificationPriority.MEDIUM
        assert request.target_user is None  # default (resolved at dispatch time)
        assert request.timeout == 5  # default

    def test_message_required( self ):
        """Test that message field is required."""
        with pytest.raises( ValidationError ) as exc_info:
            AsyncNotificationRequest()  # message missing

        errors = exc_info.value.errors()
        assert any( e['loc'] == ('message',) for e in errors )

    def test_message_not_whitespace( self ):
        """Test that message cannot be whitespace-only."""
        with pytest.raises( ValidationError ) as exc_info:
            AsyncNotificationRequest(
                message="   "  # whitespace only
            )

        errors = exc_info.value.errors()
        assert any( 'whitespace' in e['msg'].lower() for e in errors )

    def test_message_stripped( self ):
        """Test that message is stripped of leading/trailing whitespace."""
        request = AsyncNotificationRequest(
            message="  Test message  "
        )

        assert request.message == "Test message"

    def test_timeout_min_value( self ):
        """Test timeout must be >= 1."""
        with pytest.raises( ValidationError ):
            AsyncNotificationRequest(
                message="Test",
                timeout=0  # Invalid
            )

    def test_timeout_max_value( self ):
        """Test timeout must be <= 30."""
        with pytest.raises( ValidationError ):
            AsyncNotificationRequest(
                message="Test",
                timeout=31  # Invalid
            )

    def test_timeout_valid_range( self ):
        """Test timeout accepts valid range 1-30."""
        # Min
        request_min = AsyncNotificationRequest(
            message="Test",
            timeout=1
        )
        assert request_min.timeout == 1

        # Max
        request_max = AsyncNotificationRequest(
            message="Test",
            timeout=30
        )
        assert request_max.timeout == 30

    def test_notification_type_enum( self ):
        """Test notification type uses enum validation."""
        # Valid enum
        request = AsyncNotificationRequest(
            message="Test",
            notification_type=NotificationType.ALERT
        )
        assert request.notification_type == NotificationType.ALERT

        # String conversion works
        request2 = AsyncNotificationRequest(
            message="Test",
            notification_type="progress"
        )
        assert request2.notification_type == NotificationType.PROGRESS

    def test_priority_enum( self ):
        """Test priority uses enum validation."""
        # Valid enum
        request = AsyncNotificationRequest(
            message="Test",
            priority=NotificationPriority.URGENT
        )
        assert request.priority == NotificationPriority.URGENT

        # String conversion works
        request2 = AsyncNotificationRequest(
            message="Test",
            priority="low"
        )
        assert request2.priority == NotificationPriority.LOW

    def test_to_api_params_conversion( self ):
        """Test conversion to API query parameters."""
        request = AsyncNotificationRequest(
            message="Test notification",
            notification_type=NotificationType.TASK,
            priority=NotificationPriority.HIGH,
            target_user="test@example.com"
        )

        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        assert params["message"] == "Test notification"
        assert params["type"] == "task"
        assert params["priority"] == "high"
        assert params["target_user"] == "test@example.com"
        # api_key no longer in params - goes in HTTP header as X-API-Key
        # Async does NOT include response_requested
        assert "response_requested" not in params

    def test_to_api_params_no_response_fields( self ):
        """Test that async params don't include sync response fields."""
        request = AsyncNotificationRequest( message="Test", target_user="test@example.com" )
        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        # Async should NOT have these sync-only fields
        assert "response_requested" not in params
        assert "response_type" not in params
        assert "timeout_seconds" not in params
        assert "response_default" not in params
        assert "api_key" not in params  # Now in HTTP headers


# ============================================================================
# AsyncNotificationResponse Tests (Phase 2.4)
# ============================================================================

class TestAsyncNotificationResponse:
    """Test AsyncNotificationResponse model."""

    def test_success_response_queued( self ):
        """Test successful queued response."""
        response = AsyncNotificationResponse(
            success=True,
            status="queued",
            message="Notification queued for delivery",
            target_user="test@example.com",
            target_system_id="user-uuid-123",
            connection_count=1
        )

        assert response.success is True
        assert response.status == "queued"
        assert response.message == "Notification queued for delivery"
        assert response.target_user == "test@example.com"
        assert response.target_system_id == "user-uuid-123"
        assert response.connection_count == 1
        assert response.is_queued is True
        assert response.is_error is False

    def test_error_response_connection_error( self ):
        """Test connection error response."""
        response = AsyncNotificationResponse(
            success=False,
            status="connection_error",
            message="Cannot reach server",
            target_user="test@example.com"
        )

        assert response.success is False
        assert response.status == "connection_error"
        assert response.message == "Cannot reach server"
        assert response.target_system_id is None  # default
        assert response.connection_count == 0  # default
        assert response.is_queued is False
        assert response.is_error is True

    def test_error_response_timeout( self ):
        """Test timeout error response."""
        response = AsyncNotificationResponse(
            success=False,
            status="timeout",
            message="Server did not respond within 5 seconds",
            target_user="test@example.com"
        )

        assert response.success is False
        assert response.status == "timeout"
        assert response.is_error is True

    def test_user_not_available_response( self ):
        """Test user not available response."""
        response = AsyncNotificationResponse(
            success=True,
            status="user_not_available",
            message="User offline, notification queued",
            target_user="test@example.com"
        )

        assert response.success is True
        assert response.status == "user_not_available"
        assert response.is_queued is False
        assert response.is_error is False

    def test_connection_count_validation( self ):
        """Test connection count must be >= 0."""
        # Valid
        response = AsyncNotificationResponse(
            success=True,
            status="queued",
            target_user="test@example.com",
            connection_count=0
        )
        assert response.connection_count == 0

        # Invalid (negative)
        with pytest.raises( ValidationError ):
            AsyncNotificationResponse(
                success=True,
                status="queued",
                target_user="test@example.com",
                connection_count=-1
            )

    def test_is_queued_property( self ):
        """Test is_queued property logic."""
        # Queued
        response_queued = AsyncNotificationResponse(
            success=True,
            status="queued",
            target_user="test@example.com"
        )
        assert response_queued.is_queued is True

        # Not queued
        response_error = AsyncNotificationResponse(
            success=False,
            status="error",
            target_user="test@example.com"
        )
        assert response_error.is_queued is False

    def test_is_error_property( self ):
        """Test is_error property logic."""
        # Error statuses
        for error_status in ["error", "connection_error", "timeout"]:
            response = AsyncNotificationResponse(
                success=False,
                status=error_status,
                target_user="test@example.com"
            )
            assert response.is_error is True, f"Expected is_error=True for status={error_status}"

        # Success statuses
        for success_status in ["queued", "user_not_available"]:
            response = AsyncNotificationResponse(
                success=True,
                status=success_status,
                target_user="test@example.com"
            )
            assert response.is_error is False, f"Expected is_error=False for status={success_status}"

    def test_optional_fields( self ):
        """Test that optional fields default correctly."""
        # Minimal response
        response = AsyncNotificationResponse(
            success=True,
            status="queued",
            target_user="test@example.com"
        )

        assert response.message is None  # optional
        assert response.target_system_id is None  # optional
        assert response.connection_count == 0  # default


# ============================================================================
# Progress Group ID Tests
# ============================================================================

class TestProgressGroupId:
    """Test progress_group_id field on AsyncNotificationRequest."""

    def test_default_is_none( self ):
        """Test that progress_group_id defaults to None."""
        req = AsyncNotificationRequest( message="Test message" )
        assert req.progress_group_id is None

    def test_valid_progress_group_id( self ):
        """Test that valid progress_group_id patterns are accepted (original pg- format)."""
        valid_ids = [
            "pg-a1b2c3d4",
            "pg-00000000",
            "pg-ffffffff",
            "pg-abcdef01",
        ]
        for pg_id in valid_ids:
            req = AsyncNotificationRequest( message="Test", progress_group_id=pg_id )
            assert req.progress_group_id == pg_id

    def test_valid_proxy_batch_progress_group_id( self ):
        """Test that proxy batch pr-{hex}-{N} format is accepted by relaxed regex."""
        valid_ids = [
            "pr-a1b2c3d4-1",     # Standard proxy batch
            "pr-a1b2c3d4-01",    # Zero-padded batch
            "pr-deadbeef-99",    # Two-digit batch
            "pr-a1b2c3d4-99999", # Unbounded batch number (long sessions)
            "pr-abcdef-1",       # 6-char hex is valid too
        ]
        for pg_id in valid_ids:
            req = AsyncNotificationRequest( message="Test", progress_group_id=pg_id )
            assert req.progress_group_id == pg_id

    def test_invalid_progress_group_id_rejected( self ):
        """Test that invalid progress_group_id patterns are rejected."""
        invalid_ids = [
            "pg-ABCDEF01",    # Uppercase hex
            "a1b2c3d4",       # Missing prefix
            "PG-a1b2c3d4",    # Uppercase prefix
            "pg_a1b2c3d4",    # Underscore instead of hyphen
            "pg-a1b2c",       # Too short (5 hex chars)
            "pr-ABCD1234-1",  # Uppercase hex in proxy format
            "abcd-a1b2c3d4",  # Prefix too long (4 chars)
        ]
        for pg_id in invalid_ids:
            with pytest.raises( ValidationError ):
                AsyncNotificationRequest( message="Test", progress_group_id=pg_id )

    def test_included_in_to_api_params( self ):
        """Test that progress_group_id is included in to_api_params() when set."""
        req = AsyncNotificationRequest(
            message="Test progress",
            target_user="test@example.com",
            progress_group_id="pg-a1b2c3d4"
        )
        params = req.to_api_params()
        assert "progress_group_id" in params
        assert params[ "progress_group_id" ] == "pg-a1b2c3d4"

    def test_excluded_from_to_api_params_when_none( self ):
        """Test that progress_group_id is excluded from to_api_params() when None."""
        req = AsyncNotificationRequest( message="Test no progress", target_user="test@example.com" )
        params = req.to_api_params()
        assert "progress_group_id" not in params

    def test_coexists_with_job_id( self ):
        """Test that progress_group_id works alongside job_id."""
        req = AsyncNotificationRequest(
            message="Test",
            target_user="test@example.com",
            job_id="dr-a1b2c3d4",
            progress_group_id="pg-12345678"
        )
        params = req.to_api_params()
        assert params[ "job_id" ] == "dr-a1b2c3d4"
        assert params[ "progress_group_id" ] == "pg-12345678"


class TestNotificationItemProgressGroup:
    """Test progress_group_id on NotificationItem and queue."""

    def test_notification_item_stores_progress_group_id( self ):
        """Test that NotificationItem stores progress_group_id."""
        from cosa.rest.notification_fifo_queue import NotificationItem
        item = NotificationItem( message="Step 1/5", progress_group_id="pg-abcdef01" )
        assert item.progress_group_id == "pg-abcdef01"

    def test_notification_item_default_none( self ):
        """Test that NotificationItem defaults progress_group_id to None."""
        from cosa.rest.notification_fifo_queue import NotificationItem
        item = NotificationItem( message="No group" )
        assert item.progress_group_id is None

    def test_notification_item_to_dict_includes_progress_group_id( self ):
        """Test that to_dict() includes progress_group_id."""
        from cosa.rest.notification_fifo_queue import NotificationItem
        item = NotificationItem( message="Step 2/5", progress_group_id="pg-12345678" )
        d = item.to_dict()
        assert "progress_group_id" in d
        assert d[ "progress_group_id" ] == "pg-12345678"

    def test_notification_item_to_dict_none_when_unset( self ):
        """Test that to_dict() includes progress_group_id as None when unset."""
        from cosa.rest.notification_fifo_queue import NotificationItem
        item = NotificationItem( message="No group" )
        d = item.to_dict()
        assert "progress_group_id" in d
        assert d[ "progress_group_id" ] is None


class TestAgenticJobBaseProgressGroup:
    """Test create_progress_group() on AgenticJobBase."""

    def test_create_progress_group_format( self ):
        """Test that create_progress_group() returns valid pg-{8hex} format."""
        from cosa.agents.agentic_job_base import AgenticJobBase

        class _TestJob( AgenticJobBase ):
            JOB_TYPE = "test"
            JOB_PREFIX = "tj"
            def __init__( self ):
                super().__init__( "u1", "t@t.com", "s1" )
            @property
            def last_question_asked( self ): return "test"
            def do_all( self ): return ""
            async def _execute( self ): return ""

        job = _TestJob()
        pg_id = job.create_progress_group()

        assert pg_id.startswith( "pg-" )
        assert len( pg_id ) == 11  # "pg-" + 8 hex chars
        # Validate hex characters
        hex_part = pg_id[ 3: ]
        int( hex_part, 16 )  # Should not raise

    def test_create_progress_group_unique( self ):
        """Test that create_progress_group() generates unique IDs."""
        from cosa.agents.agentic_job_base import AgenticJobBase

        class _TestJob( AgenticJobBase ):
            JOB_TYPE = "test"
            JOB_PREFIX = "tj"
            def __init__( self ):
                super().__init__( "u1", "t@t.com", "s1" )
            @property
            def last_question_asked( self ): return "test"
            def do_all( self ): return ""
            async def _execute( self ): return ""

        job = _TestJob()
        ids = { job.create_progress_group() for _ in range( 20 ) }
        assert len( ids ) == 20  # All unique


# ============================================================================
# resolve_target_user Tests
# ============================================================================

class TestResolveTargetUser:
    """Test resolve_target_user() precedence chain."""

    def test_explicit_value_takes_priority( self ):
        """Test that explicit value is returned immediately."""
        result = resolve_target_user( "explicit@example.com" )
        assert result == "explicit@example.com"

    def test_env_var_used_when_no_explicit( self, monkeypatch ):
        """Test LUPIN_DEV_EMAIL env var is used when no explicit value."""
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
        result = resolve_target_user()
        assert result == "env@example.com"

    def test_explicit_beats_env_var( self, monkeypatch ):
        """Test explicit value takes priority over env var."""
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
        result = resolve_target_user( "explicit@example.com" )
        assert result == "explicit@example.com"

    def test_raises_when_no_source( self, monkeypatch ):
        """Test ValueError raised when no source provides email."""
        from unittest.mock import patch
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        # Mock config loader to return no global_notification_recipient
        with patch( "cosa.utils.config_loader.get_api_config", return_value={ "api_url": "x", "api_key_file": "y" } ):
            with pytest.raises( ValueError, match="Cannot resolve target_user" ):
                resolve_target_user()


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for notification_models - validates basic functionality.
    """
    import cosa.utils.util as cu

    cu.print_banner( "Notification Models Smoke Test", prepend_nl=True )

    try:
        # Test 1: Create valid sync request
        print( "Testing NotificationRequest (sync) creation..." )
        request = NotificationRequest(
            message="Test notification",
            response_type=ResponseType.YES_NO,
            response_default="yes"
        )
        assert request.message == "Test notification"
        print( "✓ NotificationRequest created successfully" )

        # Test 2: Validate yes/no default
        print( "Testing yes/no default validation..." )
        try:
            NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                response_default="maybe"  # Invalid
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            print( "✓ Yes/no default validation working" )

        # Test 3: SSE event parsing
        print( "Testing SSE event models..." )
        event = RespondedEvent( response="yes", default_used=False )
        assert event.status == "responded"
        print( f"✓ SSE event created: {event.model_dump_json()}" )

        # Test 4: Response model
        print( "Testing NotificationResponse (sync) model..." )
        response = NotificationResponse( response_value="yes", exit_code=0 )
        assert response.success is True
        print( "✓ NotificationResponse created successfully" )

        # Test 5: Async request model (Phase 2.4)
        print( "Testing AsyncNotificationRequest creation..." )
        async_request = AsyncNotificationRequest(
            message="Build completed",
            notification_type=NotificationType.TASK,
            priority=NotificationPriority.MEDIUM
        )
        assert async_request.message == "Build completed"
        assert async_request.timeout == 5  # default
        print( "✓ AsyncNotificationRequest created successfully" )

        # Test 6: Async request validation
        print( "Testing async request timeout validation..." )
        try:
            AsyncNotificationRequest(
                message="Test",
                timeout=31  # Invalid (max is 30)
            )
            assert False, "Should have raised ValidationError"
        except ValidationError:
            print( "✓ Async timeout validation working" )

        # Test 7: Async response model
        print( "Testing AsyncNotificationResponse model..." )
        async_response = AsyncNotificationResponse(
            success=True,
            status="queued",
            target_user="test@example.com",
            connection_count=1
        )
        assert async_response.is_queued is True
        assert async_response.is_error is False
        print( "✓ AsyncNotificationResponse created successfully" )

        # Test 8: Async response properties
        print( "Testing async response is_error property..." )
        error_response = AsyncNotificationResponse(
            success=False,
            status="connection_error",
            target_user="test@example.com"
        )
        assert error_response.is_error is True
        print( "✓ Async response properties working" )

        print( "\n✓ Smoke test completed successfully (sync + async models)" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
