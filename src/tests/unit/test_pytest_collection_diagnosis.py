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
    _read_tail,
    _strip_ansi,
    diagnose,
    main,
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


# ── 4. THE CLI — the surface the RUNNER SCRIPTS call (row 73c6819d) ─────────
# The suite job imports this module; a shell script cannot. The conftest shape fires no
# hook, so a runner's only route to a diagnosis is to run this file as a program, keyed on
# the exit code it just captured. These cover that entry point; the end-to-end proof that
# real runner scripts print real blocks lives in test_runner_collection_diagnosis.py.
def test_strip_ansi_removes_colour_and_is_idempotent():
    """
    Runner wrappers pipe pytest through `tee`, which kills colour, so they ask for it back
    with PY_COLORS — putting escape codes in the very text the cause regexes match against.
    """
    coloured = "\x1b[31mE   ModuleNotFoundError: No module named 'x'\x1b[0m"

    assert _strip_ansi( coloured ) == "E   ModuleNotFoundError: No module named 'x'"
    assert _strip_ansi( _strip_ansi( coloured ) ) == _strip_ansi( coloured )
    assert _strip_ansi( "plain text" ) == "plain text"


def test_a_coloured_traceback_is_still_classified():
    """The point of stripping: colour must not be able to silence the diagnosis."""
    coloured = ( "\x1b[1m!!!! Interrupted: 1 error during collection !!!!\x1b[0m\n"
                 "\x1b[31mE   ModuleNotFoundError: No module named 'cosa.gone'\x1b[0m\n" )
    diag = diagnose( 2, coloured )

    assert diag is not None
    assert "orphaned import" in diag[ "cause_class" ]
    assert "cosa.gone" in diag[ "detail" ]


def test_read_tail_returns_whole_small_files_and_caps_large_ones( tmp_path ):
    """A collection error's output is short; the cap stops a 200MB suite log being read."""
    small = tmp_path / "small.log"; small.write_text( "short output\n" )
    big   = tmp_path / "big.log";   big.write_text( "A" * 500 + "TAIL_MARKER" )

    assert _read_tail( str( small ) ) == "short output\n"
    tail = _read_tail( str( big ), max_bytes=20 )
    assert tail.endswith( "TAIL_MARKER" ) and len( tail ) == 20


def test_read_tail_is_silent_about_a_file_that_is_not_there( tmp_path ):
    """A missing capture must degrade to no diagnosis, never to an exception."""
    assert _read_tail( str( tmp_path / "never_written.log" ) ) == ""


def test_cli_prints_the_block_for_a_collection_error( tmp_path, capsys ):
    log = tmp_path / "run.log"
    log.write_text( "ImportError while loading conftest '/x/conftest.py'.\n"
                    "E   TypeError: make_provenance() missing 1 required positional argument: 'run_id'\n" )

    rc  = main( [ "--exit-code", "4", "--output-file", str( log ), "--project-root", str( tmp_path ) ] )
    out = capsys.readouterr().out

    assert rc == 0, "the diagnoser's status describes the DIAGNOSER, never the suite"
    assert COLLECTION_ERROR in out
    assert "signature change ahead of its callers" in out


def test_cli_says_nothing_about_a_run_that_actually_ran( tmp_path, capsys ):
    """THE CONTROL. A block on a pass or a plain failure would make the block meaningless."""
    log = tmp_path / "run.log"; log.write_text( "5 passed, 1 failed\n" )

    for code in ( 0, 1 ):
        assert main( [ "--exit-code", str( code ), "--output-file", str( log ) ] ) == 0
        assert capsys.readouterr().out == ""


def test_cli_accepts_a_where_hint_for_a_caller_that_already_knows( tmp_path, capsys ):
    log = tmp_path / "run.log"
    log.write_text( "E   ModuleNotFoundError: No module named 'cosa.retired'\n" )

    assert main( [ "--exit-code", "2", "--output-file", str( log ), "--where-hint", "test module" ] ) == 0
    assert "Where        : test module" in capsys.readouterr().out


def test_cli_runs_without_an_output_file( capsys ):
    """Exit 5 needs no output to be diagnosable — nothing was collected, and that is the fact."""
    assert main( [ "--exit-code", "5" ] ) == 0
    assert "no tests matched" in capsys.readouterr().out


