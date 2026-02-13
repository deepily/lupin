"""
Unit tests for notify_user_sync SSE client (Phase 2.3).

Tests SSE stream parsing, notification sending, and error handling
with mocked HTTP responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from cosa.cli.notify_user_sync import consume_sse_stream, notify_user_sync
from cosa.cli.notification_models import (
    NotificationRequest,
    NotificationResponse,
    RespondedEvent,
    ExpiredEvent,
    OfflineEvent,
    ErrorEvent,
    ResponseType
)


# ============================================================================
# SSE Stream Parsing Tests
# ============================================================================

class TestConsumeSSEStream:
    """Test SSE stream consumption and event parsing."""

    def test_parse_responded_event( self ):
        """Test parsing RespondedEvent from SSE stream."""
        # Mock response with SSE data
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "responded", "response": "yes", "default_used": false}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30, debug=False )

        assert isinstance( event, RespondedEvent )
        assert event.status == "responded"
        assert event.response == "yes"
        assert event.default_used is False

    def test_parse_expired_event_with_default( self ):
        """Test parsing ExpiredEvent with default value."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "expired", "response": "no", "default_used": true, "timeout": true}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert isinstance( event, ExpiredEvent )
        assert event.status == "expired"
        assert event.response == "no"
        assert event.default_used is True
        assert event.timeout is True

    def test_parse_offline_event( self ):
        """Test parsing OfflineEvent."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "offline", "response": "yes", "default_used": true}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert isinstance( event, OfflineEvent )
        assert event.status == "offline"
        assert event.response == "yes"
        assert event.default_used is True

    def test_parse_error_event( self ):
        """Test parsing ErrorEvent."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "error", "message": "User not found", "response": null}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert isinstance( event, ErrorEvent )
        assert event.status == "error"
        assert event.message == "User not found"
        assert event.response is None

    def test_skip_invalid_json( self ):
        """Test that invalid JSON lines are skipped."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {invalid json}',  # Should be skipped
            b'data: {"status": "responded", "response": "yes", "default_used": false}'  # Valid
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert isinstance( event, RespondedEvent )
        assert event.response == "yes"

    def test_skip_malformed_sse_lines( self ):
        """Test that malformed SSE lines are skipped."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'not a data line',  # Should be skipped
            b'data: {"status": "responded", "response": "yes", "default_used": false}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert isinstance( event, RespondedEvent )

    def test_empty_stream_returns_none( self ):
        """Test that empty stream returns None."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = []

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert event is None

    def test_stream_without_final_event_returns_none( self ):
        """Test stream without final event returns None."""
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "heartbeat"}',  # Not a final event
            b'data: {"status": "unknown"}'     # Unknown status
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )

        assert event is None


# ============================================================================
# notify_user_sync Function Tests
# ============================================================================

class TestNotifyUserSync:
    """Test notify_user_sync function with mocked requests."""

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_successful_yes_response( self, mock_post ):
        """Test successful yes response."""
        # Mock SSE response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "responded", "response": "yes", "default_used": false}'
        ]
        mock_post.return_value = mock_response

        # Create request
        request = NotificationRequest(
            message="Approve?",
            response_type=ResponseType.YES_NO,
            response_default="no"
        )

        # Send notification
        response = notify_user_sync( request, debug=False )

        assert response.exit_code == 0
        assert response.response_value == "yes"
        assert response.status == "responded"
        assert response.default_used is False
        assert response.success is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_timeout_with_default( self, mock_post ):
        """Test timeout using default value."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "expired", "response": "no", "default_used": true, "timeout": true}'
        ]
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Approve?",
            response_type=ResponseType.YES_NO,
            response_default="no"
        )

        response = notify_user_sync( request )

        assert response.exit_code == 2  # Timeout exit code
        assert response.response_value == "no"
        assert response.status == "expired"
        assert response.default_used is True
        assert response.is_timeout is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_offline_with_default( self, mock_post ):
        """Test offline user with default value."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "offline", "response": "yes", "default_used": true}'
        ]
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Approve?",
            response_type=ResponseType.YES_NO,
            response_default="yes"
        )

        response = notify_user_sync( request )

        assert response.exit_code == 0  # Offline with default = success
        assert response.response_value == "yes"
        assert response.status == "offline"
        assert response.default_used is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_http_error( self, mock_post ):
        """Test HTTP error response."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "User not found"
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
        )

        response = notify_user_sync( request )

        assert response.exit_code == 1
        assert response.response_value is None
        assert response.status == "http_error_404"
        assert response.is_error is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_connection_error( self, mock_post ):
        """Test connection error handling."""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError( "Cannot reach server" )

        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
        )

        response = notify_user_sync( request )

        assert response.exit_code == 1
        assert response.response_value is None
        assert response.status == "connection_error"

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_request_timeout( self, mock_post ):
        """Test request timeout handling."""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout( "Request timeout" )

        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
        )

        response = notify_user_sync( request )

        assert response.exit_code == 2  # Timeout exit code
        assert response.response_value is None
        assert response.status == "request_timeout"
        assert response.is_timeout is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_server_error_event( self, mock_post ):
        """Test server error SSE event."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "error", "message": "Internal server error", "response": null}'
        ]
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
        )

        response = notify_user_sync( request )

        assert response.exit_code == 1
        assert response.response_value is None
        assert response.status == "error"

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_expired_without_default( self, mock_post ):
        """Test expired notification without default value."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "expired", "response": null, "default_used": false, "timeout": true}'
        ]
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Test",
            response_type=ResponseType.YES_NO
            # No default provided
        )

        response = notify_user_sync( request )

        assert response.exit_code == 1  # Error (no default)
        assert response.response_value is None
        assert response.status == "expired_no_default"
        assert response.is_timeout is True

    @patch( 'cosa.cli.notify_user_sync.requests.post' )
    def test_open_ended_response( self, mock_post ):
        """Test open-ended text response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = [
            b'data: {"status": "responded", "response": "My custom answer", "default_used": false}'
        ]
        mock_post.return_value = mock_response

        request = NotificationRequest(
            message="Enter text",
            response_type=ResponseType.OPEN_ENDED
        )

        response = notify_user_sync( request )

        assert response.exit_code == 0
        assert response.response_value == "My custom answer"
        assert response.status == "responded"


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for notify_user_sync - validates basic functionality.
    """
    import cosa.utils.util as cu

    cu.print_banner( "notify_user_sync Smoke Test", prepend_nl=True )

    try:
        # Test 1: Create request
        print( "Testing NotificationRequest creation..." )
        request = NotificationRequest(
            message="Test notification",
            response_type=ResponseType.YES_NO,
            response_default="yes"
        )
        print( "✓ Request created successfully" )

        # Test 2: Mock SSE stream parsing
        print( "Testing SSE stream parsing..." )
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b'data: {"status": "responded", "response": "yes", "default_used": false}'
        ]

        event = consume_sse_stream( mock_response, timeout_seconds=30 )
        assert isinstance( event, RespondedEvent )
        print( f"✓ SSE event parsed: {event.model_dump_json()}" )

        # Test 3: Test exit code logic
        print( "Testing NotificationResponse..." )
        response = NotificationResponse(
            response_value="yes",
            exit_code=0,
            status="responded"
        )
        assert response.success is True
        print( "✓ NotificationResponse created successfully" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
