"""
A filtered run must not be reported as a full suite.

THE DEFECT. run-e2e-ui-tests.sh printed "✓ All E2E UI tests passed!" on exit 0
unconditionally and never echoed its args. All three 2026-09-24 reports under
io/test-suite/ were `-k` filtered — 891 deselected, 33 / 43 / 45 selected — and two of them
carry that banner verbatim. The banner is the line a reader skims to, so the run's strongest
claim was also its most false one, and the evidence against it (pytest's
selected/deselected line, hundreds of lines up; the argv, printed nowhere) was not where
anyone would look.

WHAT IS ASSERTED HERE. src/scripts/lib/report-run-scope.sh derives the claim from pytest's
own summary line instead of asserting over it, and run-e2e-ui-tests.sh actually calls it.

⚠️ THE NEGATIVE CASES ARE THE POINT, not padding. A lib that shouted "NOT THE WHOLE SUITE"
on every run would pass the positive test and be ignored inside a week — and worse, it would
make the honest full-suite banner unreachable. So:

  · test_a_full_green_run_still_says_all_tests_passed   keeps the true claim sayable
  · test_a_filter_that_narrows_nothing_is_a_full_run    is the one that settles the DESIGN:
    `-k test_` matches everything, pytest deselects nothing, and this must read as full. An
    argv-sniffing implementation calls it filtered and fails this test. That is deliberate —
    it is how this file distinguishes asking the gate from restating its rule.

PROVED BY CONSTRUCTION, in the shape of test_runner_coverage_blindness.py next door: every
case sources the REAL lib and parses the output of a REAL pytest run over tmp_path. No
summary line in this file is hand-written, so no assertion here can pass because of a string
this file invented — with one named exception, test_no_summary_line_reads_as_unknown, whose
whole subject is the absence of pytest output.

Venue: :7999-eligible. Subprocess pytest over tmp_path; no server, no network, no state
mutation outside tmp_path. Whole file is seconds.
"""

import os
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
SCOPE_LIB    = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "report-run-scope.sh" )
DIAGNOSIS_LIB= os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "pytest-with-diagnosis.sh" )
E2E_RUNNER   = os.path.join( PROJECT_ROOT, "src", "scripts", "run-e2e-ui-tests.sh" )
PYTEST_BIN   = os.path.join( PROJECT_ROOT, ".venv", "bin", "pytest" )

FULL_CLAIM    = "All E2E UI tests passed!"
PARTIAL_CLAIM = "THIS IS NOT THE WHOLE"
EMPTY_CLAIM   = "NO TESTS RAN"
UNKNOWN_CLAIM = "scope of this run is UNKNOWN"


# ---------------------------------------------------------------------------
# The instrument, before any reading taken with it
# ---------------------------------------------------------------------------

def test_the_files_and_interpreter_this_file_depends_on_exist():
    """
    Every case below shells out to these paths. If one moved, the subprocesses would fail
    for a reason unrelated to the property under test and a reader would be left debugging
    this file instead of the banner.
    """
    assert os.path.isfile( SCOPE_LIB ),     f"report-run-scope.sh is not at {SCOPE_LIB}"
    assert os.path.isfile( DIAGNOSIS_LIB ), f"pytest-with-diagnosis.sh is not at {DIAGNOSIS_LIB}"
    assert os.path.isfile( E2E_RUNNER ),    f"run-e2e-ui-tests.sh is not at {E2E_RUNNER}"
    assert os.access( PYTEST_BIN, os.X_OK ), f"no runnable venv pytest at {PYTEST_BIN}"


# ---------------------------------------------------------------------------
# Helpers — a real suite, a real pytest, a real summary line
# ---------------------------------------------------------------------------

def _suite( tmp_path, name="suite" ):
    """
    Write a three-test suite whose names let `-k` select a strict subset.

    Ensures:
        - exactly 3 collectable tests, one of them marked `slow`
        - returns the directory as a str
    """
    d = tmp_path / name
    d.mkdir()
    ( d / "test_probe.py" ).write_text(
        "import pytest\n"
        "def test_alpha(): assert True\n"
        "def test_beta(): assert True\n"
        "@pytest.mark.slow\n"
        "def test_gamma(): assert True\n"
    )
    return str( d )


