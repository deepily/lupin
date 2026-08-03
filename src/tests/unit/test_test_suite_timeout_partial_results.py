"""
Unit tests for bug 8b93bcf5 — a timed-out tier used to discard every result it
had already produced, and its timeout could not fire while the child was quiet.

WHAT WENT WRONG, MEASURED LIVE 2026-07-26 on scheduled run ts-e69bfbbd:

    [TestSuiteJob] TIMEOUT: smoke exceeded 3600s, killing process
    smoke: FAILED — 0 passed, 0 failed, 1 errors, 0 skipped

The same run's own log showed the tier had reached 53% with ~17 failures and 1
error already on the floor. Two independent defects, one incident:

  DEFECT 1  --junit-xml is written only at session end, so a killed run leaves
            no junit, the parser falls back to zeros, and "0 passed, 0 failed,
            1 errors" becomes byte-identical to a tier that crashed at import,
            a tier whose script was missing, and a tier that collected nothing.

  DEFECT 2  the poll loop called process.stdout.readline() inline. readline()
            on a pipe BLOCKS, so the timeout and cancellation checks were
            reachable only BETWEEN lines. The kill landed ~9 minutes late, and
            the overrun was bounded by nothing but the child's silence.

Venue: :7999 / AI-discretionary. No server, no network, no persistent state.
The latency tests spawn short-lived `sleep`/`echo` children with sub-second
budgets and finish in a couple of seconds.
"""
import subprocess
import sys
import time

import pytest

from cosa.agents.test_suite.job import (
    TestSuiteJob,
    STDOUT_POLL_INTERVAL_SECONDS,
)


# The verbatim head of the real smoke log the incident produced. Using the
# genuine artifact rather than a hand-written fixture matters: a fixture I wrote
# would encode my own belief about pytest's format, and the belief is the thing
# under test.
REAL_SMOKE_LOG = """============================= test session starts ==============================
platform linux -- Python 3.13.7, pytest-8.4.2, pluggy-1.6.0
rootdir: /var/lupin
collected 1043 items

src/tests/smoke/test_alembic_create_all_bootstrap_idempotency.py FFF.F   [  1%]
src/tests/smoke/test_approach_d_user_messages.py F                       [  2%]
src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py F                   [  3%]
src/tests/smoke/test_conv_mode_three_layer_integration.py FF..F          [ 28%]
src/tests/smoke/test_external_scopes.py E....F.........                  [ 45%]
src/tests/smoke/test_io_files_endpoint.py .............s.                [ 51%]
src/tests/smoke/test_multiplexer_phase1_smoke.py F.
"""


# ══════════════════════════════════════════════════════════════════════════
# DEFECT 1 — partial results survive the kill
# ══════════════════════════════════════════════════════════════════════════

def test_real_incident_log_recovers_the_counts_that_were_thrown_away():
    r = TestSuiteJob._parse_pytest_progress_stdout( REAL_SMOKE_LOG )
    assert r is not None

    # Counted off the fixture above, per line:
    #   FFF.F           4F  1p
    #   F               1F
    #   F               1F
    #   FF..F           3F  2p
    #   E....F......... 1E  1F  13p
    #   .............s. 1s     14p
    #   F.              1F      1p
    #                  ----------------
    #                  11F  1E  1s  31p
    assert r[ "failed"  ] == 11
    assert r[ "errors"  ] == 1
    assert r[ "skipped" ] == 1
    assert r[ "passed"  ] == 31
    assert len( r[ "partial_files" ] ) == 7


def test_unrecognized_output_returns_None_not_zeros():
    """
    THE CENTRAL DISTINCTION. "I parsed nothing" must not render as
    "zero of everything" — collapsing them recreates the exact
    indistinguishable-zeros defect this whole change exists to end.
    """
    assert TestSuiteJob._parse_pytest_progress_stdout( "" ) is None
    assert TestSuiteJob._parse_pytest_progress_stdout( "Traceback (most recent call last):\n  File x\n" ) is None
    assert TestSuiteJob._parse_pytest_progress_stdout( "============ test session starts ====\ncollected 5 items\n" ) is None


def test_banners_and_tracebacks_are_not_miscounted_as_results():
    """
    A traceback line contains dots and capital E's. Miscounting one as results
    would be worse than recovering nothing — it would publish invented numbers.
    """
    noisy = (
        "============================= test session starts ====\n"
        "rootdir: /var/lupin\n"
        "E   AssertionError: expected 3, got 4\n"
        "src/tests/smoke/test_real.py ..F                       [ 10%]\n"
        "self.assertEqual( a, b )\n"
    )
    r = TestSuiteJob._parse_pytest_progress_stdout( noisy )
    assert r is not None
    assert ( r[ "passed" ], r[ "failed" ], r[ "errors" ] ) == ( 2, 1, 0 )
    assert len( r[ "partial_files" ] ) == 1


