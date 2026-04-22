#!/usr/bin/env python3
"""
Unit tests for OrchestratorNotificationClient (Approach D).

Tests event filtering, job_id matching, priority handling,
and urgent interrupt signaling. All WebSocket operations mocked.
"""

import asyncio
import queue
import threading
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.swe_team.notification_client import OrchestratorNotificationClient


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def msg_queue():
    """Shared threading.Queue for test use."""
    return queue.Queue()


@pytest.fixture
def urgent_event():
    """Shared threading.Event for test use."""
    return threading.Event()


@pytest.fixture
def client( msg_queue, urgent_event ):
    """OrchestratorNotificationClient configured for testing."""
    return OrchestratorNotificationClient(
        user_email    = "test@example.com",
        job_id        = "swe-abc123",
        message_queue = msg_queue,
        urgent_event  = urgent_event,
        debug         = True,
    )


# =============================================================================
# Test: Event Filtering — notification_type
# =============================================================================

class TestEventTypeFiltering:
    """Test that only user_initiated_message notifications are queued."""

    def test_user_message_queued( self, client, msg_queue ):
        """user_initiated_message notification for correct job_id is queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-abc123",
                "message"  : "Use auth module",
                "priority" : "normal",
            }
        } ) )

        assert not msg_queue.empty()
        msg = msg_queue.get_nowait()
        assert msg[ "message" ] == "Use auth module"
        assert msg[ "priority" ] == "normal"

    def test_progress_notification_ignored( self, client, msg_queue ):
        """progress notifications are NOT queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "progress",
                "job_id"   : "swe-abc123",
                "message"  : "Task 1 complete",
                "priority" : "low",
            }
        } ) )

        assert msg_queue.empty()

    def test_alert_notification_ignored( self, client, msg_queue ):
        """alert notifications are NOT queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "alert",
                "job_id"   : "swe-abc123",
                "message"  : "Build failed",
                "priority" : "urgent",
            }
        } ) )

        assert msg_queue.empty()

    def test_task_notification_ignored( self, client, msg_queue ):
        """task notifications are NOT queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "task",
                "job_id"   : "swe-abc123",
                "message"  : "Starting decomposition",
                "priority" : "medium",
            }
        } ) )

        assert msg_queue.empty()

    def test_notification_type_field_also_works( self, client, msg_queue ):
        """notification_type field (alternative to type) is also recognized."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "notification_type" : "user_initiated_message",
                "job_id"            : "swe-abc123",
                "message"           : "Alternative field",
                "priority"          : "normal",
            }
        } ) )

        assert not msg_queue.empty()
        msg = msg_queue.get_nowait()
        assert msg[ "message" ] == "Alternative field"


# =============================================================================
# Test: Event Filtering — job_id
# =============================================================================

class TestJobIdFiltering:
    """Test that only messages for the target job_id are queued."""

    def test_matching_job_id_queued( self, client, msg_queue ):
        """Message with matching job_id is queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-abc123",
                "message"  : "Correct job",
                "priority" : "normal",
            }
        } ) )

        assert not msg_queue.empty()

    def test_wrong_job_id_ignored( self, client, msg_queue ):
        """Message with different job_id is NOT queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-other456",
                "message"  : "Wrong job",
                "priority" : "normal",
            }
        } ) )

        assert msg_queue.empty()

    def test_missing_job_id_ignored( self, client, msg_queue ):
        """Message with no job_id is NOT queued."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "message"  : "No job ID",
                "priority" : "normal",
            }
        } ) )

        assert msg_queue.empty()


# =============================================================================
# Test: Urgent Priority
# =============================================================================

class TestUrgentPriority:
    """Test urgent priority sets the interrupt event."""

    def test_urgent_sets_event( self, client, msg_queue, urgent_event ):
        """urgent priority message sets the threading.Event."""
        assert not urgent_event.is_set()

        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-abc123",
                "message"  : "URGENT: Stop!",
                "priority" : "urgent",
            }
        } ) )

        assert urgent_event.is_set()
        assert not msg_queue.empty()
        msg = msg_queue.get_nowait()
        assert msg[ "priority" ] == "urgent"

    def test_normal_does_not_set_event( self, client, msg_queue, urgent_event ):
        """normal priority message does NOT set the threading.Event."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-abc123",
                "message"  : "Normal message",
                "priority" : "normal",
            }
        } ) )

        assert not urgent_event.is_set()
        assert not msg_queue.empty()

    def test_medium_does_not_set_event( self, client, msg_queue, urgent_event ):
        """medium priority message does NOT set the threading.Event."""
        asyncio.run( client._on_event( "notification_queue_update", {
            "notification": {
                "type"     : "user_initiated_message",
                "job_id"   : "swe-abc123",
                "message"  : "Medium message",
                "priority" : "medium",
            }
        } ) )

        assert not urgent_event.is_set()


# =============================================================================
# Test: Non-notification events
# =============================================================================

class TestNonNotificationEvents:
    """Test that non-notification_queue_update events are ignored."""

    def test_job_state_transition_ignored( self, client, msg_queue ):
        """job_state_transition events are ignored."""
        asyncio.run( client._on_event( "job_state_transition", {
            "job_id"     : "swe-abc123",
            "from_state" : "queued",
            "to_state"   : "running",
        } ) )

        assert msg_queue.empty()

    def test_notification_responded_ignored( self, client, msg_queue ):
        """notification_responded events are ignored."""
        asyncio.run( client._on_event( "notification_responded", {
            "notification_id": "123",
            "response_value" : "yes",
        } ) )

        assert msg_queue.empty()

    def test_empty_notification_ignored( self, client, msg_queue ):
        """notification_queue_update with no notification data is ignored."""
        asyncio.run( client._on_event( "notification_queue_update", {} ) )
        assert msg_queue.empty()


# =============================================================================
# Test: Constructor and Configuration
# =============================================================================

class TestClientConfiguration:
    """Test client initialization and configuration."""

    def test_session_id_format( self, client ):
        """Session ID should include job_id."""
        assert client.session_id == "swe-notif-swe-abc123"

    def test_subscribed_events( self, client ):
        """Should subscribe to notification_queue_update and sys_ping."""
        assert "notification_queue_update" in client.subscribed_events
        assert "sys_ping" in client.subscribed_events

    def test_stores_target_job_id( self, client ):
        """Should store target job_id."""
        assert client._target_job_id == "swe-abc123"

    def test_stores_queue_reference( self, client, msg_queue ):
        """Should store shared queue reference."""
        assert client._message_queue is msg_queue

    def test_stores_event_reference( self, client, urgent_event ):
        """Should store shared event reference."""
        assert client._urgent_event is urgent_event

    def test_multiple_messages_queued_in_order( self, client, msg_queue ):
        """Multiple messages are queued in FIFO order."""
        for i in range( 3 ):
            asyncio.run( client._on_event( "notification_queue_update", {
                "notification": {
                    "type"     : "user_initiated_message",
                    "job_id"   : "swe-abc123",
                    "message"  : f"Message {i}",
                    "priority" : "normal",
                }
            } ) )

        messages = []
        while not msg_queue.empty():
            messages.append( msg_queue.get_nowait() )

        assert len( messages ) == 3
        assert messages[ 0 ][ "message" ] == "Message 0"
        assert messages[ 1 ][ "message" ] == "Message 1"
        assert messages[ 2 ][ "message" ] == "Message 2"
