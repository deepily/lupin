"""
THE CONTROL for the step-B0(iii) unreachability probes — the test the deletion cites.

WHAT THIS IS FOR. Steps 7a and 7c delete code on the strength of a STATIC search: grep
found no production caller of `RunningFifoQueue._process_fast_lane`, and nothing that arms
a blocking object, so `is_accepting_jobs()` is said never to go false. A probe was armed on
each branch to look for a caller a grep cannot see. But a probe that has never been SEEN to
fire proves nothing: "the branch was never reached" and "the probe was never wired" produce
exactly the same silence, and the second one looks like success.

So this file drives each probed path deliberately and asserts the probe recorded the hit.
Disarm any probe — delete its `trip()` call — and the matching test here goes red by name.
That is the receipt: it says the instrument works, so the quiet live-traffic window means
what it claims.

WHY IT LIVES IN THE REPO AND NOT IN A TRANSCRIPT. It was proven ad hoc first, and that
proof sat in one session's scrollback while the module docstring asked for it in the suite.
A control nobody can re-run is a claim, not evidence — and 7a/7c will cite this months from
now, when the transcript is gone.

DELETE THIS FILE WITH THE PROBES. It is scaffolding for one decision.

Venue: :7999-eligible unit — pure, no server, writes only to a tmp_path.
"""

from unittest.mock import MagicMock, patch

import pytest

import cosa.rest._unreachability_probe as probe


@pytest.fixture
def probe_log( tmp_path, monkeypatch ):
    """Point the probe at a throwaway file so a test never reads another run's trips."""
    target = tmp_path / "unreachability-probe.log"
    monkeypatch.setenv( "LUPIN_UNREACHABILITY_PROBE_PATH", str( target ) )
    return target


# ── the instrument itself ────────────────────────────────────────────────────

def test_a_trip_is_recorded_and_readable( probe_log ):
    probe.trip( probe.FAST_LANE, "detail=x" )
    lines = probe.trips()
    assert len( lines ) == 1
    assert probe.FAST_LANE in lines[ 0 ]
    assert "detail=x"      in lines[ 0 ]


def test_an_unarmed_run_and_a_quiet_run_look_identical_on_disk( probe_log ):
    """
    The ambiguity this whole exercise exists to remove, pinned so nobody forgets it.
    No file means NOTHING — it is equally consistent with a branch never reached and a
    probe never wired. Only the tests below, which make the real code fire, tell them
    apart.
    """
    assert probe.trips() == []
    assert not probe_log.exists()


def test_a_write_failure_never_breaks_the_code_being_watched( probe_log, monkeypatch ):
    """
    A tripwire that can take down the thing it watches is worse than no tripwire. Point it
    at an unwritable path and it must still return normally.
    """
    monkeypatch.setenv( "LUPIN_UNREACHABILITY_PROBE_PATH", "/proc/nonexistent/probe.log" )
    assert probe.trip( probe.FAST_LANE, "boom" ) is None


def test_reset_clears_the_window( probe_log ):
    probe.trip( probe.FAST_LANE )
    assert probe.trips()
    probe.reset()
    assert probe.trips() == []


# ── the armed branches — drive the REAL code, assert the probe saw it ────────

def test_the_fast_lane_probe_fires_when_the_method_runs( probe_log ):
    """
    Positive control for 7a. Disarm `_process_fast_lane` and this goes red.

    The method is driven with a job that takes its shortest branch — a CRUD agent, which
    skips the cache and hands straight off — because what is under test is that the probe
    fires on ENTRY, not what the method then does.
    """
    from cosa.rest.running_fifo_queue import RunningFifoQueue
    from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent

    class _CrudFake( CrudForDataFramesAgent ):
        # The real base wants a live agent's constructor args; the probe fires on entry,
        # before any of that is touched, so a bare subclass with the one attribute the
        # first line reads is enough — and keeps this control free of agent machinery.
        def __init__( self ): self.last_question_asked = "delete my 3pm"

    rq = MagicMock( spec=RunningFifoQueue )
    rq.debug = False
    rq._handle_base_agent = MagicMock( return_value="handled" )

    RunningFifoQueue._process_fast_lane( rq, _CrudFake() )

    recorded = probe.trips()
    assert any( probe.FAST_LANE in line for line in recorded ), (
        f"the fast-lane probe did not fire — it is disarmed, and a quiet live window "
        f"would prove nothing. Recorded: {recorded}"
    )


