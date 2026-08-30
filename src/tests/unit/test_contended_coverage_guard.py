"""
Row `e2099400`, decision 4 — the SHELL half: a --cov run refuses a contended box.

WHAT THE PYTHON HALF DOES NOT COVER. src/tests/unit/test_coverage_contention.py pins the
checker's answers. This file pins what the shell does WITH those answers, which is where the
guard can fail in ways the checker cannot see: running the suite anyway, mapping a refusal
onto a code that reads as a pytest result, or being wired into a place nothing calls.

⚠️ THE WIRING IS THE FRAGILE PART, NOT THE CHECK. Row fc74c1d4 measured this exact failure
one rung down: a venv guard written inline in run-unit-tests.sh never reached the other four
runners, and one of them was a named PR-merge gate carrying full gate weight with none of the
protection — for months, until somebody re-found it by accident in a fresh worktree. So the
guard here is sourced ONCE by the wrapper every sanctioned runner already routes through, and
test_a_runner_that_invokes_pytest_outside_the_wrapper_is_declared below walks the runner
directories so a runner added next month that side-steps it fails on the day it lands.

⚠️ THE CHECKER IS STUBBED IN MOST CASES, ON PURPOSE. Asking the real checker "is the box
clear?" gives an answer that depends on whether a peer session happens to be running pytest
right now — a test that reddens for a reason having nothing to do with the code. The stub
makes the SHELL's exit-code mapping deterministic. Two end-to-end cases at the bottom use the
real checker against a process WE spawn, so the seam between them is still proved.

Venue: :7999-eligible. Subprocess bash against tmp_path stubs plus one short-lived sleep; no
server, no state mutation, no network.
"""

import os
import re
import subprocess

import pytest

import cosa.utils.util as cu
import cosa.utils.coverage_contention as cc


PROJECT_ROOT = cu.get_project_root()
GUARD_LIB    = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "guard-contended-coverage.sh" )
WRAPPER_LIB  = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "pytest-with-diagnosis.sh" )

EXIT_CONTENDED = 6
EXIT_UNKNOWN   = 7


def test_the_two_shell_libraries_this_file_depends_on_exist():
    """The instrument before the reading — every case below sources one of these."""
    assert os.path.isfile( GUARD_LIB ),   f"the guard library is not at {GUARD_LIB}"
    assert os.path.isfile( WRAPPER_LIB ), f"the shared wrapper is not at {WRAPPER_LIB}"


def test_both_shell_libraries_are_syntactically_valid():
    for lib in ( GUARD_LIB, WRAPPER_LIB ):
        done = subprocess.run( [ "bash", "-n", lib ], capture_output=True, text=True )
        assert done.returncode == 0, f"{lib} does not parse:\n{done.stderr}"


# ── helpers ──────────────────────────────────────────────────────────────────

def _stub_checker( tmp_path, exit_code ):
    """
    A fake checker interpreter that exits `exit_code` and records that it ran.

    The guard invokes `<python> <module_path>`; this stands in for the python, so it also
    proves the guard passed the module path at all. Returns (interpreter, ran_marker).
    """
    marker = tmp_path / "checker-ran"
    stub   = tmp_path / "fake-python"
    stub.write_text(
        "#!/bin/bash\n"
        f'echo "$@" > "{marker}"\n'
        f"exit {exit_code}\n"
    )
    stub.chmod( 0o755 )
    return str( stub ), marker


def _call_guard( args, interpreter=None, lupin_root=None, env_extra=None ):
    """Source the guard library and call it with `args`. Returns the CompletedProcess."""
    env = dict( os.environ )
    env[ "LUPIN_ROOT" ] = lupin_root or PROJECT_ROOT
    env.pop( "LUPIN_ALLOW_CONTENDED_COVERAGE", None )
    if interpreter: env[ "LUPIN_DIAGNOSIS_PYTHON" ] = interpreter
    else:           env.pop( "LUPIN_DIAGNOSIS_PYTHON", None )
    if env_extra:   env.update( env_extra )
    script = f'source "{GUARD_LIB}"\nguard_contended_coverage "$@"\n'
    return subprocess.run( [ "bash", "-c", script, "bash" ] + list( args ),
                           capture_output=True, text=True, env=env, timeout=60 )


