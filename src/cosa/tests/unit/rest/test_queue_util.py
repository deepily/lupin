"""
Unit tests for emit_job_state_transition (cosa.rest.queue_util).

Covers transition validation, the WebSocket emission matrix (targeted vs
broadcast vs no-manager vs emit-failure), metadata inclusion, and the CJ Flow
persistence dispatch (created / started / completed / stalled / failed /
fall-through / non-agentic / persistence-failure) — to genuine 100% line +
branch + function.

All job_persistence calls are boundary-mocked (patched in the queue_util
namespace, plus the locally-imported persist_job_stalled at its source) — ZERO
DB access.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.rest.queue_util import emit_job_state_transition


class TestEmitJobStateTransition( unittest.TestCase ):
    """
    Validate emit_job_state_transition's emission + persistence branches.

    Ensures:
        - Invalid transitions raise ValueError before any side effect
        - Emission targets a user (dual-emit) or broadcasts, tolerates failures,
          and is skipped when no manager is supplied
        - Agentic persistence fires the correct helper per transition; non-agentic
          jobs skip persistence; helper failures are swallowed (logged)
    """

    def _ws( self ):
        ws = Mock()
        ws.emit = Mock()
        ws.emit_to_user_and_admins_sync = Mock()
        return ws

    def test_invalid_transition_raises( self ):
        with self.assertRaises( ValueError ):
            emit_job_state_transition( self._ws(), "job1", "pending", "running" )

    def test_no_websocket_manager_skips_emission( self ):
        # websocket_mgr None → emission block skipped; non-agentic → persistence skipped.
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False ):
            # Must not raise
            emit_job_state_transition( None, "job1", "pending", "queued" )

    def test_targeted_emission_with_user_id( self ):
        ws = self._ws()
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False ):
            emit_job_state_transition( ws, "job1", "pending", "queued", user_id="user1" )
        ws.emit_to_user_and_admins_sync.assert_called_once()
        args = ws.emit_to_user_and_admins_sync.call_args.args
        self.assertEqual( args[ 0 ], "user1" )
        self.assertEqual( args[ 1 ], "job_state_transition" )
        self.assertEqual( args[ 2 ][ "from_state" ], "pending" )
        self.assertEqual( args[ 2 ][ "to_state" ], "queued" )
        ws.emit.assert_not_called()

    def test_broadcast_emission_without_user_id( self ):
        ws = self._ws()
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False ):
            emit_job_state_transition( ws, "job1", "pending", "queued" )
        ws.emit.assert_called_once()
        self.assertEqual( ws.emit.call_args.args[ 0 ], "job_state_transition" )
        ws.emit_to_user_and_admins_sync.assert_not_called()

    def test_metadata_included_in_event( self ):
        ws = self._ws()
        meta = { "response_text": "hi", "agent_type": None }
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False ):
            emit_job_state_transition( ws, "job1", "pending", "queued", metadata=meta )
        data = ws.emit.call_args.args[ 1 ]
        self.assertEqual( data[ "metadata" ], meta )

    def test_emission_failure_is_swallowed( self ):
        ws = self._ws()
        ws.emit.side_effect = Exception( "ws down" )
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False ), \
             patch( "builtins.print" ) as mock_print:
            # Must not raise despite the emit failure
            emit_job_state_transition( ws, "job1", "pending", "queued" )
        # The except branch logged the failure
        self.assertTrue( any( "emit_job_state_transition failed" in str( c ) for c in mock_print.call_args_list ) )

    def test_persist_created_on_pending_to_queued( self ):
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_created_from_metadata" ) as mock_created:
            emit_job_state_transition( None, "job1", "pending", "queued", user_id="u1", metadata={ "agent_type": "deep_research" } )
        mock_created.assert_called_once_with( "job1", "u1", { "agent_type": "deep_research" } )

    def test_persist_started_on_queued_to_running( self ):
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_started_from_metadata" ) as mock_started:
            emit_job_state_transition( None, "job1", "queued", "running", metadata={ "agent_type": "deep_research" } )
        mock_started.assert_called_once_with( "job1", { "agent_type": "deep_research" } )

    def test_persist_completed_on_to_completed( self ):
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" ) as mock_done:
            emit_job_state_transition( None, "job1", "running", "completed", metadata={ "agent_type": "deep_research" } )
        mock_done.assert_called_once_with( "job1", { "agent_type": "deep_research" } )

    def test_persist_stalled_on_to_stalled( self ):
        # persist_job_stalled_from_metadata is imported locally inside the function
        # → patch it at its source module.
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.job_persistence.persist_job_stalled_from_metadata" ) as mock_stalled:
            emit_job_state_transition( None, "job1", "running", "stalled", metadata={ "agent_type": "deep_research" } )
        mock_stalled.assert_called_once_with( "job1", { "agent_type": "deep_research" } )

    def test_persist_failed_on_to_failed( self ):
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" ) as mock_failed:
            emit_job_state_transition( None, "job1", "running", "failed", metadata={ "agent_type": "deep_research" } )
        mock_failed.assert_called_once_with( "job1", { "agent_type": "deep_research" } )

    def test_agentic_transition_with_no_persist_arm_is_noop( self ):
        # QUEUED → PAUSED is valid + agentic but matches none of the persist arms.
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_created_from_metadata" ) as mock_created, \
             patch( "cosa.rest.queue_util.persist_job_started_from_metadata" ) as mock_started, \
             patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" ) as mock_done, \
             patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" ) as mock_failed:
            emit_job_state_transition( None, "job1", "queued", "paused", metadata={ "agent_type": "deep_research" } )
        mock_created.assert_not_called()
        mock_started.assert_not_called()
        mock_done.assert_not_called()
        mock_failed.assert_not_called()

    def test_persistence_failure_is_swallowed( self ):
        with patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True ), \
             patch( "cosa.rest.queue_util.persist_job_created_from_metadata", side_effect=Exception( "db down" ) ), \
             patch( "builtins.print" ) as mock_print:
            # Must not raise despite the persistence failure
            emit_job_state_transition( None, "job1", "pending", "queued", metadata={ "agent_type": "deep_research" } )
        self.assertTrue( any( "CJ Flow persistence failed" in str( c ) for c in mock_print.call_args_list ) )


def isolated_unit_test():
    """
    Run the queue_util unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} queue_util tests in {secs:.3f}s — {msg}" )