def test_wrapped_continuation_lines_are_attributed_to_the_open_file():
    """pytest wraps long runs onto a bare second line with no filename."""
    wrapped = (
        "src/tests/smoke/test_long.py ......................................\n"
        "..FF                                                        [ 12%]\n"
    )
    r = TestSuiteJob._parse_pytest_progress_stdout( wrapped )
    assert r is not None
    assert r[ "failed" ] == 2
    assert r[ "passed" ] == 40
    assert all( f == "src/tests/smoke/test_long.py" for f, _ in r[ "partial_files" ] )


def test_xfail_and_xpass_count_as_neither_pass_nor_failure():
    r = TestSuiteJob._parse_pytest_progress_stdout( "src/tests/smoke/test_x.py .xX.F   [ 5%]\n" )
    assert r is not None
    assert ( r[ "passed" ], r[ "failed" ] ) == ( 2, 1 )


# ══════════════════════════════════════════════════════════════════════════
# DEFECT 2 — the loop's own clock governs, not the child's chattiness
#
# These exercise the LOOP SHAPE that now lives in _run_suite: a drain
# thread feeding a queue, with the poll interval bounding how long the loop can
# be away from its checks. Each carries the CONTROL that made the original
# finding real — a chatty child, which the OLD code also handled correctly.
# Without that arm, a green here is equally explained by a wrong budget or a
# wrong suite key rather than by the fix.
# ══════════════════════════════════════════════════════════════════════════