# ── the exit-code mapping ────────────────────────────────────────────────────

def test_a_clear_box_lets_a_coverage_run_proceed( tmp_path ):
    interpreter, marker = _stub_checker( tmp_path, 0 )
    done = _call_guard( [ "pytest", "--cov=cosa" ], interpreter=interpreter )
    assert done.returncode == 0
    assert marker.exists(), "the guard never ran the checker at all"


def test_a_contended_box_refuses_the_run( tmp_path ):
    interpreter, _ = _stub_checker( tmp_path, 1 )
    done = _call_guard( [ "pytest", "--cov=cosa" ], interpreter=interpreter )
    assert done.returncode == EXIT_CONTENDED


def test_an_unreadable_process_table_also_refuses_and_says_which_case_it_was( tmp_path ):
    """
    ⚠️ UNKNOWN IS NOT CLEAR. A guard that answered "proceed" when it could not look would be
    a member of the defect class it was written to close — a control reporting OK under the
    exact condition where it cannot function.
    """
    interpreter, _ = _stub_checker( tmp_path, 2 )
    done = _call_guard( [ "pytest", "--cov=cosa" ], interpreter=interpreter )
    assert done.returncode == EXIT_UNKNOWN, "an unknown answer was softened into a pass"
    assert "could not tell" in done.stderr
    assert "LUPIN_ALLOW_CONTENDED_COVERAGE" in done.stderr, "no deliberate path is offered"


def test_an_unexpected_checker_status_is_treated_as_unknown_not_as_clear( tmp_path ):
    """A checker that grows a fourth exit code must not fail open."""
    interpreter, _ = _stub_checker( tmp_path, 37 )
    assert _call_guard( [ "pytest", "--cov=cosa" ], interpreter=interpreter ).returncode == EXIT_UNKNOWN


def test_the_two_refusal_codes_are_outside_pytests_own_range():
    """
    pytest owns 0-5 (5 = no tests collected, 4 = usage error). A refusal that reused one
    would be read by every log, watchdog and CI parser as a pytest result.
    """
    assert EXIT_CONTENDED > 5 and EXIT_UNKNOWN > 5
    assert EXIT_CONTENDED != EXIT_UNKNOWN


# ── when the guard must stay out of the way ──────────────────────────────────

@pytest.mark.parametrize( "args", [
    [ "pytest", "src/tests/unit/" ],
    [ "pytest", "-q", "--no-header" ],
    [ "pytest", "src/cosa/tests/", "-x" ],
] )
def test_a_run_without_coverage_is_never_checked_or_delayed( tmp_path, args ):
    """
    The guard must cost nothing on the ~99% of runs that ask for no number. If it ran the
    checker on every pytest invocation, it would refuse ordinary test runs whenever a peer
    session had a suite up — and be turned off within the day.
    """
    interpreter, marker = _stub_checker( tmp_path, 1 )   # would REFUSE if consulted
    done = _call_guard( args, interpreter=interpreter )
    assert done.returncode == 0
    assert not marker.exists(), "the checker ran for a command that asked for no coverage"


@pytest.mark.parametrize( "flag", [
    "--cov", "--cov=cosa", "--cov-report", "--cov-report=term-missing", "--cov-config=pyproject.toml",
] )
def test_every_shape_of_coverage_flag_arms_the_guard( tmp_path, flag ):
    interpreter, _ = _stub_checker( tmp_path, 1 )
    assert _call_guard( [ "pytest", flag ], interpreter=interpreter ).returncode == EXIT_CONTENDED