def _real_summary_line( suite_dir, *pytest_args ):
    """
    Run the REAL pytest and return the REAL summary line it printed, via the same
    run_scope_summary_line parser the runner uses.

    This is what keeps the file honest: the strings the assertions below reason about are
    produced by pytest, not by this module.

    Ensures:
        - returns ( summary_line, pytest_exit_code )
        - raises AssertionError if the parser found no summary line, because every arm here
          is a run that certainly printed one — a silent empty string would make the
          downstream assertion vacuous
    """
    log  = os.path.join( suite_dir, "pytest-output.log" )
    args = " ".join( f"'{a}'" for a in pytest_args )
    script = (
        f'source "{SCOPE_LIB}"\n'
        f'"{PYTEST_BIN}" "{suite_dir}" -q -p no:cacheprovider -p no:randomly '
        f'--rootdir "{suite_dir}" {args} > "{log}" 2>&1\n'
        f'status=$?\n'
        f'run_scope_summary_line "{log}"\n'
        f'exit $status\n'
    )
    proc = subprocess.run( [ "bash", "-c", script ], cwd=PROJECT_ROOT,
                           env=dict( os.environ, LUPIN_ROOT=PROJECT_ROOT ),
                           capture_output=True, text=True, timeout=300 )
    line = proc.stdout.strip()
    assert line, (
        f"the parser found no summary line for args {pytest_args!r}; every assertion built "
        f"on it would be vacuous.\n--- raw pytest output ---\n"
        f"{open( log ).read()[ -2000: ] if os.path.isfile( log ) else '<no log>'}"
    )
    return line, proc.returncode


def _banner( summary_line, status=0, half="", extra_args=() ):
    """
    Call the REAL report_run_scope with a summary line and return everything it printed.

    Ensures:
        - returns the banner's combined stdout as a str
    """
    args = " ".join( f"'{a}'" for a in extra_args )
    script = (
        f'source "{SCOPE_LIB}"\n'
        f"report_run_scope 'E2E UI tests' '{status}' \"$1\" '{half}' {args}\n"
    )
    proc = subprocess.run( [ "bash", "-c", script, "bash", summary_line ],
                           cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60 )
    assert proc.returncode == 0, f"report_run_scope itself failed:\n{proc.stderr}"
    return proc.stdout


# ---------------------------------------------------------------------------
# It fires on the defect shape — the assignment's "fails if the script prints
# the wrong message for a filtered run"
# ---------------------------------------------------------------------------

def test_a_k_filtered_green_run_is_not_reported_as_all_tests_passed( tmp_path ):
    """
    The exact io/test-suite shape: `-k` selects a subset, everything selected passes, exit
    is 0. The banner must NOT claim the whole suite passed, and must say so in the words a
    skimming reader will hit.
    """
    line, status = _real_summary_line( _suite( tmp_path ), "-k", "alpha" )

    assert status == 0, f"this arm needs a GREEN filtered run to reproduce the defect; pytest exited {status}"
    assert "deselected" in line, (
        f"pytest did not report a deselection for -k alpha, so this case no longer "
        f"reproduces the bug and the assertions below would be vacuous. Line: {line!r}"
    )

    out = _banner( line, status=0, extra_args=( "-k", "alpha" ) )

    assert FULL_CLAIM not in out, (
        f"a filtered run was reported with the full-suite banner — this is the defect.\n"
        f"summary line: {line!r}\n--- banner ---\n{out}"
    )
    assert PARTIAL_CLAIM in out, f"the banner did not say the run was partial.\n{out}"


def test_the_partial_banner_carries_pytests_own_counts( tmp_path ):
    """
    "Not the whole suite" without numbers sends the reader back to the log. The counts must
    be the ones pytest reported, so the banner can be checked against it rather than
    believed.
    """
    line, _ = _real_summary_line( _suite( tmp_path ), "-k", "alpha" )
    out     = _banner( line, status=0, extra_args=( "-k", "alpha" ) )

    assert "1 test(s) selected" in out, f"selected count missing or wrong.\nline: {line!r}\n{out}"
    assert "2 deselected"       in out, f"deselected count missing or wrong.\nline: {line!r}\n{out}"


