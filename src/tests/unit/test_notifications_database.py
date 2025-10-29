"""
Unit tests for Notifications Database Operations.

Tests CRUD operations, state transitions, and query functionality for the notifications table.
Phase 2.0 Foundation - Week 1
"""

import pytest
import sqlite3
import uuid
import os
from datetime import datetime, timedelta
from pathlib import Path


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

    yield TEST_DB_PATH

    # Cleanup
    if os.path.exists( TEST_DB_PATH ):
        os.remove( TEST_DB_PATH )


class TestNotificationCRUD:
    """Test suite for basic CRUD operations on notifications table."""

    def test_create_notification( self, test_db ):
        """Test creating a new notification record."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority, created_at, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            notification_id,
            "claude.code@deepily.ai",
            "user_123",
            "Test Notification",
            "This is a test message",
            "task",
            "high",
            now,
            "created"
        ) )

        conn.commit()

        # Verify insertion
        cursor.execute( "SELECT * FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == notification_id  # id
        assert row[1] == "claude.code@deepily.ai"  # sender_id
        assert row[2] == "user_123"  # recipient_id

        conn.close()

    def test_read_notification_by_id( self, test_db ):
        """Test reading a notification by its ID."""
        conn = sqlite3.connect( test_db )
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # Create notification
        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority, created_at, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "recipient_123", "Title", "Message", "alert", "urgent", now, "created") )
        conn.commit()

        # Read notification
        cursor.execute( "SELECT * FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row is not None
        assert row["title"] == "Title"
        assert row["priority"] == "urgent"
        assert row["state"] == "created"

        conn.close()

    def test_update_notification_state( self, test_db ):
        """Test updating notification state (state transition)."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # Create notification
        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority, created_at, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "user_456", "Title", "Message", "task", "medium", now, "created") )
        conn.commit()

        # Update state: created → delivered
        delivered_at = datetime.utcnow().isoformat()
        cursor.execute( """
            UPDATE notifications
            SET state = ?, delivered_at = ?
            WHERE id = ?
        """, ("delivered", delivered_at, notification_id) )
        conn.commit()

        # Verify update
        cursor.execute( "SELECT state, delivered_at FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row[0] == "delivered"
        assert row[1] is not None

        conn.close()

    def test_delete_notification_soft_delete( self, test_db ):
        """Test soft delete (state = 'deleted', keep row)."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # Create notification
        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority, created_at, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "user_789", "Title", "Message", "progress", "low", now, "delivered") )
        conn.commit()

        # Soft delete
        deleted_at = datetime.utcnow().isoformat()
        cursor.execute( """
            UPDATE notifications
            SET state = ?, deleted_at = ?
            WHERE id = ?
        """, ("deleted", deleted_at, notification_id) )
        conn.commit()

        # Verify soft delete (row still exists)
        cursor.execute( "SELECT state, deleted_at FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "deleted"
        assert row[1] is not None

        conn.close()


class TestNotificationQueries:
    """Test suite for notification query operations."""

    def test_query_by_recipient_id( self, test_db ):
        """Test querying notifications by recipient."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat()

        # Create notifications for multiple users
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_a", "Notification 1", "Message 1", "task", "high", now, "created") )

        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_a", "Notification 2", "Message 2", "alert", "urgent", now, "delivered") )

        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_b", "Notification 3", "Message 3", "progress", "medium", now, "created") )

        conn.commit()

        # Query notifications for user_a
        cursor.execute( "SELECT * FROM notifications WHERE recipient_id = ?", ("user_a",) )
        rows = cursor.fetchall()

        assert len( rows ) == 2

        conn.close()

    def test_query_by_state( self, test_db ):
        """Test querying notifications by state."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        now = datetime.utcnow().isoformat()

        # Create notifications with different states
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_x", "N1", "M1", "task", "high", now, "created") )

        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_x", "N2", "M2", "task", "high", now, "delivered") )

        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_x", "N3", "M3", "task", "high", now, "responded") )

        conn.commit()

        # Query delivered notifications
        cursor.execute( "SELECT * FROM notifications WHERE state = ?", ("delivered",) )
        rows = cursor.fetchall()

        assert len( rows ) == 1

        conn.close()

    def test_query_expired_notifications( self, test_db ):
        """Test querying notifications past their expiration time."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        now = datetime.utcnow()
        past = (now - timedelta( minutes=5 )).isoformat()
        future = (now + timedelta( minutes=5 )).isoformat()

        # Create notifications with different expiration times
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, expires_at, state, response_requested)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_y", "Expired", "Message", "task", "high", past, past, "delivered", 1) )

        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, expires_at, state, response_requested)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str( uuid.uuid4() ), "sender@test.com", "user_y", "Not Expired", "Message", "task", "high", now.isoformat(), future, "delivered", 1) )

        conn.commit()

        # Query expired notifications
        cursor.execute( "SELECT * FROM notifications WHERE expires_at IS NOT NULL AND expires_at < ?", (now.isoformat(),) )
        rows = cursor.fetchall()

        assert len( rows ) == 1

        conn.close()