def test_a_missing_checker_module_lets_the_run_proceed_but_says_so_loudly( tmp_path ):
    """
    A guard that can block every coverage run in the tree because one file moved is worse
    than the hole it closes — but it must never do that quietly, or the silence becomes the
    same "measured nothing, reported fine" this row exists to end.
    """
    empty_root = tmp_path / "not-the-repo"
    ( empty_root / "src" / "cosa" / "utils" ).mkdir( parents=True )
    done = _call_guard( [ "pytest", "--cov=cosa" ], lupin_root=str( empty_root ) )
    assert done.returncode == 0
    assert "checker not found" in done.stderr
    assert "NOT checked" in done.stderr


# ── the detectors on both sides of the seam agree ────────────────────────────

_COV_CORPUS = [
    ( [ "pytest", "--cov" ],                       True  ),
    ( [ "pytest", "--cov=cosa" ],                  True  ),
    ( [ "pytest", "--cov-report=html" ],           True  ),
    ( [ "pytest", "--cov-config=pyproject.toml" ], True  ),
    ( [ "pytest", "-q" ],                          False ),
    ( [ "pytest", "--no-cov-on-fail" ],            False ),
    ( [ "pytest", "src/tests/unit/", "-x" ],       False ),
    ( [ "pytest", "--covfefe" ],                   False ),
]


@pytest.mark.parametrize( "args,expected", _COV_CORPUS )
def test_the_guards_flag_detector_and_the_wrappers_agree( args, expected ):
    """
    ⚠️ THE FLAG LIST IS DUPLICATED IN TWO SHELL FILES, so that the guard library stays
    sourceable and testable on its own. Duplication that nothing pins is duplication that
    drifts: this asserts the two detectors give the same answer, so a flag added to one and
    forgotten in the other fails here rather than silently un-arming the guard.
    """
    script = (
        f'source "{GUARD_LIB}"\n'
        f'source "{WRAPPER_LIB}"\n'
        'if _guard_cov_requested "$@"; then g=yes; else g=no; fi\n'
        'if _cov_requested "$@"; then w=yes; else w=no; fi\n'
        'echo "$g $w"\n'
    )
    env = dict( os.environ ); env[ "LUPIN_ROOT" ] = PROJECT_ROOT
    done = subprocess.run( [ "bash", "-c", script, "bash" ] + args,
                           capture_output=True, text=True, env=env, timeout=60 )
    word = "yes" if expected else "no"
    assert done.stdout.split() == [ word, word ], f"detectors disagree on {args}: {done.stdout!r}"


# ── the wiring: the wrapper actually consults the guard ──────────────────────

def test_the_shared_wrapper_refuses_and_never_runs_the_command( tmp_path ):
    """
    THE PROPERTY EVERY RUNNER INHERITS. Proved behaviourally rather than by grepping the
    wrapper for a function name: a refusal that still ran the suite would grep identically.
    """
    interpreter, _ = _stub_checker( tmp_path, 1 )
    ran = tmp_path / "the-suite-ran"
    fake_pytest = tmp_path / "pytest"
    fake_pytest.write_text( f'#!/bin/bash\ntouch "{ran}"\nexit 0\n' )
    fake_pytest.chmod( 0o755 )

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]             = PROJECT_ROOT
    env[ "LUPIN_DIAGNOSIS_PYTHON" ] = interpreter
    env.pop( "LUPIN_ALLOW_CONTENDED_COVERAGE", None )
    done = subprocess.run(
        [ "bash", "-c", f'source "{WRAPPER_LIB}"\nrun_pytest_with_diagnosis "$@"\n',
          "bash", str( fake_pytest ), "--cov=cosa" ],
        capture_output=True, text=True, env=env, timeout=60 )

    assert done.returncode == EXIT_CONTENDED, "the wrapper did not carry the refusal out"
    assert not ran.exists(), "the wrapper REFUSED and ran the suite anyway"


