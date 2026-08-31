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


# ---------------------------------------------------------------------------
# It stays quiet when the table was suppressed ON PURPOSE
#
# This is the shape the repo's own tiers use. `coverage_opt_in_flags()` emits
# `--cov --cov-report= --cov-fail-under=0 --cov-append` for every tier (row e2099400),
# because the tiers APPEND to one data file and run-coverage-gate.sh renders the number
# once, afterwards. Before this section existed the block fired on that sanctioned
# invocation the moment a tier had any red, and told the reader the run "measured
# nothing" while the whole frame had in fact been measured. Two seats hit it and read
# it as a defect in their own run, which is the cost of a warning that cannot tell
# "measured nothing" from "was told not to print".
# ---------------------------------------------------------------------------

TIER_FLAGS = ( "--cov", "--cov-report=", "--cov-fail-under=0", "--cov-append" )


def _child_measured_files( suite_dir ):
    """
    Read the child's OWN coverage data back and return how many files it measured.

    Requires:
        - suite_dir is the directory _run used, so `.coverage-child` sits inside it

    Ensures:
        - returns an int, 0 when the file is absent or holds no measurement
        - reads the CHILD's data file, never the parent's — see _run's note on why
          these children are given their own COVERAGE_FILE
    """
    import coverage

    path = os.path.join( suite_dir, ".coverage-child" )
    if not os.path.exists( path ):
        return 0
    data = coverage.CoverageData( path )
    data.read()
    return len( list( data.measured_files() ) )


def test_a_deliberately_suppressed_table_is_not_reported_as_blindness( tmp_path ):
    """
    The repo's own tier flags against a red run. No table is printed, and that is correct
    — `--cov-report=` asked for none. The block must not fire.

    ⚠️ THE MEASUREMENT PRECONDITION IS ASSERTED FIRST, AND IT IS THE WHOLE TEST. Silence
    alone would pass vacuously if the run had genuinely measured nothing — that is exactly
    the case the block SHOULD fire on. What makes this a false positive rather than a
    judgement call is that the data file is non-empty: the run measured, it simply did not
    render.
    """
    suite = _suite( tmp_path, red=True )
    proc  = _run( suite, *TIER_FLAGS )

    assert proc.returncode == 1, f"this case needs a red run to be meaningful; got {proc.returncode}"
    assert "coverage: platform" not in proc.stdout, \
        "this case depends on NO table being printed; one appeared, so it is testing nothing"

    measured = _child_measured_files( suite )
    assert measured > 0, (
        "the run measured nothing, so silence here would be WRONG rather than a false "
        f"positive — this test would pass for the opposite reason. measured={measured}"
    )

    assert BLOCK_HEADLINE not in proc.stderr, (
        f"fired on the repo's own tier flags, which suppress the table on purpose and "
        f"measured {measured} files.\n--- stderr ---\n{proc.stderr}"
    )


def test_the_suppressed_run_still_says_not_to_cite_a_number_from_it( tmp_path ):
    """
    Quiet is not the same as saying nothing. You still cannot cite coverage from a run that
    rendered none, so the note has to survive — it is the alarm and the false "measured
    nothing" claim that go, not the guidance. Pinned separately from the silence above
    because dropping the note entirely would still pass that test.
    """
    proc = _run( _suite( tmp_path, red=True ), *TIER_FLAGS )

    assert "run-coverage-gate.sh" in proc.stderr, (
        "the note must name the step that actually renders the number, or the reader is "
        f"left knowing only that this run did not.\n--- stderr ---\n{proc.stderr}"
    )