def test_the_banner_echoes_the_args_that_narrowed_the_run( tmp_path ):
    """
    Half of the 2026-09-24 problem was that the argv was printed NOWHERE, so a reader could
    not tell a filtered run from a full one after the fact. A verdict a reader cannot check
    is a verdict they have to trust.
    """
    line, _ = _real_summary_line( _suite( tmp_path ), "-k", "alpha" )
    out     = _banner( line, status=0, extra_args=( "-k", "alpha" ) )

    assert "Invoked with:" in out, f"the banner did not echo its args.\n{out}"
    assert "-k" in out and "alpha" in out, f"the narrowing args are not in the banner.\n{out}"


def test_a_marker_excluded_run_is_also_partial( tmp_path ):
    """
    `-m` is a different spelling of the same narrowing, and the reason this asks pytest
    rather than looking for `-k`: one signal covers every spelling, including ones nobody
    has added yet.
    """
    line, status = _real_summary_line( _suite( tmp_path ), "-m", "not slow" )

    assert status == 0
    assert "deselected" in line, f"-m did not deselect; case does not reproduce. Line: {line!r}"

    out = _banner( line, status=0, extra_args=( "-m", "not slow" ) )
    assert FULL_CLAIM not in out, f"a marker-narrowed run claimed the full suite.\n{out}"
    assert PARTIAL_CLAIM in out


def test_a_half_run_is_partial_even_though_pytest_deselected_nothing( tmp_path ):
    """
    The partition is not a filter. pytest is handed exactly the files in half-<a|b>.txt,
    collects all of them and deselects nothing, so its summary line is indistinguishable
    from a full suite's. The RUNNER knows, and must say.

    ⚠️ This is the one arm the deselected count cannot answer. Without it, `--half a`
    would print "All E2E UI tests passed!" for half the suite — the same defect wearing the
    partition's clothes.
    """
    line, status = _real_summary_line( _suite( tmp_path ) )

    assert status == 0
    assert "deselected" not in line, (
        f"this arm needs a summary line with NO deselection, or it is not testing the "
        f"property. Line: {line!r}"
    )

    assert FULL_CLAIM in _banner( line, status=0, half="" ), \
        "control: the same line with no half must read as full, or the arm below proves nothing"

    out = _banner( line, status=0, half="a" )
    assert FULL_CLAIM not in out, f"--half a claimed the whole suite.\n{out}"
    assert PARTIAL_CLAIM in out, f"--half a was not reported as partial.\n{out}"
    assert "--half a" in out, f"the banner did not name the half it ran.\n{out}"


def test_a_run_with_zero_tests_is_not_a_pass( tmp_path ):
    """
    `--collect-only` exits 0 having executed nothing, and prints "N tests collected" with no
    outcome words at all. Exit 0 plus a green banner would report that as a passing suite.
    """
    line, status = _real_summary_line( _suite( tmp_path ), "--collect-only" )

    assert status == 0
    assert "passed" not in line, f"this arm needs a summary with no outcomes. Line: {line!r}"

    out = _banner( line, status=0 )
    assert FULL_CLAIM not in out, f"a run that executed nothing claimed a passing suite.\n{out}"
    assert EMPTY_CLAIM in out,    f"a zero-test run was not called out.\n{out}"


def test_no_summary_line_reads_as_unknown_not_as_full():
    """
    The fail-safe. When pytest's output was lost — no capture file, a crash before the
    summary, a `--bg` log truncated by a timeout kill — the scope is UNKNOWN, and unknown
    must not render as a full suite. This is the one case whose input is deliberately not
    real pytest output: its subject is the absence of any.
    """
    out = _banner( "", status=0 )

    assert FULL_CLAIM not in out,  f"an empty summary line was reported as a full suite.\n{out}"
    assert UNKNOWN_CLAIM in out,   f"the unknown-scope fail-safe did not print.\n{out}"


# ---------------------------------------------------------------------------
# It stays quiet — the half that keeps the banner worth reading
# ---------------------------------------------------------------------------