def test_the_shared_wrapper_still_runs_an_ordinary_coverage_run( tmp_path ):
    """The negative half — a wrapper that refused everything would pass the test above."""
    interpreter, _ = _stub_checker( tmp_path, 0 )
    ran = tmp_path / "the-suite-ran"
    fake_pytest = tmp_path / "pytest"
    fake_pytest.write_text( f'#!/bin/bash\ntouch "{ran}"\necho "TOTAL 100%"\nexit 0\n' )
    fake_pytest.chmod( 0o755 )

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]             = PROJECT_ROOT
    env[ "LUPIN_DIAGNOSIS_PYTHON" ] = interpreter
    env.pop( "LUPIN_ALLOW_CONTENDED_COVERAGE", None )
    done = subprocess.run(
        [ "bash", "-c", f'source "{WRAPPER_LIB}"\nrun_pytest_with_diagnosis "$@"\n',
          "bash", str( fake_pytest ), "--cov=cosa" ],
        capture_output=True, text=True, env=env, timeout=60 )

    assert done.returncode == 0
    assert ran.exists(), "a clear box did not get its coverage run"


# ── every runner is either wrapped or declared ───────────────────────────────

RUNNER_DIRS = [ os.path.join( PROJECT_ROOT, "src", "tests" ),
                os.path.join( PROJECT_ROOT, "src", "scripts" ) ]

# Runners that invoke pytest WITHOUT the shared wrapper, each with the reason it is allowed
# to. Anything not on this list must route through run_pytest_with_diagnosis, which is what
# gives it the contention guard (and the collection diagnosis, and the coverage-blindness
# check) for free.
UNWRAPPED_BY_DESIGN = {
    "run-presentation-regression.sh": "builds pytest command STRINGS handed to its own "
                                      "stage runner; never passes a coverage flag",
    "run-lupin-smoke-tests.sh"      : "one inline filtering-tests probe inside a larger "
                                      "shell suite; never passes a coverage flag",
}

# ⚠️ A LOOSE SUBSTRING SEARCH WAS TRIED FIRST AND MISREPORTS. Searching for "$PYTEST"
# anywhere on the line flags `$PYTEST_EXIT_CODE` and `echo "... at $PYTEST"` — three
# innocent runners came back as offenders on the first run of this test. What matters is
# whether pytest is the COMMAND BEING RUN, so the line is reduced to its command word first.
_COMMAND_PREFIXES  = ( "if ", "elif ", "then ", "else ", "&& ", "|| ", "! " )
_PYTEST_INVOCATION = re.compile( r'^(\$PYTEST(?![A-Za-z0-9_])|\$VENV_PYTHON["\']?\s+-m\s+pytest'
                                 r'|(\S*/)?python3?["\']?\s+-m\s+pytest)' )


def _command_word( line ):
    """The line reduced to what it actually RUNS: leading keywords and quotes removed."""
    text = line.strip()
    changed = True
    while changed:
        changed = False
        for prefix in _COMMAND_PREFIXES:
            if text.startswith( prefix ):
                text    = text[ len( prefix ): ].lstrip()
                changed = True
    return text.lstrip( "\"'" )


def _runner_scripts():
    for directory in RUNNER_DIRS:
        for name in sorted( os.listdir( directory ) ):
            if name.endswith( ".sh" ) and name.startswith( ( "run-", "smoke" ) ):
                yield name, os.path.join( directory, name )


def test_a_runner_that_invokes_pytest_outside_the_wrapper_is_declared():
    """
    ⚠️ THIS ASSERTS A PROPERTY OF EVERY RUNNER, NOT A LIST OF KNOWN-GOOD ONES. Row fc74c1d4's
    whole lesson is that a fix applied to the runners that existed on the day never reaches
    the ones written afterwards. A runner added next month that calls pytest directly fails
    here on the day it lands, and its author has to either use the wrapper or say in this
    dict why it does not need to.
    """
    offenders = {}
    for name, path in _runner_scripts():
        if name in UNWRAPPED_BY_DESIGN: continue
        bare = []
        for number, line in enumerate( open( path ), start=1 ):
            stripped = line.strip()
            if stripped.startswith( "#" ) or not stripped: continue
            if "run_pytest_with_diagnosis" in stripped:    continue
            if _PYTEST_INVOCATION.match( _command_word( stripped ) ):
                bare.append( f"{number}: {stripped[ :90 ]}" )
        if bare: offenders[ name ] = bare
    assert not offenders, (
        "these runners invoke pytest without the shared wrapper, so they get no contention "
        f"guard: {offenders}" )


