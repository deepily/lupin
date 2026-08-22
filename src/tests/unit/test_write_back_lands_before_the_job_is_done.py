"""The queue writes the snapshot BEFORE it reports the job done — driven, not read.

WHY THIS FILE EXISTS. `src/tests/integration/v2_queued.py` tells a round-trip test it may
trust the done queue as a write-back barrier: *"running_fifo_queue saves the snapshot
BEFORE it pushes the job onto the done queue. So a job visible in the done queue has
already had its write-back land, and a second identical ask can be expected to replay."*
That sentence is what makes the cold→warm round trip a fair test rather than a race, and
until now nothing checked it — it was read off the source by whoever wrote the helper.

IT ALSO HAD TO MOVE DOWN A TIER. The live half of that round trip cannot run on `:8000`
at all: the test-suite job is itself the queue's monopolizer, so a job submitted from
inside a suite run sits in `todo` until the suite ends and can never be observed draining
(row `ce29cd20`, confirmed on the box by maya). The integration tests keep the halves the
box can show — the hand-off, and the job's presence in `todo` under the id the API
returned — and the drain half is skipped there and pinned HERE, against a fake consumer.

WHAT IT DOES NOT CLAIM. Only `_handle_base_agent` — the path a cold v2 ask takes — is
covered. `_handle_solution_snapshot`, the replay path, pushes to done first and saves
runtime stats afterwards, which is correct for it: it updates a row that already exists,
so there is no barrier to keep. A test that asserted "save always precedes push" would be
asserting something the code deliberately does not do.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import threading
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.running_fifo_queue import RunningFifoQueue


def _queue():
    """A RunningFifoQueue with every collaborator faked, built without `__init__`.

    Mirrors the harness in test_crud_queue_integration.py: `__new__` skips the real
    constructor (which wants a live app, websocket manager and snapshot store), and the
    attributes the method under test actually touches are set by hand.

    The two collaborators whose ORDER is the subject — the snapshot store and the done
    queue — are attached to one parent mock, so `parent.mock_calls` records them on a
    single timeline. Two independent mocks could each say they were called and neither
    could say which came first, which is the entire question.
    """
    queue = RunningFifoQueue.__new__( RunningFifoQueue )

    recorder = MagicMock()
    queue.snapshot_mgr    = recorder.snapshot_mgr
    queue.jobs_done_queue = recorder.jobs_done_queue

    queue.debug            = False
    queue.verbose          = False
    queue.websocket_mgr    = MagicMock()
    queue.jobs_dead_queue  = MagicMock()
    queue.io_tbl           = MagicMock()
    queue.gist_normalizer  = MagicMock()
    queue.user_job_tracker = MagicMock()
    queue._lock            = threading.RLock()
    queue.queue_list       = [ ]
    queue.queue_dict       = OrderedDict()
    queue.push_counter     = 0
    queue.last_queue_size  = 0
    queue._agentic_futures      = { }
    queue._agentic_futures_lock = threading.RLock()

    queue._notify                      = MagicMock()
    queue._fire_correctness_check_async = MagicMock()
    queue.delete_by_id_hash            = MagicMock()

    return queue, recorder


def _completed_agent():
    """An agent that has already run and whose class the queue is willing to serialize.

    A MagicMock is none of ReceptionistAgent / WeatherAgent / CrudForDataFramesAgent, so
    it takes the serializing arm — which is the arm this test is about.
    """
    agent = MagicMock()
    agent.code_ran_to_completion      = MagicMock( return_value=True )
    agent.formatter_ran_to_completion = MagicMock( return_value=True )
    agent.do_all                      = MagicMock( return_value="four hundred and forty" )
    agent.run_formatter               = MagicMock( return_value="four hundred and forty" )
    agent.answer_conversational       = "four hundred and forty"
    agent.answer                      = "440"
    agent.id_hash                     = "cold-job-1"
    agent.user_id                     = "u1"
    agent.user_email                  = "u@example.com"
    agent.last_question_asked         = "what is 220 plus 220"
    agent.session_id                  = "s1"
    agent.started_at                  = "2026-08-21T20:00:00"
    agent.is_cache_hit                = False
    agent.routing_command             = "agent router go to math"
    return agent


def _snapshot_stub():
    """What `SolutionSnapshot.create` hands back — only the fields the method reads."""
    snapshot = MagicMock()
    snapshot.solution_summary_gist = "already-gisted"    # skips the lazy backfill
    snapshot.answer_conversational = "four hundred and forty"
    snapshot.answer                = "440"
    snapshot.id_hash               = "cold-job-1"
    snapshot.user_id               = "u1"
    snapshot.user_email            = "u@example.com"
    snapshot.last_question_asked   = "what is 220 plus 220"
    snapshot.session_id            = "s1"
    snapshot.started_at            = "2026-08-21T20:00:00"
    snapshot.is_cache_hit          = False
    snapshot.routing_command       = "agent router go to math"
    return snapshot


def _fake_snapshot_class( stub ):
    """A stand-in for the SolutionSnapshot CLASS whose `create` hands back `stub`.

    It has to be a real class, not a MagicMock: `_handle_base_agent` also asks
    `isinstance( running_job, SolutionSnapshot )` when it builds the completion metadata,
    and isinstance against a mock raises TypeError. Faking the class as a mock made the
    method die two lines before the push this test is timing — a failure that looks like
    the code is broken when it is the harness that is.
    """
    class _FakeSolutionSnapshot:
        @staticmethod
        def create( _job ):
            return stub
    return _FakeSolutionSnapshot


def _names_in_order( recorder ):
    """The two calls under test, in the order they happened, as bare names."""
    watched = ( "snapshot_mgr.save_snapshot", "jobs_done_queue.push" )
    return [ name for name, _args, _kwargs in recorder.mock_calls if name in watched ]


@patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" )
def test_a_completed_agent_is_saved_before_it_is_reported_done( _mock_emit ):
    """
    THE BARRIER. `_handle_base_agent` saves the snapshot, THEN pushes the job onto the
    done queue — so anything that watches the done queue is watching a point at which the
    row is already in the store.

    RED ON REVERT: move `save_snapshot` below `jobs_done_queue.push` and the recorded
    order flips. The integration round trip would then be a race that passes on a fast
    box and fails on a slow one, which is the failure mode a test is least likely to
    catch after the fact.
    """
    queue, recorder = _queue()

    with patch( "cosa.rest.running_fifo_queue.SolutionSnapshot", _fake_snapshot_class( _snapshot_stub() ) ):
        queue._handle_base_agent( _completed_agent(), "what is 220 plus 220", MagicMock() )

    order = _names_in_order( recorder )
    assert order == [ "snapshot_mgr.save_snapshot", "jobs_done_queue.push" ], (
        f"the queue reported the job done before its snapshot was stored: {order}. A "
        f"round-trip test that treats the done queue as a write-back barrier would then "
        f"be racing the store."
    )


@patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" )
def test_both_calls_actually_happen( _mock_emit ):
    """
    THE CONTROL, and it is not ceremony: an ordering assertion over an EMPTY list passes.
    If the harness drifted so that neither call fired — a changed guard, a renamed
    collaborator — the test above would go green while checking nothing at all.

    RED ON REVERT: stop serializing this class, or stop pushing to done, and this names
    which of the two went missing.
    """
    queue, recorder = _queue()

    with patch( "cosa.rest.running_fifo_queue.SolutionSnapshot", _fake_snapshot_class( _snapshot_stub() ) ):
        queue._handle_base_agent( _completed_agent(), "what is 220 plus 220", MagicMock() )

    order = _names_in_order( recorder )
    assert "snapshot_mgr.save_snapshot" in order, "no snapshot was saved — nothing to order"
    assert "jobs_done_queue.push" in order, "the job never reached the done queue"


def test_the_replay_path_is_deliberately_not_held_to_the_same_order():
    """
    THE SCOPE LINE, stated as a test so the next reader does not "fix" the replay path to
    match. `_handle_solution_snapshot` pushes to done and saves runtime stats AFTER — and
    that is right: it is updating a row that already exists, so there is no barrier to
    hold. The barrier belongs to the cold path, where the row does not exist yet.

    This asserts the current shape rather than endorsing it: if the replay path is ever
    reordered on purpose, this is the line that says the decision was made and not
    stumbled into.
    """
    import inspect
    source = inspect.getsource( RunningFifoQueue._handle_solution_snapshot )
    push   = source.index( "jobs_done_queue.push" )
    save   = source.index( "snapshot_mgr.save_snapshot" )
    assert push < save, (
        "the replay path now saves before pushing to done. That may well be an improvement "
        "— but it is a change of contract, and the comment in tests/integration/v2_queued.py "
        "about which path carries the barrier should move with it."
    )
