"""
Unit tests for Notifications Database Operations.

Tests CRUD operations, state transitions, and query functionality using NotificationsDatabase class.
Phase 2.0 Foundation - Week 1
"""

import pytest
import sqlite3
import uuid
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Bootstrap for imports
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root:
    src_path = os.path.join( lupin_root, 'src' )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

from cosa.rest.notifications_database import NotificationsDatabase


# Database path for testing
TEST_DB_PATH = "/tmp/test_notifications.db"


@pytest.fixture
def test_db():
    """
    Create a test database with notifications table for testing.

    Ensures:
        - Fresh database created for each test
        - Schema matches production (23 fields, 3 indexes)
        - Database cleaned up after test
        - Returns NotificationsDatabase instance
    """
    # Remove existing test database
    if os.path.exists( TEST_DB_PATH ):
        os.remove( TEST_DB_PATH )

    # Create test database with notifications schema
    conn = sqlite3.connect( TEST_DB_PATH )
    cursor = conn.cursor()

    # Create notifications table (same schema as production)
    cursor.execute( """
        CREATE TABLE notifications (
            -- Identity
            id                      TEXT PRIMARY KEY,

            -- Routing
            sender_id               TEXT NOT NULL,
            recipient_id            TEXT NOT NULL,

            -- Source Context
            source_context          TEXT DEFAULT 'internal',
            source_sender           TEXT DEFAULT 'claude.code@deepily.ai',

            -- Content
            title                   TEXT NOT NULL,
            message                 TEXT NOT NULL,
            type                    TEXT NOT NULL,
            priority                TEXT NOT NULL,

            -- Timestamps
            created_at              TEXT NOT NULL,
            delivered_at            TEXT,
            expires_at              TEXT,
            deleted_at              TEXT,

            -- Response-Required Fields
            response_requested      INTEGER DEFAULT 0,
            response_type           TEXT,
            response_value          TEXT,
            responded_at            TEXT,
            timeout_seconds         INTEGER,
            response_default        TEXT,

            -- State Management
            state                   TEXT NOT NULL DEFAULT 'created',

            -- Legacy Compatibility
            played                  INTEGER DEFAULT 0,
            play_count              INTEGER DEFAULT 0,
            last_played             TEXT
        )
    """ )

    # Create indexes
    cursor.execute( "CREATE INDEX idx_recipient_state ON notifications(recipient_id, state)" )
    cursor.execute( "CREATE INDEX idx_recipient_created ON notifications(recipient_id, created_at)" )
    cursor.execute( "CREATE INDEX idx_expires_at ON notifications(expires_at) WHERE expires_at IS NOT NULL" )

    conn.commit()
    conn.close()

    # Return NotificationsDatabase instance pointing to test database
    db = NotificationsDatabase( db_path=TEST_DB_PATH, debug=False )

    yield db

    # Cleanup
    if os.path.exists( TEST_DB_PATH ):
        os.remove( TEST_DB_PATH )


class TestNotificationCRUD:
    """Test suite for basic CRUD operations using NotificationsDatabase class."""

    def test_create_notification( self, test_db ):
        """Test creating a new notification record."""
        notification_id = test_db.create_notification(
            sender_id    = "claude.code@deepily.ai",
            recipient_id = "user_123",
            title        = "Test Notification",
            message      = "This is a test message",
            type         = "task",
            priority     = "high"
        )

        assert notification_id is not None

        # Verify insertion
        notification = test_db.get_notification( notification_id )

        assert notification is not None
        assert notification["id"] == notification_id
        assert notification["sender_id"] == "claude.code@deepily.ai"
        assert notification["recipient_id"] == "user_123"
        assert notification["title"] == "Test Notification"

    def test_read_notification_by_id( self, test_db ):
        """Test reading a notification by its ID."""
        # Create notification
        notification_id = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "recipient_123",
            title        = "Title",
            message      = "Message",
            type         = "alert",
            priority     = "urgent"
        )

        # Read notification
        notification = test_db.get_notification( notification_id )

        assert notification is not None
        assert notification["title"] == "Title"
        assert notification["priority"] == "urgent"
        assert notification["state"] == "created"

    def test_update_notification_state( self, test_db ):
        """Test updating notification state (state transition)."""
        # Create notification
        notification_id = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_456",
            title        = "Title",
            message      = "Message",
            type         = "task",
            priority     = "medium"
        )

        # Update state: created → delivered
        delivered_at = datetime.utcnow().isoformat()
        success = test_db.update_state(
            notification_id,
            "delivered",
            delivered_at = delivered_at
        )

        assert success is True

        # Verify update
        notification = test_db.get_notification( notification_id )

        assert notification["state"] == "delivered"
        assert notification["delivered_at"] is not None

    def test_delete_notification_soft_delete( self, test_db ):
        """Test soft delete (state = 'deleted', keep row)."""
        # Create notification
        notification_id = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_789",
            title        = "Title",
            message      = "Message",
            type         = "progress",
            priority     = "low"
        )

        # Soft delete
        success = test_db.soft_delete( notification_id )

        assert success is True

        # Verify soft delete (row still exists)
        notification = test_db.get_notification( notification_id )

        assert notification is not None
        assert notification["state"] == "deleted"
        assert notification["deleted_at"] is not None


