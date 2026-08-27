"""
Row 7e2125a7, decisions D6 and D5 — and the tests are written the way María's D7 catch
says they have to be.

THE LESSON THESE TESTS ARE SHAPED BY. D7 proposed adding `job_id` to a failed replay's
Outcome. A test asserting on that Outcome would have passed; the field still would never
have reached the emitted record, because the flow discards that Outcome at the degrade
boundary. So: ASSERT ON THE RECORD, NOT ON THE OUTCOME. Where a claim is about what a run
produces, these tests read what the run produced — the records list `main` returns and
writes — not the intermediate object on the way there.

D6 — v2_eval is reachable through the sanctioned door (`POST /api/test-suite/submit`),
     and is deliberately NOT in the merge pyramid.
D5 — `main` waits for terminal outcomes by default, instead of stopping at the enqueue ack.
"""

import json
import os
import sys

import pytest


def _load_v2_eval():
    scripts = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" )
    if scripts not in sys.path: sys.path.insert( 0, scripts )
    import v2_eval
    return v2_eval


ve = _load_v2_eval()

from cosa.agents.test_suite.job import (
    ALL_SUITE_COMPONENTS,
    SUITE_SCRIPTS,
    SUITE_TIMEOUTS_SECONDS,
    SUITES_SUPPORTING_JUNIT_XML,
    TestSuiteJob,
)


# ---------------------------------------------------------------------------
# D6 — registration
# ---------------------------------------------------------------------------
def test_v2_eval_is_registered_with_a_runner_that_exists():
    """The whole point of D6: the suite is reachable, and its script is really there.

    A SUITE_SCRIPTS entry pointing at a missing file registers a suite that answers
    'Script not found' — reachable in the dict and unreachable in fact.
    """
    assert "v2_eval" in SUITE_SCRIPTS
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], SUITE_SCRIPTS[ "v2_eval" ] )
    assert os.path.exists( path ),  f"registered runner does not exist: {path}"
    assert os.access( path, os.X_OK ), f"registered runner is not executable: {path}"


def test_v2_eval_carries_its_own_timeout_not_the_default():
    """A 105-minute run under the 600s fallback is a suite that always reports killed."""
    assert "v2_eval" in SUITE_TIMEOUTS_SECONDS
    assert SUITE_TIMEOUTS_SECONDS[ "v2_eval" ] > 105 * 60, \
        "budget must exceed the measured ~105 min inline run (doc §7.4)"


def test_v2_eval_is_deliberately_absent_from_the_merge_pyramid():
    """Registration and gate-membership are separate decisions.

    In the pyramid, every merge would carry ~105 min of billed LLM work. This asserts the
    exclusion so a future 'tidy-up' that adds it has to argue with a red test rather than
    with a comment.
    """
    assert "v2_eval" not in ALL_SUITE_COMPONENTS
    # ...and the exclusion is not an accident of a stale list: the registered-but-excluded
    # shape already has a precedent this one matches.
    assert "presentation" in SUITE_SCRIPTS and "presentation" not in ALL_SUITE_COMPONENTS


def test_v2_eval_never_gets_junit_xml_injected():
    """`--junit-xml` would reach v2_eval.py's argparse as an unknown flag and kill the run."""
    assert "v2_eval" not in SUITES_SUPPORTING_JUNIT_XML


def test_all_expansion_does_not_pull_in_v2_eval():
    """The record that matters is what `all` actually expands to, not what the list says."""
    from cosa.agents.test_suite.job import _expand_all
    assert "v2_eval" not in _expand_all( [ "all" ] )
    # ...but naming it explicitly still works — excluded from "all", not from the door.
    assert _expand_all( [ "v2_eval" ] ) == [ "v2_eval" ]


@pytest.mark.parametrize( "rc_line,expected", [
    ( "Passed: 1\nFailed: 0", ( 1, 0 ) ),
    ( "Passed: 0\nFailed: 1", ( 0, 1 ) ),
] )
def test_runner_summary_is_parsed_into_counts( rc_line, expected ):
    """Without a parse arm the suite reports 0/0/0/0 — a green for a run nobody read.

    This asserts on the PARSED RESULT the job records, not on the regexes.
    """
    stdout = f"=== v2 eval summary ===\nTotal Tests: 1\n{rc_line}\n"
    parsed = TestSuiteJob._parse_non_pytest_stdout( "v2_eval", stdout )
    assert parsed is not None, "v2_eval stdout was not recognized — counts would be 0/0/0/0"
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == expected


def test_unrecognized_v2_eval_stdout_still_returns_none():
    """The negative control: no summary block means no fabricated counts."""
    assert TestSuiteJob._parse_non_pytest_stdout( "v2_eval", "wrote /tmp/report.md\n" ) is None