def test_the_declared_exemptions_still_exist_and_still_ask_for_no_coverage():
    """
    An exemption is a claim about a file. If the file changed to pass a coverage flag, the
    claim is stale and the exemption is now a hole — this is what stops the dict above from
    turning into a place to silence the test.
    """
    for name, reason in UNWRAPPED_BY_DESIGN.items():
        matches = [ path for _n, path in _runner_scripts() if _n == name ]
        assert matches, f"{name} is exempted but no longer exists — drop the entry"
        assert reason.strip(), f"{name} is exempted without a reason"
        body = open( matches[ 0 ] ).read()
        code = "\n".join( l for l in body.splitlines() if not l.strip().startswith( "#" ) )
        assert "--cov" not in code, f"{name} now passes a coverage flag but is exempt from the guard"


# ── end to end, against the real checker ─────────────────────────────────────

def test_end_to_end_a_real_foreign_pytest_refuses_a_real_coverage_run():
    """
    No stub anywhere: the real guard, the real checker, and a process we spawn that genuinely
    looks like somebody else's suite. This is the seam the stubbed cases cannot prove.
    """
    foreign = subprocess.Popen( [ "bash", "-c", 'exec -a "/usr/bin/pytest lupin-suite" sleep 20' ] )
    try:
        done = _call_guard( [ "pytest", "--cov=cosa" ] )
        assert done.returncode == EXIT_CONTENDED, f"the real checker missed it: {done.stderr}"
        assert "REFUSING" in done.stderr
        assert "pgrep -af pytest" in done.stderr, "the refusal does not say how to check"
    finally:
        foreign.terminate(); foreign.wait( timeout=10 )


def test_end_to_end_the_escape_hatch_lets_a_deliberate_contended_run_through():
    """The operator's override — same conditions as above, one env var different."""
    foreign = subprocess.Popen( [ "bash", "-c", 'exec -a "/usr/bin/pytest lupin-suite" sleep 20' ] )
    try:
        done = _call_guard( [ "pytest", "--cov=cosa" ],
                            env_extra={ "LUPIN_ALLOW_CONTENDED_COVERAGE": "1" } )
        assert done.returncode == 0, f"the escape hatch did not open: {done.stderr}"
        assert "check skipped" in done.stderr, "an override that says nothing is a silent hole"
    finally:
        foreign.terminate(); foreign.wait( timeout=10 )


# ── a test that spawns a --cov child must not be flaky-by-construction ───────

_COV_ARG   = re.compile( r'["\']--cov[=\s"\']' )
_HATCH_SET = re.compile( r'LUPIN_ALLOW_CONTENDED_COVERAGE["\']?\s*\]?\s*[:=]' )

# Files that hand --cov to a subprocess for a reason OTHER than measuring something.
_NOT_A_COVERAGE_CHILD = {
    "test_contended_coverage_guard.py": "its --cov strings are arguments to the refusal check itself",
    "test_pytest_args_policy.py"      : "asserts on argument STRINGS; spawns no coverage child",
}

# ⚠️ ONLY CHILDREN THAT GO THROUGH THE WRAPPER CAN BE REFUSED. The guard lives in
# run_pytest_with_diagnosis; a test that invokes `sys.executable -m pytest` directly never
# meets it and is not flaky-by-construction. The first version of this check ignored that and
# accused test_coverage_file_guard.py, which spawns its children directly — a false positive,
# and a guard that cries wolf is a guard that gets an exemption entry instead of a fix.
_ROUTES_THROUGH_WRAPPER = re.compile( r'run_pytest_with_diagnosis|pytest-with-diagnosis' )