def test_the_blocking_gate_and_branch_probes_fire_when_a_blocking_object_is_armed( probe_log ):
    """
    Positive control for 7c, covering BOTH halves: the `is_accepting_jobs()` gate that
    makes the branch reachable, and the `run_previous_best_snapshot` branch itself.

    🔴 THIS DRIVES THE REAL `push_job`, and it has to. The first version of this test
    called `probe.trip()` directly and asserted the lines came back — which tests the
    probe module and NOTHING about the armed branches. Disarm both trips in
    todo_fifo_queue.py and that version stayed green: a vacuous control, which is worse
    than no control, because it looks like evidence. Caught before it shipped, and only by
    asking what the test would do if the thing it guards were removed.

    So: arm a real blocking object, make the confirmation dialogue say yes, and push a
    real question through. That is the one sequence the plan says nothing in the running
    system performs — and if it ever does, these probes are what will have caught it.
    """
    from unittest.mock import Mock, patch
    import cosa.rest.todo_fifo_queue as tfq
    from cosa.rest.todo_fifo_queue import TodoFifoQueue

    heavy = [ patch.object( tfq, name ) for name in
              ( "LlmClientFactory", "Gister", "GistNormalizer", "Normalizer",
                "QueryLogTable", "EmbeddingManager", "get_embedding_provider" ) ]
    for h in heavy: h.start()
    try:
        config_mgr = Mock()
        config_mgr.get = Mock( return_value="whatever" )
        queue = TodoFifoQueue( websocket_mgr=Mock(), snapshot_mgr=Mock(), app=Mock(),
                               config_mgr=config_mgr, debug=False, verbose=False )
        queue.gist_normalizer.get_normalized_gist        = Mock( return_value="gist" )
        queue.normalizer.normalize                       = Mock( return_value="normalized" )
        queue._embedding_provider.generate_embedding     = Mock( return_value=[ 0.1, 0.2 ] )
        queue.query_log.log_query                        = Mock()
        queue.user_job_tracker                           = Mock()

        snapshot = Mock()
        snapshot.id_hash = "snap-1"
        queue.push_blocking_object( { "best_snapshot": snapshot, "question": "the original question" } )

        confirmation = Mock()
        confirmation.confirmed.return_value = True

        with patch.object( tfq, "ConfirmationDialogue", return_value=confirmation ), \
             patch.object( queue, "_queue_best_snapshot", return_value={ "job_id": "j" } ), \
             patch.object( queue, "_dump_code" ), patch( "builtins.print" ):
            queue.push_job( "yes please", "ws-1", "u-1", "u@example.com" )
    finally:
        for h in reversed( heavy ): h.stop()

    recorded = probe.trips()
    assert any( probe.BLOCKING_GATE in line for line in recorded ), (
        f"the is_accepting_jobs() gate probe did not fire — it is disarmed. Recorded: {recorded}"
    )
    assert any( probe.BLOCKING_BRANCH in line for line in recorded ), (
        f"the run_previous_best_snapshot branch probe did not fire — it is disarmed. "
        f"Recorded: {recorded}"
    )


def test_every_named_probe_is_covered_by_this_file():
    """
    A probe added to PROBE_NAMES without a control here would ship uninstrumented and its
    silence would be read as evidence. Fail instead.
    """
    covered = { probe.FAST_LANE, probe.BLOCKING_GATE, probe.BLOCKING_BRANCH }
    assert set( probe.PROBE_NAMES ) == covered, (
        f"probe(s) with no control in this file: {set( probe.PROBE_NAMES ) - covered}"
    )