def test_a_full_green_run_still_says_all_tests_passed( tmp_path ):
    """
    The true claim must remain sayable. A guard that made the honest full-suite banner
    unreachable would simply relocate the dishonesty.
    """
    line, status = _real_summary_line( _suite( tmp_path ) )

    assert status == 0
    out = _banner( line, status=0 )

    assert FULL_CLAIM in out,      f"a genuine full green run lost its banner.\n{line!r}\n{out}"
    assert PARTIAL_CLAIM not in out, f"a full run was called partial.\n{out}"
    assert EMPTY_CLAIM not in out


def test_a_filter_that_narrows_nothing_is_a_full_run( tmp_path ):
    """
    🔴 THE DESIGN TEST. `-k test_` matches all three tests, so pytest deselects nothing and
    the run genuinely IS the whole suite. An implementation that sniffed the argv for `-k`
    would call this partial and fail here.

    Measured 2026-09-27 before the lib was written: `-k 'test_'` over this suite prints
    "3 passed", with no deselected clause. The assertion below depends on that, and says so,
    so a pytest that changes its reporting reddens this test instead of silently weakening it.
    """
    line, status = _real_summary_line( _suite( tmp_path ), "-k", "test_" )

    assert status == 0
    assert "deselected" not in line, (
        f"-k 'test_' deselected something, so this arm is no longer the case it describes. "
        f"Line: {line!r}"
    )

    out = _banner( line, status=0, extra_args=( "-k", "test_" ) )
    assert FULL_CLAIM in out, (
        f"a filter that narrowed nothing was reported as partial — that is an argv-sniffer, "
        f"not a reading of pytest's own result.\nline: {line!r}\n{out}"
    )


def test_a_red_run_reports_the_failure_and_claims_nothing( tmp_path ):
    """
    The red path is unchanged by this work, and must stay that way: a failing run claims
    nothing and so cannot overclaim. Pinned because the banner's exit-0 branch is where all
    the new logic lives, and a refactor could easily route red through it.
    """
    d = _suite( tmp_path, name="red" )
    with open( os.path.join( d, "test_red.py" ), "w" ) as f:
        f.write( "def test_forced_red(): assert False, 'deliberate red'\n" )

    line, status = _real_summary_line( d )

    assert status == 1, f"this arm needs a red run; pytest exited {status}"
    out = _banner( line, status=status )

    assert "failed (exit code: 1)" in out, f"the red banner changed shape.\n{out}"
    assert FULL_CLAIM not in out
    assert PARTIAL_CLAIM not in out


# ---------------------------------------------------------------------------
# Wiring — a correct lib that nothing calls is still the old defect
# ---------------------------------------------------------------------------

def test_the_e2e_runner_calls_report_run_scope_and_no_longer_asserts_the_banner():
    """
    A component can be complete, correct, fully covered and never mounted. This reads the
    runner and asserts the old unconditional line is gone and the new call is in.

    The anchor is checked for EXACTLY ONE match, not merely presence: a name that also
    appears in a comment would let this pass over a script that never calls anything.
    """
    source = open( E2E_RUNNER ).read()

    calls = [ ln for ln in source.splitlines()
              if ln.strip().startswith( "report_run_scope " ) ]
    assert len( calls ) == 1, (
        f"expected exactly one report_run_scope CALL (a line starting with it, so a mention "
        f"inside a comment does not count); found {len( calls )}: {calls}"
    )

    assert '"$RUN_PYTEST_SUMMARY_LINE"' in calls[ 0 ], \
        f"the call does not pass pytest's summary line, so its verdict cannot depend on it: {calls[ 0 ]}"
    assert '"$HALF"' in calls[ 0 ], \
        f"the call does not pass --half, so a half run would claim the whole suite: {calls[ 0 ]}"

    bare_banner = [ ln for ln in source.splitlines()
                    if "All E2E UI tests passed" in ln and not ln.strip().startswith( "#" ) ]
    assert bare_banner == [], (
        f"the unconditional full-suite banner is still executable in the runner: {bare_banner}"
    )