def test_suppression_alone_does_not_excuse_the_other_blind_shapes( tmp_path ):
    """
    The narrowing is on `--cov-report=` ONLY. `--no-cov-on-fail` is a different cause with a
    different remedy, and a run carrying BOTH is still genuinely blind — pytest-cov drops the
    data, so there is nothing for the gate to render later.

    This is the case that keeps the fix from becoming a blanket mute.

    ⚠️ THE OBVIOUS DISCRIMINATOR DOES NOT WORK, AND THIS TEST IS WHERE THAT WAS MEASURED.
    A first cut asserted `_child_measured_files( suite ) == 0` here, on the assumption that
    `--no-cov-on-fail` discards the data as well as the report. It does not. Measured directly
    afterwards, with the figure rather than the word: this flag combination against a red suite
    wrote **249,856 bytes / 704 measured files**. So a data-file check cannot separate this case
    from an ordinary suppressed-table run — the file is non-empty either way, and only the FLAG
    separates them. That is why the wrapper branches on the flag and why the precedence between
    the two flags had to be made explicit.

    ⚠️ The failing assertion above showed only that the count was NOT ZERO; it never printed one.
    Reporting that as "measured" was an inference dressed as a reading, and review caught it.
    """
    suite = _suite( tmp_path, red=True )
    proc  = _run( suite, *TIER_FLAGS, "--no-cov-on-fail" )

    assert proc.returncode == 1, "this case needs a red run to be meaningful"
    assert BLOCK_HEADLINE in proc.stderr, (
        f"went quiet on a genuinely blind run just because --cov-report= was present.\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    assert "--no-cov-on-fail was passed" in proc.stderr, (
        "the block fired but did not name the flag as the cause — the named-cause branch is "
        f"the most actionable thing in here and it must survive the narrowing.\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------
# Chloé 🗼's review of the first cut (row da5868df) — three findings, three pins.
#
# F1: the note claimed "Measurement still happened" WITHOUT LOOKING, which is the
#     exact charge this file levels at the old block, pointing the other way. A
#     false alarm gets investigated; a false reassurance does not.
# F2: the same false join survived on the branch that was deliberately KEPT.
# F3: the exact-match judgement was a judgement no test defended — her mutation
#     widening it to the prefix form SURVIVED all 79 tests.
# ---------------------------------------------------------------------------

def test_a_suppressed_table_over_an_empty_data_file_is_not_called_measurement( tmp_path ):
    """
    F1. `--cov` scoped to code the run never imports measures NOTHING, and the suppressed-table
    note must not reassure over it.

    ⚠️ THE POINT IS THE DIRECTION OF THE ERROR. The old block's failure was loud and false; this
    one would be quiet and false, and quiet is worse because nobody goes and checks it. The data
    file DOES discriminate here — 0 against 704 — which is exactly why the check belongs on this
    branch even though it is unavailable one branch over (see the --no-cov-on-fail test below).
    """
    suite = _suite( tmp_path, red=True )
    proc  = _run( suite, "--cov=cosa.agents.deep_research.deep_research_job",
                  "--cov-report=", "--cov-fail-under=0" )

    assert _child_measured_files( suite ) == 0, (
        "this case needs a genuinely dead scope; something was measured, so it is testing "
        "the opposite of what it claims"
    )
    assert "Measurement did happen" not in proc.stderr, (
        f"claimed measurement over an EMPTY data file — the false-reassurance shape.\n{proc.stderr}"
    )
    assert "0 files measured" in proc.stderr, (
        f"went quiet instead of naming the empty data file.\n--- stderr ---\n{proc.stderr}"
    )


def test_the_no_cov_on_fail_block_says_the_report_was_dropped_not_that_nothing_was_measured( tmp_path ):
    """
    F2. `--no-cov-on-fail` drops the REPORT and still WRITES the data. The first cut measured
    that, wrote it into a docstring, and left the block's prose saying the opposite.

    Pinned separately from the block firing at all, because the block firing is correct here —
    what was wrong was what it SAID once it fired.
    """
    suite = _suite( tmp_path, red=True )
    proc  = _run( suite, *TIER_FLAGS, "--no-cov-on-fail" )

    measured = _child_measured_files( suite )
    assert measured > 0, (
        f"this case assumes --no-cov-on-fail still writes data; it wrote {measured}, so the "
        "assertion below would be testing something else"
    )
    assert "BUT THE DATA SURVIVED" in proc.stderr, (
        f"the block still implies nothing was measured while {measured} files sit in "
        f"COVERAGE_FILE.\n--- stderr ---\n{proc.stderr}"
    )
    assert "do NOT re-run" in proc.stderr, (
        "the remedy still says re-run, which under the tier architecture buys a number that is "
        f"already on disk at the price of a full tier.\n--- stderr ---\n{proc.stderr}"
    )


def test_a_real_terminal_report_is_not_mistaken_for_a_suppressed_one( tmp_path ):
    """
    F3, and this is Chloé's mutation arm rather than mine. My pass widened the predicate to
    `--cov-report` (no `=`), which the tests killed. Hers widened it to the PREFIX form a
    well-meaning editor would actually write — `case "$a" in --cov-report=*)` — and it
    SURVIVED all 79 tests.

    The harm the survival hid: `--cov-report=term` REQUESTS a terminal report, and under the
    prefix form it would be told no table was asked for. Exact match is the right judgement;
    it simply had no test defending it, which is a different problem from being wrong.

    ⚠️ Two harnesses aimed at one file found different arms. That — not a matching sha — is
    the argument for a second harness.

    🔴 IT TOOK TWO WRONG PINS TO REACH THIS ONE, AND THE REASON IS THE USEFUL PART.
    Measured, with a suite that DOES import the measured module:

        --cov-report=''      -> 0 table markers   (the guard proceeds)
        --cov-report=term    -> 2
        --cov-report=html    -> 1
        --cov-report=xml     -> 1

    Every NON-EMPTY report form prints coverage's `coverage: platform` header whenever there
    is data, so `_cov_table_present` returns early and the predicate is never consulted. My
    first pin used `term` and my second used `html`; both were unreachable, and her mutation
    survived tests written specifically to catch it.

    ⇒ On a run WITH data the prefix mutation is an EQUIVALENT mutant — unreachable, not
    merely untested. The one reachable case needs BOTH a non-empty report form AND a scope
    that measures nothing, because then there is no table to return early on. That is the
    case below, and it is where exact-versus-prefix finally changes the output.

    ⇒ A test aimed at the right BEHAVIOUR still misses if its input never reaches the code.
    """
    proc = _run( _suite( tmp_path, red=True ),
                 "--cov=cosa.agents.deep_research.deep_research_job",
                 f"--cov-report=html:{tmp_path}/htmlcov", "--cov-fail-under=0" )

    assert "coverage: platform" not in proc.stdout, (
        "this case needs a report that prints NO terminal table; one appeared, so the guard "
        "returns early and the predicate under test is never reached"
    )
    assert "asked for none" not in proc.stderr, (
        "treated an html report as a request for NO report. Exact match on '--cov-report=' is "
        f"what keeps these apart.\n--- stderr ---\n{proc.stderr}"
    )
