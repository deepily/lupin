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

def test_the_default_path_is_under_io_and_not_projects_data( monkeypatch ):
    """
    THE DEFAULT WRITE PATH, exercised with the override UNSET — the one thing every other
    test in this file hides.

    Each test below points the probe at a tmp_path via LUPIN_UNREACHABILITY_PROBE_PATH,
    which is right for isolation and wrong as the only coverage: it means the real
    path-derivation is never run, and the bug it had could come back invisibly.

    THE BUG THIS GUARDS. The first version derived `projects-data/<repo>/` by walking up
    from the project root and across to the sibling data dir, the way the heartbeat holds
    do. On the host that resolves correctly. Inside the dev container `get_project_root()`
    is /var/lupin, so the identical arithmetic produced `/projects-data/lupin/`, which
    nothing mounts — every trip would have landed in the container's throwaway layer, and
    the host would have shown an empty file that reads as "no trips." That is the exact
    false negative this probe exists to rule out: the instrument would have reported
    success by failing.

    So: the path must sit under `get_project_root()`, which is bind-mounted in the
    container and therefore the same file on both sides.
    """
    monkeypatch.delenv( "LUPIN_UNREACHABILITY_PROBE_PATH", raising=False )

    import cosa.utils.util as du
    resolved = probe.probe_path()

    assert resolved.endswith( "/io/unreachability-probe.log" ), (
        f"probe writes to {resolved!r}, which is not the io/ file the container and the "
        f"host share"
    )
    assert resolved.startswith( du.get_project_root().rstrip( "/" ) + "/" ), (
        f"probe writes to {resolved!r}, which is OUTSIDE the project root — in the dev "
        f"container that means an unmounted directory, and every trip is silently lost"
    )
    assert "projects-data" not in resolved, (
        f"probe writes to {resolved!r} — projects-data/ is the host-only derivation that "
        f"resolved to an unmounted path inside the container"
    )



def test_a_trip_is_recorded_and_readable( probe_log ):
    probe.trip( probe.BLOCKING_GATE, "detail=x" )
    lines = probe.trips()
    assert len( lines ) == 1
    assert probe.BLOCKING_GATE in lines[ 0 ]
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
    assert probe.trip( probe.BLOCKING_GATE, "boom" ) is None


def test_reset_clears_the_window( probe_log ):
    probe.trip( probe.BLOCKING_GATE )
    assert probe.trips()
    probe.reset()
    assert probe.trips() == []


# ── the armed branches — drive the REAL code, assert the probe saw it ────────

# The fast-lane positive control was DELETED with `_process_fast_lane` itself (step 7a,
# 2026-08-21). It had done its job: it proved the probe FIRES when the method runs, which
# is what made the quiet live window mean something rather than nothing. A control for a
# method that no longer exists cannot be kept honest, and the probe name went with it.


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
    covered = { probe.BLOCKING_GATE, probe.BLOCKING_BRANCH }
    assert set( probe.PROBE_NAMES ) == covered, (
        f"probe(s) with no control in this file: {set( probe.PROBE_NAMES ) - covered}"
    )
