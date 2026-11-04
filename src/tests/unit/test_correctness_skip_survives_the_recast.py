"""
Row 4cbd4858 — a job recast from an agent into a SolutionSnapshot keeps its test-suite lineage,
so the "Was this answer correct?" ask is skipped for it as it already is for replay jobs.

THE DEFECT (measured 2026-10-03, job ts-332ebcf6): 10 math jobs each waited the full 60 s on the
correctness ask. `_handle_base_agent` recasts the agent with `SolutionSnapshot.create`, which does
not carry `spawned_by_id_hash`, and `_confirm_correctness` then looked for the stamp on the snapshot.
The earlier tests set the stamp by hand on a fake snapshot, so none of them took an agent through
the recast.

THIS FILE DOES. The agent is a real `AgentBase` subclass, the recast is the real
`SolutionSnapshot.create`, the lineage walk and the ask are the real `RunningFifoQueue` methods. Only
the collaborators that need a database, a socket or a user are replaced, and the user is replaced by
a recorder, so "was the user asked" is an observation and not an assumption.

FALSIFIABILITY. Mutants this file reddens, by name, are listed in io/findings-4cbd4858-recast.md.
"""

import os
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cosa.rest.running_fifo_queue as rfq
from cosa.agents.agent_base import AgentBase
from cosa.agents.test_suite.job import TestSuiteJob
from cosa.memory.solution_snapshot import SolutionSnapshot


class _RealAgent( AgentBase ):
    """
    A real AgentBase. Only `do_all` is stood in for (it would otherwise call an LLM); it fills the
    two dicts `SolutionSnapshot.create` reads, exactly as a finished run leaves them.
    """

    def do_all( self ):
        self.prompt_response_dict  = { "explanation": "adds", "code": [ "x = 1" ], "returns": "int",
                                       "example": "1", "thoughts": "t" }
        self.code_response_dict    = { "return_code": 0, "output": "2" }
        self.answer_conversational = "the answer is two"
        return self.answer_conversational

    def code_ran_to_completion( self ):      return True
    def formatter_ran_to_completion( self ): return True
    def restore_from_serialized_state( self, path ): pass
    def is_code_runnable( self ):            return False
    def is_prompt_executable( self ):        return True
    def run_prompt( self, **kwargs ):        return {}
    def run_code( self, auto_debug=None, inject_bugs=None ): return {}
    def run_formatter( self ):               return ""
    def format_output( self ):               return ""


def _suite_job():
    return TestSuiteJob( test_types=[ "integration" ], user_id="u", user_email="e@x.y", session_id="wise penguin" )


@pytest.fixture
def harness( monkeypatch ):
    """
    A real RunningFifoQueue with its collaborators replaced, plus a recorder where the user would
    be. Returns ( queue, asks, saved ) — the requests the user was sent and the snapshots saved.
    """
    queue                 = object.__new__( rfq.RunningFifoQueue )
    queue._lock           = threading.RLock()
    queue.queue_dict      = { }
    queue.debug           = False
    queue.websocket_mgr   = None
    queue.snapshot_mgr    = MagicMock()
    queue.jobs_done_queue = MagicMock()
    queue.io_tbl          = MagicMock()
    queue.gist_normalizer = MagicMock()
    queue._notify         = MagicMock()
    queue.delete_by_id_hash = MagicMock()

    asks = []
    def fake_ask( request, **kw ):
        asks.append( request )
        return SimpleNamespace( status="expired", response_value=None )
    # The one thing in the real recast that needs a model server is the embedding call at
    # snapshot construction; it is stood in for, as test_solution_snapshot.py does. Everything
    # else in `SolutionSnapshot.create` runs for real.
    provider = MagicMock()
    provider.generate_embedding.return_value = [ 0.1 ] * 768
    monkeypatch.setattr( "cosa.memory.solution_snapshot.EmbeddingManager", MagicMock() )
    monkeypatch.setattr( "cosa.memory.solution_snapshot.get_embedding_provider", lambda *a, **k: provider )
    monkeypatch.setattr( rfq, "notify_user_sync", fake_ask )
    monkeypatch.setattr( rfq, "emit_job_state_transition", MagicMock() )

    saved = []
    queue.snapshot_mgr.save_snapshot.side_effect = lambda snap: saved.append( snap )
    return queue, asks, saved


