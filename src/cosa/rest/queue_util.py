"""
Queue utility functions for state transition events.

These functions are standalone because state transitions happen in disparate
locations (job submission, queue consumer, running queue) - not behaviors
inherently owned by any single queue class.
"""
from datetime import datetime
from typing import Any, Optional

import cosa.utils.util as du
from cosa.rest.job_state import JobState, assert_valid_transition, STATE_TO_UI_CONTAINER
from cosa.rest.job_persistence import (
    is_agentic_job_type,
    persist_job_created_from_metadata,
    persist_job_started_from_metadata,
    persist_job_completed_from_metadata,
    persist_job_failed_from_metadata
)


def emit_job_state_transition(
    websocket_mgr: Any,
    job_id: str,
    from_state: str,
    to_state: str,
    user_id: str = None,
    metadata: dict = None
) -> None:
    """
    Emit job state transition event with optional completion metadata.

    Requires:
        - websocket_mgr is not None (or function returns early)
        - job_id is a non-empty string
        - from_state and to_state are valid JobState values

    Ensures:
        - Validates transition against JobState transition matrix
        - Emits 'job_state_transition' event to WebSocket with from_state/to_state keys
        - Targets specific user if user_id provided
        - Falls back to broadcast if no user_id
        - Persists state transition to PostgreSQL for agentic job types (fire-and-forget)
        - Handles exceptions gracefully (both WS and persistence failures are logged, never raised)

    Args:
        websocket_mgr: WebSocket manager instance with emit() and emit_to_user_sync() methods
        job_id: Unique identifier for the job
        from_state: Source state (JobState value string or enum)
        to_state: Target state (JobState value string or enum)
        user_id: Optional user ID for targeted emission
        metadata: Optional dict with completion data (response_text, abstract, report_link, cost_summary, error)

    Raises:
        - ValueError if the state transition is invalid (from assert_valid_transition)
    """
    # Validate the transition is legal
    assert_valid_transition( from_state, to_state )

    # Normalize to JobState enum for consistent handling
    from_state = JobState( from_state )
    to_state   = JobState( to_state )

    # --- WebSocket emission ---
    if websocket_mgr:
        data = {
            'job_id'     : job_id,
            'from_state' : from_state.value,
            'to_state'   : to_state.value,
            'timestamp'  : du.get_current_datetime_iso()
        }

        if metadata:
            data[ 'metadata' ] = metadata

        try:
            if user_id:
                # Canonical dual-emit (owner + watching admins, deduplicated).
                # See WebSocketManager.emit_to_user_and_admins_sync for the
                # rationale — Session 248e740e fix moved the dual-call burden
                # off individual call sites and into one named method.
                websocket_mgr.emit_to_user_and_admins_sync( user_id, 'job_state_transition', data )
            else:
                websocket_mgr.emit( 'job_state_transition', data )
        except Exception as e:
            print( f"[ERROR] emit_job_state_transition failed: {e}" )

    # --- CJ Flow Persistence (fire-and-forget) ---
    # Only persist agentic job types; sync agents are cached in LanceDB
    agent_type = metadata.get( "agent_type" ) if metadata else None
    if is_agentic_job_type( agent_type ):
        try:
            if from_state == JobState.PENDING and to_state == JobState.QUEUED:
                persist_job_created_from_metadata( job_id, user_id, metadata )
            elif from_state == JobState.QUEUED and to_state == JobState.RUNNING:
                persist_job_started_from_metadata( job_id, metadata )
            elif to_state == JobState.COMPLETED:
                persist_job_completed_from_metadata( job_id, metadata )
            elif to_state == JobState.STALLED:
                from cosa.rest.job_persistence import persist_job_stalled_from_metadata
                persist_job_stalled_from_metadata( job_id, metadata or {} )
            elif to_state in ( JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED ):
                persist_job_failed_from_metadata( job_id, metadata or {} )
        except Exception as e:
            print( f"[WARN] CJ Flow persistence failed for {job_id}: {e}" )


def quick_smoke_test():
    """
    Quick smoke test for queue_util functions.
    """
    import cosa.utils.util as du

    du.print_banner( "Queue Utility Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import verification
        print( "Testing module import..." )
        from cosa.rest.queue_util import emit_job_state_transition
        print( "✓ emit_job_state_transition imported successfully" )

        # Test 2: Function with None websocket_mgr (should return early)
        print( "Testing with None websocket_mgr..." )
        emit_job_state_transition( None, "test-job-123", "todo", "run" )
        print( "✓ Gracefully handled None websocket_mgr" )

        # Test 3: Mock WebSocket manager
        print( "Testing with mock websocket_mgr..." )

        class MockWebSocketMgr:
            def __init__( self ):
                self.emitted_events = []
                self.user_events = []

            def emit( self, event_name, data ):
                self.emitted_events.append( ( event_name, data ) )

            def emit_to_user_sync( self, user_id, event_name, data ):
                self.user_events.append( ( user_id, event_name, data ) )

        mock_ws = MockWebSocketMgr()

        # Test broadcast emission
        emit_job_state_transition( mock_ws, "job-456", "pending", "queued" )
        assert len( mock_ws.emitted_events ) == 1, "Expected 1 broadcast event"
        event_name, data = mock_ws.emitted_events[ 0 ]
        assert event_name == "job_state_transition", f"Expected 'job_state_transition', got '{event_name}'"
        assert data[ "job_id" ] == "job-456", f"Expected job_id 'job-456', got '{data[ 'job_id' ]}'"
        assert data[ "from_state" ] == "pending", f"Expected from_state 'pending', got '{data[ 'from_state' ]}'"
        assert data[ "to_state" ] == "queued", f"Expected to_state 'queued', got '{data[ 'to_state' ]}'"
        print( "✓ Broadcast emission working" )

        # Test user-targeted emission
        emit_job_state_transition( mock_ws, "job-789", "running", "completed", user_id="user-123" )
        assert len( mock_ws.user_events ) == 1, "Expected 1 user-targeted event"
        user_id, event_name, data = mock_ws.user_events[ 0 ]
        assert user_id == "user-123", f"Expected user_id 'user-123', got '{user_id}'"
        assert event_name == "job_state_transition", f"Expected 'job_state_transition', got '{event_name}'"
        print( "✓ User-targeted emission working" )

        # Test with metadata
        mock_ws2 = MockWebSocketMgr()
        metadata = {
            'response_text' : 'Test response',
            'question_text' : 'What is 2+2?',
            'agent_type'    : 'MathAgent'
        }
        emit_job_state_transition( mock_ws2, "job-999", "running", "completed", metadata=metadata )
        assert len( mock_ws2.emitted_events ) == 1, "Expected 1 event with metadata"
        _, data = mock_ws2.emitted_events[ 0 ]
        assert "metadata" in data, "Expected metadata in event data"
        assert data[ "metadata" ][ "response_text" ] == "Test response", "Metadata content mismatch"
        print( "✓ Metadata inclusion working" )

        print( "\n✓ Queue utility smoke test completed successfully!" )

    except Exception as e:
        print( f"✗ Error during queue utility testing: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