class TestNotificationQueries:
    """Test suite for notification query operations using NotificationsDatabase class."""

    def test_query_by_recipient_id( self, test_db ):
        """Test querying notifications by recipient."""
        # Create notifications for multiple users
        test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_a",
            title        = "Notification 1",
            message      = "Message 1",
            type         = "task",
            priority     = "high"
        )

        id2 = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_a",
            title        = "Notification 2",
            message      = "Message 2",
            type         = "alert",
            priority     = "urgent"
        )

        # Update second notification to delivered state
        test_db.update_state( id2, "delivered", delivered_at=datetime.utcnow().isoformat() )

        test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_b",
            title        = "Notification 3",
            message      = "Message 3",
            type         = "progress",
            priority     = "medium"
        )

        # Query notifications for user_a
        notifications = test_db.get_notifications_by_recipient( "user_a" )

        assert len( notifications ) == 2

    def test_query_by_state( self, test_db ):
        """Test querying notifications by state."""
        # Create notifications with different states
        id1 = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_x",
            title        = "N1",
            message      = "M1",
            type         = "task",
            priority     = "high"
        )

        id2 = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_x",
            title        = "N2",
            message      = "M2",
            type         = "task",
            priority     = "high"
        )

        id3 = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_x",
            title        = "N3",
            message      = "M3",
            type         = "task",
            priority     = "high"
        )

        # Update states
        test_db.update_state( id2, "delivered", delivered_at=datetime.utcnow().isoformat() )
        test_db.update_response( id3, '{"answer": "yes"}' )

        # Query delivered notifications
        delivered = test_db.get_notifications_by_recipient( "user_x", state="delivered" )

        assert len( delivered ) == 1

    def test_query_expired_notifications( self, test_db ):
        """Test querying notifications past their expiration time."""
        now = datetime.utcnow()

        # Create expired notification (120 second timeout, created in the past)
        id1 = test_db.create_notification(
            sender_id          = "sender@test.com",
            recipient_id       = "user_y",
            title              = "Expired",
            message            = "Message",
            type               = "task",
            priority           = "high",
            response_requested = True,
            timeout_seconds    = 1  # 1 second timeout (will expire immediately)
        )

        # Update to delivered state
        test_db.update_state( id1, "delivered", delivered_at=datetime.utcnow().isoformat() )

        # Create not-expired notification
        id2 = test_db.create_notification(
            sender_id          = "sender@test.com",
            recipient_id       = "user_y",
            title              = "Not Expired",
            message            = "Message",
            type               = "task",
            priority           = "high",
            response_requested = True,
            timeout_seconds    = 300  # 5 minutes timeout
        )

        # Update to delivered state
        test_db.update_state( id2, "delivered", delivered_at=datetime.utcnow().isoformat() )

        # Wait for first notification to expire
        import time
        time.sleep( 2 )

        # Query expired notifications
        expired = test_db.get_expired_notifications()

        assert len( expired ) >= 1  # At least the expired one


class TestStateTransitions:
    """Test suite for notification state machine transitions using NotificationsDatabase class."""

    def test_state_transition_created_to_delivered( self, test_db ):
        """Test state transition: created → delivered."""
        # Create notification in 'created' state
        notification_id = test_db.create_notification(
            sender_id    = "sender@test.com",
            recipient_id = "user_z",
            title        = "Title",
            message      = "Message",
            type         = "task",
            priority     = "high"
        )

        # Transition to 'delivered'
        delivered_at = datetime.utcnow().isoformat()
        test_db.update_state(
            notification_id,
            "delivered",
            delivered_at = delivered_at
        )

        # Verify transition
        notification = test_db.get_notification( notification_id )

        assert notification["state"] == "delivered"
        assert notification["delivered_at"] is not None

    def test_state_transition_delivered_to_responded( self, test_db ):
        """Test state transition: delivered → responded."""
        # Create notification in 'delivered' state
        notification_id = test_db.create_notification(
            sender_id          = "sender@test.com",
            recipient_id       = "user_w",
            title              = "Title",
            message            = "Message",
            type               = "task",
            priority           = "urgent",
            response_requested = True
        )

        # Transition to delivered first
        test_db.update_state(
            notification_id,
            "delivered",
            delivered_at = datetime.utcnow().isoformat()
        )

        # Transition to 'responded'
        response_value = '{"answer": "yes", "method": "button_click"}'
        test_db.update_response( notification_id, response_value )

        # Verify transition
        notification = test_db.get_notification( notification_id )

        assert notification["state"] == "responded"
        assert notification["responded_at"] is not None
        assert notification["response_value"] == response_value

    def test_state_transition_delivered_to_expired( self, test_db ):
        """Test state transition: delivered → expired (timeout)."""
        # Create notification with very short timeout (1 second)
        notification_id = test_db.create_notification(
            sender_id          = "sender@test.com",
            recipient_id       = "user_v",
            title              = "Title",
            message            = "Message",
            type               = "task",
            priority           = "high",
            response_requested = True,
            timeout_seconds    = 1  # 1 second timeout
        )

        # Transition to delivered
        test_db.update_state(
            notification_id,
            "delivered",
            delivered_at = datetime.utcnow().isoformat()
        )

        # Wait for expiration
        import time
        time.sleep( 2 )

        # Transition to 'expired'
        test_db.update_state( notification_id, "expired" )

        # Verify transition
        notification = test_db.get_notification( notification_id )

        assert notification["state"] == "expired"


if __name__ == "__main__":
    print( "Run with: pytest src/tests/unit/test_notifications_database.py -v" )