class TestStateTransitions:
    """Test suite for notification state machine transitions."""

    def test_state_transition_created_to_delivered( self, test_db ):
        """Test state transition: created → delivered."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # Create notification in 'created' state
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "user_z", "Title", "Message", "task", "high", now, "created") )
        conn.commit()

        # Transition to 'delivered'
        delivered_at = datetime.utcnow().isoformat()
        cursor.execute( """
            UPDATE notifications
            SET state = ?, delivered_at = ?
            WHERE id = ? AND state = 'created'
        """, ("delivered", delivered_at, notification_id) )
        conn.commit()

        # Verify transition
        cursor.execute( "SELECT state, delivered_at FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row[0] == "delivered"
        assert row[1] is not None

        conn.close()

    def test_state_transition_delivered_to_responded( self, test_db ):
        """Test state transition: delivered → responded."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # Create notification in 'delivered' state
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, delivered_at, state, response_requested)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "user_w", "Title", "Message", "task", "urgent", now, now, "delivered", 1) )
        conn.commit()

        # Transition to 'responded'
        responded_at = datetime.utcnow().isoformat()
        response_value = '{"answer": "yes", "method": "button_click"}'

        cursor.execute( """
            UPDATE notifications
            SET state = ?, responded_at = ?, response_value = ?
            WHERE id = ? AND state = 'delivered'
        """, ("responded", responded_at, response_value, notification_id) )
        conn.commit()

        # Verify transition
        cursor.execute( "SELECT state, responded_at, response_value FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row[0] == "responded"
        assert row[1] is not None
        assert row[2] == response_value

        conn.close()

    def test_state_transition_delivered_to_expired( self, test_db ):
        """Test state transition: delivered → expired (timeout)."""
        conn = sqlite3.connect( test_db )
        cursor = conn.cursor()

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow()
        past = (now - timedelta( minutes=3 )).isoformat()

        # Create notification in 'delivered' state with expired timeout
        cursor.execute( """
            INSERT INTO notifications (id, sender_id, recipient_id, title, message, type, priority, created_at, delivered_at, expires_at, state, response_requested, timeout_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (notification_id, "sender@test.com", "user_v", "Title", "Message", "task", "high", past, past, past, "delivered", 1, 120) )
        conn.commit()

        # Transition to 'expired'
        cursor.execute( """
            UPDATE notifications
            SET state = ?
            WHERE id = ? AND state = 'delivered' AND expires_at < ?
        """, ("expired", notification_id, now.isoformat()) )
        conn.commit()

        # Verify transition
        cursor.execute( "SELECT state FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()

        assert row[0] == "expired"

        conn.close()


if __name__ == "__main__":
    print( "Run with: pytest src/tests/unit/test_notifications_database.py -v" )