def test_the_shared_wrapper_publishes_pytests_summary_line( tmp_path ):
    """
    End-to-end through the real wrapper: run_pytest_with_diagnosis must leave
    RUN_PYTEST_SUMMARY_LINE holding pytest's own summary, or the runner's call above has
    nothing to reason about.

    Entered at the layer the runner enters at — sourcing pytest-with-diagnosis.sh and
    calling the wrapper — rather than calling the parser directly, because the wrapper
    owning the capture file is the part that could break.
    """
    suite  = _suite( tmp_path )
    script = (
        f'source "{DIAGNOSIS_LIB}"\n'
        f'run_pytest_with_diagnosis "{PYTEST_BIN}" "{suite}" -q -p no:cacheprovider '
        f'-p no:randomly --rootdir "{suite}" -k alpha > /dev/null 2>&1\n'
        f'echo "SUMMARY:$RUN_PYTEST_SUMMARY_LINE"\n'
    )
    proc = subprocess.run( [ "bash", "-c", script ], cwd=PROJECT_ROOT,
                           env=dict( os.environ, LUPIN_ROOT=PROJECT_ROOT,
                                     LUPIN_ALLOW_CONTENDED_COVERAGE="1" ),
                           capture_output=True, text=True, timeout=300 )

    published = [ ln[ len( "SUMMARY:" ): ] for ln in proc.stdout.splitlines()
                  if ln.startswith( "SUMMARY:" ) ]
    assert len( published ) == 1, f"no SUMMARY line came back.\n{proc.stdout}\n{proc.stderr}"
    assert "deselected" in published[ 0 ], (
        f"the wrapper did not publish pytest's summary line for a filtered run: "
        f"{published[ 0 ]!r}\n{proc.stdout}\n{proc.stderr}"
    )


def test_the_published_summary_line_is_cleared_between_runs( tmp_path ):
    """
    A stale global is not a cosmetic bug here: the caller decides its green banner from it,
    so one run's scope would be reported as another's. Two calls, the second degraded so it
    cannot produce a line, and the value from the first must not survive into it.

    The second call is degraded by pointing TMPDIR at a non-directory, which is the real
    "no temp file available" path in the wrapper — not a variable this test unset by hand.
    """
    suite    = _suite( tmp_path )
    not_a_dir = tmp_path / "definitely-not-a-directory"
    not_a_dir.write_text( "x" )

    script = (
        f'source "{DIAGNOSIS_LIB}"\n'
        f'run_pytest_with_diagnosis "{PYTEST_BIN}" "{suite}" -q -p no:cacheprovider '
        f'-p no:randomly --rootdir "{suite}" -k alpha > /dev/null 2>&1\n'
        f'echo "FIRST:$RUN_PYTEST_SUMMARY_LINE"\n'
        f'TMPDIR="{not_a_dir}" run_pytest_with_diagnosis "{PYTEST_BIN}" "{suite}" -q '
        f'-p no:cacheprovider -p no:randomly --rootdir "{suite}" > /dev/null 2>&1\n'
        f'echo "SECOND:$RUN_PYTEST_SUMMARY_LINE"\n'
    )
    proc = subprocess.run( [ "bash", "-c", script ], cwd=PROJECT_ROOT,
                           env=dict( os.environ, LUPIN_ROOT=PROJECT_ROOT,
                                     LUPIN_ALLOW_CONTENDED_COVERAGE="1" ),
                           capture_output=True, text=True, timeout=300 )

    first  = [ ln[ len( "FIRST:" ): ]  for ln in proc.stdout.splitlines() if ln.startswith( "FIRST:" ) ]
    second = [ ln[ len( "SECOND:" ): ] for ln in proc.stdout.splitlines() if ln.startswith( "SECOND:" ) ]

    assert len( first ) == 1 and len( second ) == 1, f"probe did not report both calls.\n{proc.stdout}"
    assert "deselected" in first[ 0 ], (
        f"the FIRST call did not publish a line, so the second proves nothing about "
        f"clearing. Got {first[ 0 ]!r}"
    )
    assert first[ 0 ] not in ( second[ 0 ], ) or second[ 0 ] == "", (
        f"the first run's summary line survived into the second call: {second[ 0 ]!r}"
    )