def _run_loop( child_code, budget_secs ):
    """
    Drive a child through the post-fix loop shape and report when it was killed.

    Requires:
        - child_code is python source; budget_secs is the timeout under test

    Ensures:
        - returns ( killed_at_or_None, wallclock ) — killed_at is None when the
          child exited on its own before the budget expired
    """
    import queue as _queue
    import threading as _threading

    start   = time.monotonic()
    process = subprocess.Popen(
        [ sys.executable, "-u", "-c", child_code ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    q = _queue.Queue()

    def drain( pipe, out ):
        try:
            for line in iter( pipe.readline, "" ):
                out.put( line )
        finally:
            out.put( None )

    _threading.Thread( target=drain, args=( process.stdout, q ), daemon=True ).start()

    killed_at = None
    at_eof    = False
    while True:
        if time.monotonic() - start > budget_secs:
            process.terminate()
            try:
                process.wait( timeout=10 )
            except subprocess.TimeoutExpired:
                process.kill()
            killed_at = time.monotonic() - start
            break
        try:
            line = q.get( timeout=STDOUT_POLL_INTERVAL_SECONDS )
        except _queue.Empty:
            line = ""
        else:
            if line is None:
                at_eof = True
        if at_eof and process.poll() is not None:
            break

    return killed_at, time.monotonic() - start


SILENT_CHILD = "import time\ntime.sleep(30)\nprint('done')\n"
CHATTY_CHILD = "import time\nfor i in range(600):\n    print('tick', i)\n    time.sleep(0.05)\n"


def test_silent_child_is_killed_on_budget_not_on_its_next_line():
    """
    THE REGRESSION. Under the old inline readline(), this child's 30s silence
    made the kill 30s late. It must now land within a poll interval of budget.
    """
    budget = 1.0
    killed_at, wall = _run_loop( SILENT_CHILD, budget )
    assert killed_at is not None, "silent child was never killed"
    assert killed_at < budget + ( STDOUT_POLL_INTERVAL_SECONDS * 2 ) + 1.0, \
        f"kill landed {killed_at:.2f}s in against a {budget}s budget"
    assert wall < 10, f"loop ran {wall:.2f}s — nowhere near the child's 30s sleep, or it blocked"


def test_chatty_child_is_also_killed_on_budget():
    """
    CONTROL. The old code passed this too. If this ever goes red, the harness
    broke rather than the fix working — and every conclusion above is void.
    """
    budget = 1.0
    killed_at, _ = _run_loop( CHATTY_CHILD, budget )
    assert killed_at is not None
    assert killed_at < budget + ( STDOUT_POLL_INTERVAL_SECONDS * 2 ) + 1.0


def test_a_child_that_finishes_early_is_not_killed_and_output_is_complete():
    """
    The loop must still terminate normally AND drain every line. Requiring both
    EOF and process exit is what prevents a truncated log; a loop breaking on
    exit alone would drop buffered output, which is the artifact defect 1's
    recovery depends on.
    """
    child = "for i in range(50):\n    print('line', i)\n"
    killed_at, wall = _run_loop( child, 15.0 )
    assert killed_at is None, "a fast child must not be killed"
    assert wall < 15.0


# ══════════════════════════════════════════════════════════════════════════
# THE BRIDGE — drive the REAL _run_suite, not a copy of its loop
#
# The tests above prove the loop SHAPE is correct. They cannot prove job.py
# USES that shape, because _run_loop is a transcription of it. `project_root`
# is a parameter of _run_suite, so the real method can be pointed at a
# temp tree and a fake suite — which closes the gap rather than arguing it away.
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_suite( tmp_path, monkeypatch ):
    """
    Register a fake suite whose script this test writes, with a 1s budget.

    Ensures:
        - returns ( job, project_root, script_file ); the caller writes the
          script body
        - the suite name is absent from SUITES_SUPPORTING_JUNIT_XML, so no
          junit file is produced and the recovery path is the one exercised
    """
    from cosa.agents.test_suite import job as job_mod

    scripts_dir = tmp_path / "fake"
    scripts_dir.mkdir()
    script = scripts_dir / "suite.sh"

    monkeypatch.setitem( job_mod.SUITE_SCRIPTS, "faketier", "fake/suite.sh" )
    monkeypatch.setitem( job_mod.SUITE_TIMEOUTS_SECONDS, "faketier", 1 )
    assert "faketier" not in job_mod.SUITES_SUPPORTING_JUNIT_XML

    j = TestSuiteJob(
        test_types = [ "faketier" ],
        user_id    = "user-123",
        user_email = "test@test.com",
        session_id = "wise-penguin",
    )
    return j, str( tmp_path ), script


def test_real_method_kills_a_silent_suite_on_budget( fake_suite ):
    """
    THE REGRESSION, against the shipped code path. A suite silent for 30s used
    to hold the runner for the full 30s; the budget is 1s.
    """
    j, project_root, script = fake_suite
    script.write_text( "#!/usr/bin/env bash\nsleep 30\necho done\n" )

    started = time.monotonic()
    result  = j._run_suite( "faketier", project_root )
    elapsed = time.monotonic() - started

    assert result[ "exit_code" ] == -2, result
    assert "Timeout" in result[ "error" ]
    assert elapsed < 12, f"real method took {elapsed:.1f}s against a 1s budget — still blocking"


def test_kill_reaches_grandchildren_not_just_the_bash_wrapper( fake_suite, tmp_path ):
    """
    DEFECT 3, found by test_real_method_kills_a_silent_suite_on_budget failing at
    30.0s against a 1s budget while the TIMEOUT line printed on time.

    The runner is `bash <script>`. terminate() signals that bash alone, so a
    grandchild survives — and it inherited the stdout pipe, which is why the old
    blocking `process.stdout.read()` drain then waited for IT. The kill was
    punctual; the return was not.

    Assert the descendant is actually dead rather than merely that we returned
    quickly: returning quickly while leaving work running on the monopolize
    server is the worse failure of the two, and it is the silent one.
    """
    j, project_root, script = fake_suite
    marker = tmp_path / "grandchild-still-alive.txt"
    # TIMING IS THE WHOLE TEST. The marker must be written AFTER the kill (so it
    # cannot appear while the suite is legitimately running) but WELL BEFORE the
    # assertion (so a survivor has actually had its chance). Budget is 1s; the
    # grandchild writes at t+3s; we check at t+8s.
    #
    # The first version of this test slept 20s before touching and asserted at
    # t+7 — the marker could not have existed either way, so it passed against a
    # process-level kill and proved nothing. It was caught by a mutant that
    # degraded the group kill and stayed green.
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"( sleep 3; touch '{marker}' ) &\n"
        "sleep 30\n"
    )

    started = time.monotonic()
    result  = j._run_suite( "faketier", project_root )
    assert result[ "exit_code" ] == -2
    assert time.monotonic() - started < 12

    time.sleep( 8 )
    assert not marker.exists(), "a grandchild outlived the kill and kept running"


def test_real_method_publishes_partial_counts_instead_of_zeros( fake_suite ):
    """
    DEFECT 1, against the shipped code path. The suite emits pytest-shaped
    progress, then goes quiet until it is killed. The old code published
    0 passed / 0 failed / 1 errors and threw the rest away.
    """
    j, project_root, script = fake_suite
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '============================= test session starts ===='\n"
        "echo 'src/tests/smoke/test_a.py ..F   [ 10%]'\n"
        "echo 'src/tests/smoke/test_b.py .E.   [ 20%]'\n"
        "sleep 30\n"
    )

    result = j._run_suite( "faketier", project_root )

    assert result[ "exit_code" ] == -2
    assert result[ "passed" ] == 4, result          # ..  + .  . = 4
    assert result[ "failed" ] == 1, result
    # 1 recovered error + 1 for the timeout itself — a killed tier must never
    # report a clean bill, however much it managed to recover.
    assert result[ "errors" ] == 2, result
    assert "PARTIAL results recovered" in result[ "error" ]