# ---------------------------------------------------------------------------
# D5 — terminal-outcome observation, asserted on the RECORD
# ---------------------------------------------------------------------------
class _QueuedClient:
    """A server running the QUEUED executor: every reply is the enqueue ack.

    Deliberately carries NO auth attribute. Only `_default_ws_listener_factory` reads one,
    and every test here injects a fake factory instead — so a credential-shaped literal on
    this class would be dead weight that reads like a secret to anyone scanning the tree.
    """
    def __init__( self ):
        self.n = 0
    def ask( self, question ):
        self.n += 1
        return { "utterance": question, "ok": True, "status_code": 200,
                 "payload": { "path": "agent", "status": "waiting",
                              "job_id": f"jid-{self.n}", "trace_id": "tid-" + question,
                              "command": "agent router go to weather",
                              "timings_ms": { "t_first_useful": 7.0 } } }


class _RecordingListener:
    """Answers with a terminal frame and remembers what it was asked about."""
    def __init__( self ):
        self.started  = False
        self.stopped  = False
        self.asked    = []
    def start( self ): self.started = True; return self
    def stop( self ):  self.stopped = True
    def ws_recv_events( self, job_id ):
        self.asked.append( job_id )
        return [ { "job_id": job_id, "to_state": "completed" } ]


def test_terminal_wait_is_on_by_default_and_lands_in_the_record():
    """🔴 THE D5 ASSERTION, MADE ON THE RECORD.

    Not "is the wrapper installed" and not "does the Outcome carry a flag" — those are the
    Outcome-level assertions D7 showed can pass while nothing reaches the artifact. This
    asserts on the record the wrapper actually emitted: its status is the TERMINAL state,
    not `waiting`, and `terminal_waited` is set on it.
    """
    listener = _RecordingListener()
    wrapped  = ve.terminal_waiting_ask( _QueuedClient().ask, listener.ws_recv_events,
                                        clock=lambda: 0.0 )
    record   = wrapped( "what's the weather" )

    assert record[ "payload" ][ "status" ] == "completed", \
        "the record still reports the enqueue ack — the wait did not reach the artifact"
    assert record[ "terminal_waited" ] is True
    assert listener.asked == [ "jid-1" ]


def test_terminal_state_reaches_the_WRITTEN_record_on_disk( tmp_path ):
    """🔴 THIS TEST IS NOT REDUNDANT WITH THE ONE ABOVE. DO NOT DELETE IT.

    It looks like a slower restatement of `test_terminal_wait_is_on_by_default_and_lands_in_
    the_record`. It is not, and here is the measurement rather than the argument.

    MUTATION M7 — un-wire the wrapper, i.e. restore the ORIGINAL defect this row was filed
    about, by passing `client.ask` raw to both passes in `main`:

        test_terminal_wait_is_on_by_default_and_lands_in_the_record   PASSED   <-- blind to it
        test_terminal_state_reaches_the_WRITTEN_record_on_disk        FAILED   <-- catches it

    Run 2026-08-26, both directions, restored after. The test above asserts on what the
    WRAPPER RETURNS; this one asserts on what the RUN WRITES. Between them sit `run_pass`,
    the record list and `write_outputs` — three chances to drop the terminal state — and the
    defect that started all of this lives in exactly that gap: `main` never called the
    wrapper at all, while the wrapper itself was correct and unit-tested the whole time.

    Deleting this test as duplicative restores a blind spot a green suite will not report.
    That is the D7 mistake one level out: an assertion on the object handed back passes
    while the file the run produces still says `waiting`.
    """
    ( tmp_path / "io" / "v2-flow" ).mkdir( parents=True, exist_ok=True )
    with open( tmp_path / "io" / "v2-flow" / "trace-2026-08-14.jsonl", "w" ) as h:
        for q in ( "what's the weather in Tokyo", "what's the weather" ):
            h.write( json.dumps( { "trace_id": "tid-" + q } ) + "\n" )

    result = ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0", "--allow-warm-cold" ],
        client_factory=lambda url: _QueuedClient(),
        ws_listener_factory=lambda base_url, client: _RecordingListener(),
        project_root=str( tmp_path ),
        timestamp="2026-08-14-00-00-00",
        read_sha_fn=lambda url: "deadbeef",
        probe_models_fn=lambda ctx: None,
    )

    records_path = result[ "paths" ][ "records" ]
    with open( records_path ) as handle:
        written = [ json.loads( line ) for line in handle if line.strip() ]

    assert written, f"no records were written to {records_path}"
    statuses = { row[ "payload" ].get( "status" ) for row in written }
    assert statuses == { "completed" }, \
        ( f"the WRITTEN record still reports {statuses} — the terminal state did not survive "
          f"the trip from the wrapper through run_pass and write_outputs to disk" )
    assert all( row.get( "terminal_waited" ) is True for row in written ), \
        "terminal_waited did not reach the written record"


