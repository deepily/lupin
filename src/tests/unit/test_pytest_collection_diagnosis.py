"""
Row bc83f2df — a pytest collection error must report as its own state, with a diagnosis.

PROVED BY CONSTRUCTION, not by fixtures. Every test here builds a real cause shape on
disk, runs a real pytest subprocess against it, and reads the real exit code and output.
Synthetic strings would prove only that the regexes match the strings I wrote.

The row's bar: "show the current tooling goes quiet on each, then show it reports after
your fix. A test that passes both before and after is not evidence." So each shape has
a `test_current_tooling_*` counterpart asserting what the EXISTING classifier does — those
assertions are the "before", and they will start failing the day someone fixes the
classifier, which is the correct time for them to fail.

THE TWO SHAPES, both taken from real incidents on 2026-08-17:
  A. an orphaned import in a TEST module — the subject was retired, the test left behind
  B. a required parameter added to a function ahead of its callers, in a CONFTEST
"""

import subprocess
import sys
import textwrap

import pytest

from cosa.agents.test_suite.job import TestSuiteJob
from cosa.utils.pytest_collection_diagnosis import (
    COLLECTION_ERROR,
    diagnose,
    render,
)


# ── Builders: each writes a real cause shape and runs a real pytest ──────────
def _run_pytest( path ):
    """Run pytest against `path` in its own process; return (exit_code, combined output)."""
    proc = subprocess.run(
        [ sys.executable, "-m", "pytest", str( path ), "-p", "no:cacheprovider" ],
        capture_output=True, text=True, timeout=120, cwd=str( path ),
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture
def shape_a( tmp_path ):
    """
    Orphaned import in a TEST module.

    The bystander file matters: it holds tests that are perfectly fine and never run.
    That is the blast radius, and it is what the current report fails to mention.
    """
    d = tmp_path / "shape_a"
    d.mkdir()
    ( d / "test_orphan.py" ).write_text( textwrap.dedent( """
        from cosa.memory.credential_watcher_retired import CredentialWatcher
        def test_it(): assert CredentialWatcher
    """ ) )
    ( d / "test_innocent_bystander.py" ).write_text( textwrap.dedent( """
        def test_a(): assert True
        def test_b(): assert True
    """ ) )
    return d


@pytest.fixture
def shape_b( tmp_path ):
    """A required parameter added ahead of its callers, failing inside a CONFTEST."""
    d = tmp_path / "shape_b"
    d.mkdir()
    ( d / "provenance.py" ).write_text( textwrap.dedent( """
        def make_provenance( source, run_id ):
            return { "source": source, "run_id": run_id }
    """ ) )
    ( d / "conftest.py" ).write_text( textwrap.dedent( """
        from provenance import make_provenance
        DEFAULT_PROV = make_provenance( "test" )
    """ ) )
    ( d / "test_paired_eval.py" ).write_text( textwrap.dedent( """
        def test_x(): assert True
        def test_y(): assert True
    """ ) )
    return d


# ── 1. THE "BEFORE" — what the existing classifier does with each shape ─────
def test_current_tooling_calls_shape_a_a_plain_failure( shape_a ):
    """
    Shape A writes a junit with errors=1, so the existing classifier returns "FAILED" —
    a string byte-identical to a genuine red. Nothing ran, and the report says FAILED.
    """
    code, _ = _run_pytest( shape_a )
    assert code == 2, "shape A must be a pytest collection interrupt"
    # The counts the junit carries for this shape, measured 2026-08-17.
    assert TestSuiteJob._classify_outcome( passed=0, failed=0, errors=1, skipped=0 ) == "FAILED"
    # ...and that is indistinguishable from a real failing test:
    assert TestSuiteJob._classify_outcome( passed=5, failed=1, errors=0, skipped=0 ) == "FAILED"


def test_current_tooling_goes_silent_on_shape_b( shape_b ):
    """
    Shape B writes NO junit and fires NO hooks, so every count is zero and the classifier
    returns "NOT EXECUTED" — the right state reached by accident, carrying no diagnosis.
    """
    code, out = _run_pytest( shape_b )
    assert code == 4, "a conftest import failure is a pytest usage error"
    assert "ImportError while loading conftest" in out
    assert TestSuiteJob._classify_outcome( passed=0, failed=0, errors=0, skipped=0 ) == "NOT EXECUTED"


def test_shape_a_hides_its_own_blast_radius( shape_a ):
    """
    The directory holds 3 tests across 2 files. The run accounts for 1. The other 2 never
    ran and are named nowhere — the report understates its reach while sounding precise.
    """
    code, out = _run_pytest( shape_a )
    assert code == 2
    assert "test_innocent_bystander" not in out, (
        "if pytest ever starts naming the tests it skipped at collection, this test should "
        "fail and the claim in the diagnosis module should be revised"
    )


# ── 2. THE "AFTER" — the diagnosis reports on both shapes ───────────────────
def test_shape_a_is_diagnosed_as_a_collection_error( shape_a ):
    code, out = _run_pytest( shape_a )
    diag = diagnose( code, out )

    assert diag is not None, "shape A must not go undiagnosed"
    assert diag[ "state" ] == COLLECTION_ERROR
    assert diag[ "where" ] == "test module"
    assert "orphaned import" in diag[ "cause_class" ]
    assert "credential_watcher_retired" in diag[ "detail" ]


def test_shape_b_is_diagnosed_with_its_cause_and_location( shape_b ):
    code, out = _run_pytest( shape_b )
    diag = diagnose( code, out )

    assert diag is not None, "shape B must not go undiagnosed — this is the invisible one"
    assert diag[ "state" ] == COLLECTION_ERROR
    assert diag[ "where" ] == "conftest"
    assert diag[ "cause_class" ] == "signature change ahead of its callers"
    assert "make_provenance" in diag[ "detail" ]


def test_rendered_block_says_plainly_what_it_is_not( shape_a ):
    """
    Both wrong readings cost time: "the suite went red" and "no red, so we're fine". The
    rendered block has to refuse both in its own words.
    """
    code, out = _run_pytest( shape_a )
    text = render( diagnose( code, out ) )

    assert "NOT a test failure" in text
    assert "greens were falsified" in text and "greens were confirmed" in text
    assert "COLLECTION ERROR" in text


def test_conftest_case_warns_that_no_hook_can_see_it( shape_b ):
    """The uncommitted/invisible case is the hardest, so the block must call it out."""
    code, out = _run_pytest( shape_b )
    text = render( diagnose( code, out ) )

    # Match across the line wrap — the rendered block is hard-wrapped for terminals, so
    # asserting on a raw phrase couples the test to where the wrap happens to fall.
    flat = " ".join( text.split() )
    assert "NO pytest hooks" in flat
    assert "takes the whole directory down" in flat


def test_uncommitted_files_are_named_because_git_log_cannot_see_them( shape_b, monkeypatch ):
    """
    John's incident was an uncommitted change: `git log` showed nothing and the cause was
    invisible to everyone but its author. The diagnosis names uncommitted .py files.
    """
    import cosa.utils.pytest_collection_diagnosis as mod
    monkeypatch.setattr( mod, "_find_uncommitted_python",
                         lambda project_root=None: [ "src/cosa/eval/provenance.py" ] )

    code, out = _run_pytest( shape_b )
    text = render( mod.diagnose( code, out ) )

    assert "UNCOMMITTED" in text
    assert "src/cosa/eval/provenance.py" in text
    assert "git log` cannot see" in text


# ── 2b. THE GATE — the scheduled path must stop calling it a red ────────────
def test_gate_reports_a_collection_error_as_its_own_state():
    """
    The counts a collection error produces (`errors=1`) are indistinguishable from a
    genuine red, so the flag is passed in from the exit code rather than re-derived.
    """
    counts = dict( passed=0, failed=0, errors=1, skipped=0 )
    assert TestSuiteJob._classify_outcome( **counts ) == "FAILED", "the 'before'"
    assert TestSuiteJob._classify_outcome( **counts, collection_error=True ) == "COLLECTION ERROR"


def test_gate_still_calls_a_genuine_failure_a_failure():
    """THE CONTROL. If the new state swallowed real reds it would hide actual defects."""
    assert TestSuiteJob._classify_outcome( passed=5, failed=1, errors=0, skipped=0 ) == "FAILED"
    assert TestSuiteJob._classify_outcome( passed=5, failed=0, errors=0, skipped=0 ) == "PASSED"
    assert TestSuiteJob._classify_outcome( passed=0, failed=0, errors=0, skipped=0 ) == "NOT EXECUTED"


def test_new_state_is_present_in_every_lookup_map():
    """
    Both maps are strict `[...]` lookups, so a state missing from either raises KeyError
    at report time — the run would die while writing its own report.
    """
    assert TestSuiteJob._OUTCOME_ICON[ "COLLECTION ERROR" ] == "COLLECT ERR"
    for state in ( "PASSED", "FAILED", "NOT EXECUTED", "COLLECTION ERROR" ):
        assert state in TestSuiteJob._OUTCOME_ICON


# ── 3. THE CONTROLS — it must stay silent on runs that DID execute ──────────
def test_a_real_pass_is_not_diagnosed_as_a_collection_error( tmp_path ):
    """
    THE CONTROL THAT MATTERS MOST. A diagnoser that fires on everything would satisfy
    every test above while making the third state meaningless.
    """
    d = tmp_path / "green"; d.mkdir()
    ( d / "test_green.py" ).write_text( "def test_ok(): assert True\n" )

    code, out = _run_pytest( d )
    assert code == 0
    assert diagnose( code, out ) is None


def test_a_real_failure_is_not_diagnosed_as_a_collection_error( tmp_path ):
    """A genuine red must stay a genuine red — it ran, and it failed."""
    d = tmp_path / "red"; d.mkdir()
    ( d / "test_red.py" ).write_text( "def test_bad(): assert False\n" )

    code, out = _run_pytest( d )
    assert code == 1
    assert diagnose( code, out ) is None, (
        "a failing test executed and produced a verdict; calling it a collection error "
        "would suppress a real defect"
    )


def test_empty_selection_is_flagged_rather_than_read_as_a_pass( tmp_path ):
    """Exit 5 — nothing collected — is the adjacent silence, and is not a pass either."""
    d = tmp_path / "empty"; d.mkdir()
    ( d / "test_nothing.py" ).write_text( "# no tests here\n" )

    code, out = _run_pytest( d )
    assert code == 5
    diag = diagnose( code, out )
    assert diag is not None and diag[ "cause_class" ] == "no tests matched"


def test_in_process_caller_gets_a_diagnosis_without_the_terminal_banner():
    """
    REGRESSION. `diagnose` used to require the "Interrupted: N errors during collection"
    banner to corroborate exit 2. That banner is written by pytest's TERMINAL REPORTER,
    not carried in a collect report, so the in-process `pytest_collectreport` hook — the
    one surface that can catch this shape at all — passed a traceback that never matched
    and silently got None back. The diagnostic was wired in and reported nothing.

    Caught only by running the hook for real inside the repo; the earlier tests fed full
    terminal output and so could not see it.
    """
    traceback_only = (
        "ImportError while importing test module '/x/test_orphan.py'.\n"
        "E   ModuleNotFoundError: No module named 'cosa.memory.credential_watcher_retired'\n"
    )
    assert diagnose( 2, traceback_only ) is None, (
        "unchanged: without a hint and without the banner, text alone is not enough"
    )

    diag = diagnose( 2, traceback_only, where_hint="test module" )
    assert diag is not None, "a caller that KNOWS collection failed must get a diagnosis"
    assert diag[ "where" ] == "test module"
    assert "credential_watcher_retired" in diag[ "detail" ]


def test_where_hint_cannot_manufacture_a_diagnosis_for_a_healthy_run():
    """The hint states WHERE, never WHETHER — exit 0 and 1 stay None regardless."""
    for code in ( 0, 1 ):
        assert diagnose( code, "anything at all", where_hint="test module" ) is None


def test_unrecognised_shape_is_admitted_rather_than_guessed():
    """An unknown import-time failure must say so, not invent a confident cause."""
    diag = diagnose( 2, "!!!! Interrupted: 1 error during collection !!!!\nE   RuntimeError: kaboom" )

    assert diag is not None
    assert diag[ "cause_class" ] == "unrecognised import-time failure"
    assert "kaboom" in diag[ "detail" ]
