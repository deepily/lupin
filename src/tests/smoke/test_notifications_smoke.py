#!/usr/bin/env python3
"""
Smoke tests for Notifications System.

Quick sanity checks for notifications database, basic workflows, and LLM interpretation.
Phase 2.0 Foundation - Week 1
"""

import sys
import os
import sqlite3
import uuid
from datetime import datetime

# Bootstrap: Use LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/project\n"
        "  python src/tests/smoke/test_notifications_smoke.py"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

import cosa.utils.util as cu


def quick_smoke_test():
    """
    Quick smoke test for Notifications System - validates basic functionality.

    Tests:
    1. Database connection and table exists
    2. Basic CRUD workflow (create → read → update → delete)
    3. State transition workflow (created → delivered → responded)
    4. TODO: LLM interpretation helper (Phase 2.1)
    """
    cu.print_banner( "Notifications System Smoke Test", prepend_nl=True )

    try:
        # Test 1: Database connection and table exists
        print( "Test 1: Verifying database and table..." )
        db_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin-notifications.db"

        if not os.path.exists( db_path ):
            raise AssertionError( f"Database file not found: {db_path}" )

        conn = sqlite3.connect( db_path )
        cursor = conn.cursor()

        # Check table exists
        cursor.execute( """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='notifications'
        """ )
        table = cursor.fetchone()

        if not table:
            raise AssertionError( "Notifications table not found in database" )

        print( "✓ Database connected, notifications table exists" )

        # Test 2: Basic CRUD workflow
        print( "\nTest 2: Testing CRUD workflow..." )

        notification_id = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # CREATE
        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority, created_at, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            notification_id,
            "smoke.test@deepily.ai",
            "test_user_smoke",
            "Smoke Test Notification",
            "This is a smoke test notification for Phase 2.0",
            "task",
            "low",
            now,
            "created"
        ) )
        conn.commit()
        print( "✓ CREATE: Notification inserted" )

        # READ
        cursor.execute( "SELECT * FROM notifications WHERE id = ?", (notification_id,) )
        row = cursor.fetchone()
        if not row:
            raise AssertionError( "Failed to read created notification" )
        print( f"✓ READ: Notification retrieved (id: {notification_id[:8]}...)" )

        # UPDATE
        cursor.execute( """
            UPDATE notifications
            SET state = ?, delivered_at = ?
            WHERE id = ?
        """, ("delivered", datetime.utcnow().isoformat(), notification_id) )
        conn.commit()

        cursor.execute( "SELECT state FROM notifications WHERE id = ?", (notification_id,) )
        updated_state = cursor.fetchone()[0]
        if updated_state != "delivered":
            raise AssertionError( f"State update failed: expected 'delivered', got '{updated_state}'" )
        print( "✓ UPDATE: State transitioned (created → delivered)" )

        # DELETE (soft delete)
        cursor.execute( """
            UPDATE notifications
            SET state = ?, deleted_at = ?
            WHERE id = ?
        """, ("deleted", datetime.utcnow().isoformat(), notification_id) )
        conn.commit()

        cursor.execute( "SELECT state FROM notifications WHERE id = ?", (notification_id,) )
        deleted_state = cursor.fetchone()[0]
        if deleted_state != "deleted":
            raise AssertionError( f"Soft delete failed: expected 'deleted', got '{deleted_state}'" )
        print( "✓ DELETE: Soft delete successful (state = deleted)" )

        # Cleanup: Hard delete test notification
        cursor.execute( "DELETE FROM notifications WHERE id = ?", (notification_id,) )
        conn.commit()
        print( "✓ Cleanup: Test notification removed" )

        # Test 3: State transition workflow
        print( "\nTest 3: Testing state transition workflow..." )

        notification_id_2 = str( uuid.uuid4() )
        now = datetime.utcnow().isoformat()

        # created → delivered → responded
        cursor.execute( """
            INSERT INTO notifications (
                id, sender_id, recipient_id, title, message, type, priority,
                created_at, state, response_requested, response_type, timeout_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            notification_id_2, "smoke.test@deepily.ai", "test_user_smoke",
            "Response Required Test", "Do you want to continue?",
            "alert", "high", now, "created", 1, "yes_no", 120
        ) )
        conn.commit()
        print( "✓ Created response-required notification" )

        # Transition: created → delivered
        cursor.execute( """
            UPDATE notifications
            SET state = ?, delivered_at = ?
            WHERE id = ?
        """, ("delivered", datetime.utcnow().isoformat(), notification_id_2) )
        conn.commit()
        print( "✓ Transitioned: created → delivered" )

        # Transition: delivered → responded
        cursor.execute( """
            UPDATE notifications
            SET state = ?, responded_at = ?, response_value = ?
            WHERE id = ?
        """, (
            "responded",
            datetime.utcnow().isoformat(),
            '{"answer": "yes", "method": "smoke_test", "confidence": "high"}',
            notification_id_2
        ) )
        conn.commit()
        print( "✓ Transitioned: delivered → responded" )

        # Verify final state
        cursor.execute( "SELECT state, response_value FROM notifications WHERE id = ?", (notification_id_2,) )
        final_row = cursor.fetchone()
        if final_row[0] != "responded":
            raise AssertionError( f"Final state incorrect: expected 'responded', got '{final_row[0]}'" )
        print( f"✓ Final state verified: {final_row[0]}" )

        # Cleanup
        cursor.execute( "DELETE FROM notifications WHERE id = ?", (notification_id_2,) )
        conn.commit()
        print( "✓ Cleanup: Test notification removed" )

        # Test 4: LLM interpretation helper (placeholder for Phase 2.1)
        print( "\nTest 4: LLM interpretation helper..." )
        print( "⊘ SKIPPED: LLM interpretation helper not implemented until Phase 2.1" )
        print( "  (Will test: 'sure' → 'yes', 'nope' → 'no', etc.)" )

        conn.close()

        print( "\n" + "="*60 )
        print( "✓ Smoke test completed successfully" )
        print( "="*60 )

        return 0

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( quick_smoke_test() )