def _agent( stamp=None ):
    agent = _RealAgent( question="what is 1 plus 1", routing_command="agent router go to math",
                        user_email="e@x.y" )
    if stamp is not None: agent.spawned_by_id_hash = stamp   # what the queued executor does to the job
    return agent


def _run( queue, agent ):
    queue.queue_dict[ agent.id_hash ] = agent
    return queue._handle_base_agent( agent, "what is 1 plus 1", rfq.sw.Stopwatch( "t" ) )


def test_a_suite_lineage_agent_is_recast_and_not_asked( harness ):
    queue, asks, saved = harness
    suite = _suite_job()
    queue.queue_dict[ suite.id_hash ] = suite

    result = _run( queue, _agent( stamp=suite.id_hash ) )

    assert isinstance( result, SolutionSnapshot ), "the real recast must have happened"
    assert asks == [], "a suite-lineage job must not be asked whether its answer was correct"
    assert result.answer_is_correct is True, "it takes the recorded 'yes' default, as a replay job does"
    assert saved and saved[ -1 ] is result


def test_the_recast_snapshot_carries_no_stamp_so_the_verdict_cannot_ride_it_into_the_store( harness ):
    """Pins the design: lineage is decided on the agent, and is never written onto the cached row."""
    queue, asks, saved = harness
    suite = _suite_job()
    queue.queue_dict[ suite.id_hash ] = suite

    result = _run( queue, _agent( stamp=suite.id_hash ) )

    assert not hasattr( result, "spawned_by_id_hash" )


def test_control_an_agent_with_no_suite_lineage_is_still_asked( harness ):
    queue, asks, saved = harness
    suite = _suite_job()
    queue.queue_dict[ suite.id_hash ] = suite

    _run( queue, _agent( stamp=None ) )

    assert len( asks ) == 1
    assert asks[ 0 ].sender_id == "queue.correctness@lupin.deepily.ai"
    assert asks[ 0 ].timeout_seconds == 60


def test_control_a_stamp_naming_a_job_that_is_not_a_suite_is_still_asked( harness ):
    queue, asks, saved = harness
    other = SimpleNamespace( id_hash="plain-job", job_type="agentic" )
    queue.queue_dict[ other.id_hash ] = other

    _run( queue, _agent( stamp=other.id_hash ) )

    assert len( asks ) == 1


def test_an_explicit_false_verdict_is_asked_even_if_the_snapshot_would_say_otherwise( harness ):
    """The caller's decision wins over a stamp on the snapshot; None alone means 'decide here'."""
    queue, asks, saved = harness
    suite = _suite_job()
    queue.queue_dict[ suite.id_hash ] = suite
    snap = SimpleNamespace( user_email="e@x.y", spawned_by_id_hash=suite.id_hash, id_hash="s", user_id="u",
                            answer_is_correct=None )

    queue._confirm_correctness( snap, "q", "a", suite_lineage=False )

    assert len( asks ) == 1


def test_no_verdict_given_means_the_snapshots_own_stamp_decides( harness ):
    """The replay and agentic callers pass nothing; their behaviour must be unchanged."""
    queue, asks, saved = harness
    suite = _suite_job()
    queue.queue_dict[ suite.id_hash ] = suite
    snap = SimpleNamespace( user_email="e@x.y", spawned_by_id_hash=suite.id_hash, id_hash="s", user_id="u",
                            answer_is_correct=None )

    queue._confirm_correctness( snap, "q", "a" )

    assert asks == []
    assert snap.answer_is_correct is True