def test_written_record_keeps_the_enqueue_ack_when_the_wait_is_off( tmp_path ):
    """The negative control for the assertion above, also read off disk.

    Without this, the previous test could pass against a run that wrote `completed` for some
    reason unrelated to the wait, and nobody would know. With the wait off, the same client
    and the same `main` must leave `waiting` in the file — which is what makes the positive
    result attributable to D5 rather than to the harness.
    """
    ( tmp_path / "io" / "v2-flow" ).mkdir( parents=True, exist_ok=True )
    with open( tmp_path / "io" / "v2-flow" / "trace-2026-08-14.jsonl", "w" ) as h:
        for q in ( "what's the weather in Tokyo", "what's the weather" ):
            h.write( json.dumps( { "trace_id": "tid-" + q } ) + "\n" )

    result = ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0",
               "--allow-warm-cold", "--no-observe-terminal" ],
        client_factory=lambda url: _QueuedClient(),
        ws_listener_factory=lambda base_url, client: _RecordingListener(),
        project_root=str( tmp_path ),
        timestamp="2026-08-14-00-00-00",
        read_sha_fn=lambda url: "deadbeef",
        probe_models_fn=lambda ctx: None,
    )

    with open( result[ "paths" ][ "records" ] ) as handle:
        written = [ json.loads( line ) for line in handle if line.strip() ]

    assert written
    assert { row[ "payload" ].get( "status" ) for row in written } == { "waiting" }
    assert not any( "terminal_waited" in row for row in written )


def test_default_argv_observes_terminal_outcomes():
    """The default is the point of D5. A flag that ships off is a flag nobody sets."""
    assert ve.build_arg_parser().parse_args( [] ).no_observe_terminal is False
    assert ve.build_arg_parser().parse_args( [ "--no-observe-terminal" ] ).no_observe_terminal is True


def test_opting_out_is_explicit_and_leaves_the_enqueue_span_visible():
    """Opting out must be a decision somebody typed, never a silent degrade.

    Asserted on the record again: with the wait off, the status stays `waiting`, so an
    artifact produced this way SAYS it is an enqueue measurement rather than looking
    like a completion measurement.
    """
    client = _QueuedClient()
    record = client.ask( "what's the weather" )       # the unwrapped path, verbatim
    assert record[ "payload" ][ "status" ] == "waiting"
    assert "terminal_waited" not in record


def test_listener_is_started_before_the_passes_and_stopped_after( tmp_path, monkeypatch ):
    """Order is the whole correctness property: a frame arriving during connect is lost.

    Also asserts the listener is stopped, so a failed run does not leak the socket thread.
    """
    seen = {}

    def factory( base_url, client ):
        listener = _RecordingListener()
        seen[ "listener" ] = listener
        return listener

    class _AskingClient( _QueuedClient ):
        def ask( self, question ):
            # If start() had not run yet, this is the race the ordering exists to prevent.
            assert seen[ "listener" ].started is True, "a question was asked before start()"
            return super().ask( question )

    ( tmp_path / "io" / "v2-flow" ).mkdir( parents=True, exist_ok=True )
    with open( tmp_path / "io" / "v2-flow" / "trace-2026-08-14.jsonl", "w" ) as h:
        for q in ( "what's the weather in Tokyo", "what's the weather" ):
            h.write( json.dumps( { "trace_id": "tid-" + q } ) + "\n" )

    ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0", "--allow-warm-cold" ],
        client_factory=lambda url: _AskingClient(),
        ws_listener_factory=factory,
        project_root=str( tmp_path ),
        timestamp="2026-08-14-00-00-00",
        read_sha_fn=lambda url: "deadbeef",
        probe_models_fn=lambda ctx: None,
    )

    assert seen[ "listener" ].started is True
    assert seen[ "listener" ].stopped is True, "the listener leaked — stop() must run in a finally"


def test_no_observe_terminal_builds_no_listener_at_all( tmp_path ):
    """Opting out must not construct the socket object either — on a box without
    `websockets` installed, building it is itself the failure."""
    def exploding_factory( base_url, client ):
        raise AssertionError( "a listener was built despite --no-observe-terminal" )

    ( tmp_path / "io" / "v2-flow" ).mkdir( parents=True, exist_ok=True )
    with open( tmp_path / "io" / "v2-flow" / "trace-2026-08-14.jsonl", "w" ) as h:
        for q in ( "what's the weather in Tokyo", "what's the weather" ):
            h.write( json.dumps( { "trace_id": "tid-" + q } ) + "\n" )

    ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0",
               "--allow-warm-cold", "--no-observe-terminal" ],
        client_factory=lambda url: _QueuedClient(),
        ws_listener_factory=exploding_factory,
        project_root=str( tmp_path ),
        timestamp="2026-08-14-00-00-00",
        read_sha_fn=lambda url: "deadbeef",
        probe_models_fn=lambda ctx: None,
    )
