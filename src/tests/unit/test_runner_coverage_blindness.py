"""
Row f8e5215b — a run that produced NO coverage number must say so, not stay quiet.

THE SHAPE. pytest-cov's `--no-cov-on-fail` suppresses the ENTIRE coverage report when any
test in the run fails. On a tier that carries tolerated red — a worktree tier always does,
row 1cf6c918 — the instrument goes blind exactly when the number is wanted, and it goes
blind SILENTLY: no warning, no "coverage suppressed" line, just an absent table. Nothing in
the output distinguishes "coverage was not measured" from "I forgot to pass --cov". That is
how a ten-minute tier gets run specifically to obtain a number the flag then deletes
(measured 2026-08-22 while gating a0322a77).

WHAT IS ASSERTED HERE. The wrapper in src/scripts/lib/pytest-with-diagnosis.sh — the shared
path every sanctioned runner script routes through — prints a loud block when coverage was
requested, the run was red, and no coverage table reached the reader. And, just as
important, that it stays QUIET on the three shapes where there is nothing to complain
about. A detector that fires on everything is the same useless instrument in the other
direction.

⚠️ THE NEGATIVE CASES ARE THE POINT OF THIS FILE, not padding. The positive case would pass
against a wrapper that printed the block unconditionally — which would train everyone to
ignore it inside a week. Four of the seven tests below exist to make that impossible.

PROVED BY CONSTRUCTION, in the shape of test_runner_collection_diagnosis.py next door: every
test sources the REAL helper and runs a REAL pytest against real test files written to
tmp_path. Nothing is stubbed, so nothing here can pass because of a string this file wrote.

Venue: :7999-eligible. Pure subprocess pytest over tmp_path; no server, no state mutation,
no network. Each case runs two trivial tests, so the whole file is seconds.
"""

import os
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
HELPER       = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "pytest-with-diagnosis.sh" )
PYTEST_BIN   = os.path.join( PROJECT_ROOT, ".venv", "bin", "pytest" )

BLOCK_HEADLINE = "NO COVERAGE NUMBER WAS PRODUCED BY THIS RUN"


def test_the_helper_and_interpreter_this_file_depends_on_exist():
    """
    The instrument before the reading. Every case below shells out to these two paths; if
    either moved, the subprocesses would fail for a reason that has nothing to do with the
    property under test, and a reader would be left diagnosing this file instead of the bug.
    """
    assert os.path.isfile( HELPER ),   f"the shared wrapper is not at {HELPER}"
    assert os.access( PYTEST_BIN, os.X_OK ), f"no runnable venv pytest at {PYTEST_BIN}"


def _suite( tmp_path, red ):
    """
    Write a two-test suite into tmp_path and return its directory.

    Requires:
        - red is a bool: True writes one deliberately failing test

    Ensures:
        - the suite imports a small module of OURS and calls into it, so the `--cov` scope
          used below has something real to measure — a scope the run never touches produces
          no table for a DIFFERENT reason, and that shape is exercised deliberately in its
          own test below
        - returns the directory path as a str

    ⚠️ THE MEASURED MODULE USED TO BE THE STDLIB `json`, AND THAT WAS THE BUG (row e2099400
    §3a). `--cov=json` measured CPython's own json package, and because the children
    inherited this process's COVERAGE_FILE, five stdlib modules — ~610 statements — landed
    in the repo's coverage denominator at ~0%. The scope is now one of our own modules, and
    the children get their own data file in _run below. Either change alone would have
    stopped it; both are here because this file's whole subject is instruments that go
    wrong quietly.
    """
    body = (
        "from cosa.utils import coverage_contention\n"
        "def test_touches_the_measured_module():\n"
        "    assert coverage_contention.looks_like_pytest( '/opt/venv/bin/pytest -q' ) is True\n"
    )
    if red:
        body += "def test_forced_red():\n    assert False, 'deliberate red'\n"
    else:
        body += "def test_also_passes():\n    assert True\n"

    d = tmp_path / "suite"
    d.mkdir()
    ( d / "test_probe.py" ).write_text( body )
    return str( d )


def _run( suite_dir, *pytest_args ):
    """
    Source the REAL wrapper and run the REAL pytest through it.

    Ensures:
        - returns the CompletedProcess with stdout and stderr captured separately, because
          the block under test is written to stderr on purpose (it must not be mistaken for
          part of pytest's own report)
        - `-p no:cacheprovider` keeps the run from writing a cache into the repo
        - runs from PROJECT_ROOT so the wrapper's LUPIN_ROOT-relative lookups resolve
    """
    args    = " ".join( f"'{a}'" for a in pytest_args )
    script  = (
        f'source "{HELPER}"\n'
        f'run_pytest_with_diagnosis "{PYTEST_BIN}" "{suite_dir}" '
        f'-q -p no:cacheprovider --rootdir "{suite_dir}" -p no:randomly {args}\n'
        f'exit $?\n'
    )
    # ⚠️ THE CHILD GETS ITS OWN COVERAGE_FILE, AND THAT IS NOT HOUSEKEEPING (row e2099400 §3a).
    # These children run `--cov` on purpose — the scope needs something real to measure.
    # Inheriting the parent's COVERAGE_FILE wrote their json data into the TIER's data file, so
    # five CPython stdlib modules appeared in the repo's coverage report at ~0%: json/encoder.py
    # 235 statements, decoder.py 206, scanner.py 56, tool.py 41, __init__.py 61. That is ~610
    # statements of code we do not own, sitting in the denominator of a 100% mandate. Measured
    # and reproduced 2026-08-26 by running this file under --cov with an isolated data file and
    # reading the result back: 5 measured files, 5 of them outside src/, all five of them these.
    env = dict( os.environ,
                LUPIN_ROOT    = PROJECT_ROOT,
                COVERAGE_FILE = os.path.join( suite_dir, ".coverage-child" ),
                # ⚠️ AND THE CONTENDED-COVERAGE GUARD IS TURNED OFF FOR THESE CHILDREN, ON
                # PURPOSE (row e2099400 decision 4). That guard refuses a --cov run while any
                # other suite is on the box, because a contended coverage NUMBER is silently
                # wrong. These children produce no number anyone will ever cite — they exist
                # to make the wrapper print (or not print) a warning. Without this, the whole
                # file goes red whenever a peer session happens to be running tests, which is
                # most of the time on this box: caught here on the day the guard landed, with
                # a peer four minutes into `pytest src/cosa/tests/`. A guard that reddens
                # honest tests for reasons unrelated to them is a guard somebody deletes.
                LUPIN_ALLOW_CONTENDED_COVERAGE = "1" )
    return subprocess.run(
        [ "bash", "-c", script ], cwd=PROJECT_ROOT, env=env,
        capture_output=True, text=True, timeout=300
    )