def test_cli_returns_zero_on_a_malformed_call( capsys ):
    """
    argparse exits the process on bad arguments. Letting that escape would hand the shell a
    non-zero status for the DIAGNOSER, which the next `$?` would read as the run's verdict.
    """
    rc = main( [ "--exit-code", "not-a-number" ] )

    assert rc == 0
    assert "bad arguments" in capsys.readouterr().err


# ── 5. THE PATHS NOTHING HAD EXERCISED YET ─────────────────────────────────
# Found while measuring this file for the 100% gate: five branches of the original module
# had no test. Each is a place the diagnosis could go quiet or go wrong, so they are closed
# here rather than left as a number nobody looks at.
def test_uncommitted_scan_stays_quiet_when_git_is_unavailable( monkeypatch ):
    """
    The scan is a courtesy, not the diagnosis. A box without git, or a directory outside a
    work tree, must cost the reader the suspect list — never the whole block.
    """
    import cosa.utils.pytest_collection_diagnosis as mod

    def _no_git( *a, **kw ): raise FileNotFoundError( "git not found" )
    monkeypatch.setattr( mod.subprocess, "run", _no_git )
    assert mod._find_uncommitted_python( "/tmp" ) == []


def test_uncommitted_scan_ignores_non_python_and_malformed_porcelain_lines( monkeypatch ):
    """`git status --porcelain` carries two-char status flags, blank lines, and non-.py paths."""
    import cosa.utils.pytest_collection_diagnosis as mod

    class _Out:
        returncode = 0
        stdout     = " M src/a.py\n?? notes.md\n\n M src/b.py\n"

    monkeypatch.setattr( mod.subprocess, "run", lambda *a, **kw: _Out() )
    assert mod._find_uncommitted_python( "/tmp" ) == [ "src/a.py", "src/b.py" ]


def test_uncommitted_scan_stays_quiet_when_git_reports_failure( monkeypatch ):
    """A non-zero git (e.g. not a repository) is not a diagnosis failure."""
    import cosa.utils.pytest_collection_diagnosis as mod

    class _Fail:
        returncode = 128
        stdout     = ""

    monkeypatch.setattr( mod.subprocess, "run", lambda *a, **kw: _Fail() )
    assert mod._find_uncommitted_python( "/tmp" ) == []


def test_a_removed_symbol_is_named_as_an_orphaned_import():
    """The third cause class: the module still exists, the name in it does not."""
    diag = diagnose( 2, "!!!! Interrupted: 1 error during collection !!!!\n"
                        "E   ImportError: cannot import name 'make_provenance' from 'cosa.eval.provenance'" )

    assert diag[ "cause_class" ] == "orphaned import — the name is gone from a module that still exists"
    assert "make_provenance" in diag[ "detail" ] and "cosa.eval.provenance" in diag[ "detail" ]


def test_output_with_no_exception_line_is_admitted_rather_than_guessed():
    """Nothing recognisable at all still gets an honest answer instead of a confident one."""
    diag = diagnose( 4, "ImportError while loading conftest '/x/conftest.py'." )

    assert diag[ "cause_class" ] == "unrecognised import-time failure"
    assert diag[ "detail" ] == "no recognisable exception line in the captured output"


def test_a_long_suspect_list_is_truncated_and_says_how_many_it_hid():
    """Ten names is a list a human reads; forty is a wall they skip — so it says '… and N more'."""
    diag = {
        "state"                : COLLECTION_ERROR,
        "where"                : "conftest",
        "cause_class"          : "x",
        "detail"               : "y",
        "remedy"               : "z",
        "uncommitted_suspects" : [ f"src/f{i}.py" for i in range( 14 ) ],
    }
    text = render( diag )

    assert "src/f9.py" in text and "src/f10.py" not in text
    assert "… and 4 more" in text


def test_cli_returns_zero_when_the_diagnosis_itself_blows_up( monkeypatch, capsys ):
    """A broken diagnostic must not be able to change the outcome of the run it describes."""
    import cosa.utils.pytest_collection_diagnosis as mod

    def _boom( *a, **kw ): raise RuntimeError( "diagnoser is broken" )
    monkeypatch.setattr( mod, "diagnose", _boom )

    assert mod.main( [ "--exit-code", "4" ] ) == 0
    assert "could not render a diagnosis" in capsys.readouterr().err
