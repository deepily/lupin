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

from cosa.cli.notification_models import (
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
    ResponseType
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
            timeout_seconds=60,
            response_default="yes",
            title="Test Title"
        )

        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        assert params["message"] == "Test notification"
        assert params["type"] == "task"
        assert params["priority"] == "high"
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
            response_type=ResponseType.YES_NO
            # response_default and title are None
        )

        # Phase 2.5: API key moved to X-API-Key header, not in params
        params = request.to_api_params()

        assert "response_default" not in params
        assert "title" not in params
        assert "api_key" not in params  # Now in HTTP headers


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
        assert request.target_user == "ricardo.felipe.ruiz@gmail.com"  # default
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
        request = AsyncNotificationRequest( message="Test" )
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