# ---------------------------------------------------------------------------
# It fires — and for the right reason
# ---------------------------------------------------------------------------

def test_red_run_with_no_cov_on_fail_is_reported_as_blind( tmp_path ):
    """
    The exact f8e5215b shape: coverage asked for, run red, `--no-cov-on-fail` swallowing the
    report. The run must still exit 1 (the wrapper never touches the status) AND the reader
    must be told no number was produced.
    """
    proc = _run( _suite( tmp_path, red=True ), "--cov=cosa.utils.coverage_contention", "--cov-fail-under=0", "--no-cov-on-fail" )

    assert proc.returncode == 1, f"the wrapper must re-raise pytest's status verbatim; got {proc.returncode}"
    assert "coverage: platform" not in proc.stdout, \
        "pytest-cov printed a table after all — this case no longer reproduces the bug, so the assertion below would be vacuous"
    assert BLOCK_HEADLINE in proc.stderr, \
        f"no blindness block on the exact defect shape.\n--- stderr ---\n{proc.stderr}"


def test_the_block_names_the_flag_when_the_flag_is_what_caused_it( tmp_path ):
    """
    A warning that says only "something went wrong" costs the reader the diagnosis. When
    `--no-cov-on-fail` is in the command it is the known cause, so the block must name it
    and give the remedy — otherwise this check just relocates the confusion.
    """
    proc = _run( _suite( tmp_path, red=True ), "--cov=cosa.utils.coverage_contention", "--cov-fail-under=0", "--no-cov-on-fail" )

    assert "--no-cov-on-fail was passed" in proc.stderr, \
        f"the block did not name the flag that caused it.\n--- stderr ---\n{proc.stderr}"
    assert "WITHOUT --no-cov-on-fail" in proc.stderr, "the block must state the remedy, not just the cause"


def test_a_scope_the_run_never_imports_is_also_reported_as_blind( tmp_path ):
    """
    The OTHER way to end a red run with no number, and the reason this is a detector rather
    than a ban on one flag: `--cov` pointed at code the run never imports makes pytest-cov
    warn "No data to report" and print no table. Same absent number, different cause — and
    the block must distinguish them rather than blaming a flag that was never passed.
    """
    proc = _run( _suite( tmp_path, red=True ), "--cov=cosa.utils.pytest_collection_diagnosis", "--cov-fail-under=0" )

    assert BLOCK_HEADLINE in proc.stderr, \
        f"an unimported --cov scope produced no number and no warning.\n--- stderr ---\n{proc.stderr}"
    assert "--no-cov-on-fail was NOT passed" in proc.stderr, \
        "the block blamed a flag that was not in the command"


# ---------------------------------------------------------------------------
# It stays quiet — the half that keeps it worth reading
# ---------------------------------------------------------------------------

def test_quiet_when_the_red_run_DID_produce_a_table( tmp_path ):
    """
    Red, coverage requested, table printed. Nothing is wrong: the reader got their number
    alongside a failure. A block here would be noise on the most ordinary red run there is.
    """
    proc = _run( _suite( tmp_path, red=True ), "--cov=cosa.utils.coverage_contention", "--cov-fail-under=0" )

    assert "coverage: platform" in proc.stdout, \
        f"the table this case depends on was not printed — the assertion below would pass vacuously.\n{proc.stdout[-2000:]}"
    assert BLOCK_HEADLINE not in proc.stderr, \
        f"fired on a red run that DID report coverage.\n--- stderr ---\n{proc.stderr}"


def test_quiet_on_a_green_run( tmp_path ):
    """
    A green run always reports, so there is nothing for this check to add. Stated as its own
    case because "we only look at red" is a real scoping decision, not an implementation
    detail — if someone later makes the check unconditional, this is what objects.
    """
    proc = _run( _suite( tmp_path, red=False ), "--cov=cosa.utils.coverage_contention", "--cov-fail-under=0" )

    assert proc.returncode == 0, f"this case needs a genuinely green run; got {proc.returncode}\n{proc.stdout[-2000:]}"
    assert BLOCK_HEADLINE not in proc.stderr, f"fired on a green run.\n--- stderr ---\n{proc.stderr}"


def test_quiet_when_coverage_was_never_requested( tmp_path ):
    """
    The commonest run in the repo: a red tier with no --cov anywhere. Someone who did not
    ask for a number must never be told they failed to get one — that is how a warning
    becomes wallpaper.
    """
    proc = _run( _suite( tmp_path, red=True ), "--no-cov" )

    assert proc.returncode == 1, "this case needs a red run to be meaningful"
    assert BLOCK_HEADLINE not in proc.stderr, \
        f"fired on a run that never asked for coverage.\n--- stderr ---\n{proc.stderr}"