def test_a_test_that_spawns_a_coverage_child_engages_the_escape_hatch():
    """
    ⚠️ THE GUARD'S OWN FAILURE MODE, AND IT NEARLY SHIPPED. A test whose child asks for --cov
    is refused whenever ANY other suite is on the box — and on a shared box that is most of
    the time. Measured on the day the guard landed: five tests in
    test_runner_coverage_blindness.py went red together because a peer session was four
    minutes into `pytest src/cosa/tests/`. Nothing was wrong with those tests.

    Such children produce no number anyone cites — they exercise a wrapper's warning, or probe
    collection — so the right move is the escape hatch, and the wrong move is what a hurried
    reader would do instead: conclude the guard is noisy and delete it. This walks src/tests so
    the next such child is caught when it is written.
    """
    offenders = []
    for directory, _dirs, names in os.walk( os.path.join( PROJECT_ROOT, "src", "tests" ) ):
        if "__pycache__" in directory: continue
        for name in sorted( names ):
            if not ( name.startswith( "test_" ) and name.endswith( ".py" ) ): continue
            if name in _NOT_A_COVERAGE_CHILD:                                 continue
            path = os.path.join( directory, name )
            body = open( path ).read()
            if not _COV_ARG.search( body ):                continue
            if "subprocess" not in body:                   continue
            if not _ROUTES_THROUGH_WRAPPER.search( body ): continue
            if _HATCH_SET.search( body ):                  continue
            offenders.append( os.path.relpath( path, PROJECT_ROOT ) )
    assert not offenders, (
        "these tests spawn a --cov child without engaging LUPIN_ALLOW_CONTENDED_COVERAGE, so "
        f"they go red whenever a peer session runs any suite: {offenders}" )


# ── comm_could_be_pytest: a seat's spawn brief is not a running suite ─────────────
#
# Row 9078a035, measured 2026-08-30. The guard refused a --cov run on an otherwise-idle
# box, naming two `comm=claude` processes whose argv merely QUOTED "-m pytest" as part of
# their spawn briefs. Both were long-lived, so the gate would never have reopened.

@pytest.mark.parametrize( "comm,could_be", [
    ( "pytest",     True  ),
    ( "python",     True  ),
    ( "python3",    True  ),
    ( "python3.13", True  ),
    ( "",           True  ),   # unreadable comm must never hide a real suite
    ( "claude",     False ),   # the measured false positive
    ( "bash",       False ),
    ( "node",       False ),
] )
def test_comm_could_be_pytest_asks_what_the_process_is( comm, could_be ):
    assert cc.comm_could_be_pytest( comm ) is could_be


def test_a_seat_whose_brief_quotes_a_pytest_command_is_not_a_running_suite():
    """
    The exact measured shape: argv that would pass looks_like_pytest, on a process whose
    comm says it is a Claude seat. The cmdline check alone still says True — that is the
    point; comm is what discriminates.
    """
    # NOTE: the measured briefs named a per-repo virtualenv interpreter by path; these
    # fixtures use a bare `python3` and an /opt path instead, because
    # test_venv_dependent_tests_are_declared.py reddens on a unit test naming a path into
    # a repo-local virtualenv (only 5 of 29 trees have one). Nothing is lost — the
    # discriminating property is the `-m pytest` token, not which interpreter precedes it.
    brief = ( "/home/rruiz/.local/bin/claude --model claude-opus-5 You own row c89cec9b. "
              "Run: python3 -B -m pytest src/tests/unit/foo.py -q" )
    assert cc.looks_like_pytest( brief ) is True          # argv cannot tell
    assert cc.comm_could_be_pytest( "claude" ) is False    # comm can


def test_a_real_pytest_is_still_found_when_comm_is_an_interpreter():
    """The positive control — the fix must not blind the guard to actual runs."""
    real = "/opt/venv/bin/python -m pytest src/tests/unit/ -q --cov"
    assert cc.looks_like_pytest( real ) is True
    assert cc.comm_could_be_pytest( "python" ) is True
    found = cc.find_foreign_pytest( process_table=lambda: [ ( 999, real ) ], ancestors=[ 1 ] )
    assert [ pid for pid, _ in found ] == [ 999 ]
