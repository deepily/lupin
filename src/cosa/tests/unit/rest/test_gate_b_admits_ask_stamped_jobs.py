"""
Row 4cbd4858 — the consumer's Gate B admits a NON-agentic job that /api/v2/ask stamped with its
monopolizer's id, and still defers the same kind of job when nothing stamped it.

The existing lineage tests drive AgenticJobBase children. An ask enqueues something else: an
AgentBase or SolutionSnapshot, which has no `spawned_by_id_hash` of its own until the queued
executor sets one. This test runs that whole chain with the REAL pieces that matter:

    QueuedExecutor stamps the job  ->  a REAL FifoQueue holds it  ->  the REAL predicate Gate B
    builds (captured from the consumer loop) decides  ->  FifoQueue.pop_next_eligible( predicate )

Only the job objects are doubles, built WITHOUT the attribute (`del`) so they behave like the
classes that never carried it.

Venue: :7999 (unit, no server).
"""

import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

import cosa.rest.queue_consumer as qc
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state import JobState
from cosa.rest.queue_protocol import QueueableJob
from cosa.rest.v2.executor import QueuedExecutor, Work
from cosa.rest.v2.trace import StageTrace

PARENT = "monopolizing-suite-job"


def _non_agentic_job( id_hash ):
    """
    A queueable job like AgentBase / SolutionSnapshot: immediate, never monopolizes, and NO
    lineage attribute. Built as a real class carrying exactly the QueueableJob protocol members,
    because the runtime protocol check ignores a Mock's dynamic attributes (Python 3.13) and
    FifoQueue.push enforces it.
    """
    members = { name: None for name in QueueableJob.__protocol_attrs__ }
    for method in ( "do_all", "code_ran_to_completion", "formatter_ran_to_completion" ):
        members[ method ] = lambda self: None
    members.update( id_hash=id_hash, monopolize=False, scheduled_at=None, user_id="u1",
                    user_email="u@e.com", state=JobState.PENDING )
    return type( "NonAgenticJob", ( ), members )()


class _Tracker:
    def register_scoped_job( self, base, user_id, session_id=None ): return base


class _TodoForExecutor:
    """What QueuedExecutor needs from the todo queue; pushes into the real FifoQueue."""
    def __init__( self, fifo ):
        self.fifo             = fifo
        self.user_job_tracker = _Tracker()
    def push( self, job ):  self.fifo.push( job )
    def size( self ):       return self.fifo.size()


def _gate_b_predicate():
    """Run the real consumer loop one step under a hold and return the predicate it built."""
    captured = {}
    todo     = MagicMock( name="todo" )
    todo.consumer_running = True
    todo.debug            = False
    todo.condition        = MagicMock( name="condition" )

    def _capture( *args, **kwargs ):
        captured[ "predicate" ] = kwargs[ "predicate" ]
        todo.consumer_running   = False
        return None
    todo.pop_next_eligible.side_effect = _capture

    running = Mock()
    running._consumer_stall_threshold_seconds = 120
    running._monopolize_active                = PARENT
    running._is_monopolize_enabled.return_value = True

    with patch.object( qc.threading, "Thread" ) as thread, patch.object( qc.time, "sleep" ), \
         patch.object( qc, "emit_job_state_transition" ), patch( "builtins.print" ):
        qc.start_todo_producer_run_consumer_thread( todo, running )
        thread.call_args.kwargs[ "target" ]()
    return captured[ "predicate" ]


class TestGateBAdmitsAskStampedJobs( unittest.TestCase ):

    def _enqueue( self, fifo, job, parent=None ):
        trace = StageTrace( trace_dir="/tmp/unused" )
        if parent: trace.set( "parent_id_hash", parent )
        out = QueuedExecutor( _TodoForExecutor( fifo ) ).submit(
            Work( "agent", job, "u1", "u@e.com", "s1", snapshotable=True ), trace )
        self.assertEqual( "waiting", out.status )

    def test_a_stamped_job_passes_the_hold_and_an_unstamped_one_ahead_of_it_stays_deferred( self ):
        fifo      = FifoQueue( websocket_mgr=MagicMock(), queue_name="todo", emit_enabled=False )
        foreign   = _non_agentic_job( "foreign-ask" )         # control: same kind of job, no parent sent
        child     = _non_agentic_job( "suite-ask" )           # made on the suite's behalf
        self._enqueue( fifo, foreign )                        # first in the FIFO
        self._enqueue( fifo, child, parent=PARENT )
        predicate = _gate_b_predicate()

        first = fifo.pop_next_eligible( predicate=predicate )
        self.assertIs( child, first, "the stamped job must be admitted through the hold, past the foreign job ahead of it" )
        self.assertEqual( PARENT, child.spawned_by_id_hash )

        self.assertIsNone( fifo.pop_next_eligible( predicate=predicate ),
                           "the unstamped control must stay deferred while the hold is active" )
        self.assertEqual( [ foreign ], list( fifo.queue_list ), "and it stays queued, FIFO-intact" )
        self.assertFalse( hasattr( foreign, "spawned_by_id_hash" ), "the control was never touched" )

    def test_a_job_stamped_for_a_different_monopolizer_is_deferred( self ):
        fifo  = FifoQueue( websocket_mgr=MagicMock(), queue_name="todo", emit_enabled=False )
        other = _non_agentic_job( "other-suite-ask" )
        self._enqueue( fifo, other, parent="some-other-monopolizer" )
        self.assertIsNone( fifo.pop_next_eligible( predicate=_gate_b_predicate() ) )


if __name__ == "__main__":
    unittest.main()
