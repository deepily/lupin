"""
The runner script of the documentation lint gate, driven in a scratch git tree.

The script is what the merge pyramid and the pre-push hook call. These tests pin its exit codes:
0 clean, 1 a finding, 2 nothing checked, 3 no interpreter. A run that could not check must never
print what a clean tree prints.

Run on the whole tree, the script has a second step: the check of the metrics dashboard page.
The summary then counts the swept files plus one for that check.
"""

import os
import shutil
import subprocess
import sys

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
GATE         = os.path.join( PROJECT_ROOT, "src", "tests", "run-doclint-gate.sh" )
RESOLVER     = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "resolve-venv-pytest.sh" )
WORD_LIST    = os.path.join( PROJECT_ROOT, "src", "conf", "dm-tutor-lowercase-words.txt" )
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
CLEAN        = '"""\nAdd two numbers.\n"""\n'
PAGE         = "src/docs/doc-metrics-dashboard.md"
BASE         = ( "--dashboard-base", "HEAD" )
STUB_CLEAN   = 'if __name__ == "__main__": print( "Total Tests: 1\\nPassed: 1\\nFailed: 0\\nErrors: 0\\nDOCLINT GATE PASSED: all 1 files clean." )\n'
LOUD         = '"""\nThis module must NEVER change.\n"""\n'

# No skip when this tree has no .venv: the resolver also accepts the container interpreter, and a
# tree with neither fails these tests by name. The venv guard lists this file as one that breaks.


def _git( repo, *args ):
    subprocess.run( [ "git", *args ], cwd=repo, check=True, timeout=60, capture_output=True )


def _write( repo, rel, text ):
    path = repo / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )


def _write_page( repo ):
    """Write the dashboard page of the tree, with the commit it is checked out at as its before."""
    ( repo / "src" / "docs" ).mkdir( parents=True, exist_ok=True )
    env  = dict( os.environ, PYTHONPATH=os.path.join( PROJECT_ROOT, "src" ), LUPIN_ROOT=PROJECT_ROOT )
    done = subprocess.run( [ sys.executable, "-m", "cosa.repo.doc_lint.doc_metrics", "dashboard", "write", "--base", "HEAD", "--repo-root", str( repo ), "--words-root", str( repo ) ], capture_output=True, text=True, timeout=120, env=env )
    assert done.returncode == 0, done.stdout + done.stderr


def _page( repo ):
    """Commit what is staged, then write the dashboard page."""
    _git( repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base" )
    _write_page( repo )


@pytest.fixture
def repo( tmp_path ):
    """A scratch git tree holding the real runner, the real resolver and the real lint package."""
    _git( tmp_path, "init", "-q" )
    for src, rel in ( ( GATE, "src/tests/run-doclint-gate.sh" ), ( RESOLVER, "src/scripts/lib/resolve-venv-pytest.sh" ), ( WORD_LIST, "src/conf/dm-tutor-lowercase-words.txt" ) ):
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( src, tmp_path / rel )
    os.symlink( os.path.join( PROJECT_ROOT, "src", "cosa" ), tmp_path / "src" / "cosa" )
    if os.path.isdir( VENV ): os.symlink( VENV, tmp_path / ".venv" )
    return tmp_path


def _run_split( repo, *args ):
    done = subprocess.run( [ "bash", str( repo / "src" / "tests" / "run-doclint-gate.sh" ), *args ], capture_output=True, text=True, timeout=120 )
    return done.returncode, done.stdout, done.stderr


def _run( repo, *args ):
    code, out, err = _run_split( repo, *args )
    return code, out + err


def _stub_gate( repo, body ):
    """Replace the lint package with a stub whose scope_gate module runs the given body."""
    os.unlink( repo / "src" / "cosa" )
    for rel in ( "src/cosa/__init__.py", "src/cosa/repo/__init__.py", "src/cosa/repo/doc_lint/__init__.py" ): _write( repo, rel, "" )
    _write( repo, "src/cosa/repo/doc_lint/scope_gate.py", body )


def test_a_clean_tree_exits_zero_and_prints_the_file_count( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )

    code, text = _run( repo, *BASE )

    assert code == 0
    assert "Docstring step, files checked: 1\nDocstring step, files clean: 1\nDocstring step, files with a finding: 0\nDocstring step, findings: 0\n" in text
    assert "Docstring step passed: all 1 files clean." in text
    assert "DASHBOARD CHECK PASSED: 1 rows, no compared value rose and the page matches the tree." in text
    assert "Total Tests: 2\nPassed: 2\nFailed: 0\nErrors: 0\n" in text
    assert text.count( "Total Tests:" ) == 1 and text.count( "Passed:" ) == 1 and text.count( "Failed:" ) == 1
    assert text.rstrip( "\n" ).split( "\n" )[ -1 ] == "DOCLINT GATE PASSED: 1 files clean and the dashboard check passed."


def test_one_planted_finding_exits_one_and_names_its_line( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src/app" )
    _page( repo )

    code, text = _run( repo, *BASE )

    assert code == 1
    assert "src/app/loud.py:2: caps: ALL-CAPS word NEVER" in text
    assert "Docstring step failed: 1 findings in 1 of 2 files." in text
    assert "DASHBOARD CHECK PASSED: 1 rows" in text
    assert "Total Tests: 3\nPassed: 2\nFailed: 1\nErrors: 1\n" in text
    assert text.rstrip( "\n" ).split( "\n" )[ -1 ] == "DOCLINT GATE FAILED: 1 of 2 files hold a finding; the dashboard check passed."


# The second step, the dashboard check. Its exit 1 (a value rose) and 3 (a row is missing, or the page
# names another before commit) both fail the gate with exit 1, because exit 3 of this script already
# means no interpreter. Its exit 4 (only the numbers on the page are stale) passes the gate with a
# warning line. Its exit 2 (could not check) is exit 2 here, with no summary block, so the job reads
# the run as not executed.

def _stale_numbers( repo ):
    page = ( repo / PAGE ).read_text( encoding="utf-8" )
    assert page.count( "3 -> 3" ) == 2, "the one row and the total row both read 3 tokens"
    ( repo / PAGE ).write_text( page.replace( "3 -> 3", "3 -> 4" ), encoding="utf-8" )
    sha = subprocess.run( [ "git", "rev-parse", "HEAD" ], cwd=repo, check=True, capture_output=True, text=True ).stdout.strip()
    return f"PYTHONPATH=src python3 -m cosa.repo.doc_lint.doc_metrics dashboard write --base {sha}"


def test_stale_numbers_on_the_dashboard_page_pass_the_gate_with_a_warning( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )
    command = _stale_numbers( repo )

    code, out, _ = _run_split( repo, *BASE )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )
    warning      = f"WARNING {PAGE}: the numbers on the page are stale, 2 of its rows differ from the tree; regenerate with: {command}\n"

    assert code == 0
    assert out.count( warning ) == 1 and out.count( "WARNING " ) == 1
    assert out.index( warning ) < out.index( "Total Tests:" )
    assert "REFUSING" not in out and "could not check" not in out
    assert "Total Tests: 2\nPassed: 2\nFailed: 0\nErrors: 0\n" in out
    assert out.rstrip( "\n" ).split( "\n" )[ -1 ] == f"DOCLINT GATE PASSED: 1 files clean; dashboard numbers are stale, regenerate with: {command}"
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 2, 0 )


def test_stale_numbers_beside_a_docstring_finding_fail_the_gate_and_keep_the_warning( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src/app" )
    _page( repo )
    page = ( repo / PAGE ).read_text( encoding="utf-8" )
    assert page.count( "8 -> 8" ) == 2
    ( repo / PAGE ).write_text( page.replace( "8 -> 8", "8 -> 9" ), encoding="utf-8" )

    code, text = _run( repo, *BASE )

    assert code == 1
    assert text.count( "WARNING " ) == 1
    assert "Total Tests: 3\nPassed: 2\nFailed: 1\nErrors: 1\n" in text
    last = text.rstrip( "\n" ).split( "\n" )[ -1 ]
    assert last.startswith( "DOCLINT GATE FAILED: 1 of 2 files hold a finding; the dashboard check passed; dashboard numbers are stale, regenerate with: PYTHONPATH=src python3 " )


def test_a_row_missing_from_the_dashboard_page_fails_the_gate_while_the_docstrings_are_clean( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )
    lines = ( repo / PAGE ).read_text( encoding="utf-8" ).split( "\n" )
    gone  = [ line for line in lines if line.split( "|" )[ 0 ].strip() == "src/app" ]
    assert len( gone ) == 1
    ( repo / PAGE ).write_text( "\n".join( line for line in lines if line != gone[ 0 ] ), encoding="utf-8" )

    code, out, _ = _run_split( repo, *BASE )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )

    assert code == 1
    assert "Docstring step passed: all 1 files clean." in out
    assert f"MISSING src/app: no row on {PAGE}" in out
    assert "Total Tests: 2\nPassed: 1\nFailed: 1\nErrors: 1\n" in out
    assert out.rstrip( "\n" ).split( "\n" )[ -1 ] == "DOCLINT GATE FAILED: 0 of 1 files hold a finding; the dashboard check failed."
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 1, 1 )


def test_a_risen_marker_rate_fails_the_gate( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )
    _write( repo, "src/app/a.py", LOUD )
    _write_page( repo )

    code, text = _run( repo, *BASE )

    assert code == 1
    assert "ROSE src/app: caps_words 0/3 -> 1/5 per token (0.0 -> 200.0 per 1,000)" in text
    assert "DASHBOARD CHECK FAILED: 1 values rose in 1 rows; the page matches the tree." in text
    assert "Total Tests: 2\nPassed: 0\nFailed: 2\nErrors: 2\n" in text
    assert text.rstrip( "\n" ).split( "\n" )[ -1 ] == "DOCLINT GATE FAILED: 1 of 1 files hold a finding; the dashboard check failed."


def test_a_missing_dashboard_page_refuses_and_prints_no_summary_block( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )
    os.remove( repo / PAGE )

    code, out, _ = _run_split( repo, *BASE )

    assert code == 2
    assert "doc-metrics dashboard: could not check: FileNotFoundError" in out
    assert "REFUSING: the dashboard check could not check (exit 2). Nothing is summarised." in out
    assert "Total Tests:" not in out and "PASSED" not in out and "Docstring step passed: all 1 files clean." in out
    assert TestSuiteJob._parse_non_pytest_stdout( "doclint", out ) is None


def test_a_before_commit_the_repo_does_not_hold_refuses( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )

    code, text = _run( repo )

    assert code == 2
    assert "doc-metrics dashboard: could not check: RuntimeError: git rev-parse" in text
    assert "REFUSING: the dashboard check could not check (exit 2). Nothing is summarised." in text
    assert "Total Tests:" not in text and "PASSED" not in text


@pytest.mark.parametrize( "body,said", [
    ( 'if __name__ == "__main__": raise ValueError( "boom" )\n', "REFUSING: the dashboard check exited 1 without a verdict line. Nothing was checked." ),
    ( 'import sys\nif __name__ == "__main__":\n    print( "DASHBOARD CHECK EXPLODED: no check ran" )\n    sys.exit( 3 )\n', "REFUSING: the dashboard check exited 3 without a verdict line. Nothing was checked." ),
    ( 'import sys\nif __name__ == "__main__": sys.exit( 7 )\n', "REFUSING: the dashboard check exited 7, which is not a check result. Nothing was checked." ),
    ( 'import sys\nif __name__ == "__main__":\n    print( "DASHBOARD CHECK PASSED: 1 rows, the numbers on the page are stale." )\n    sys.exit( 4 )\n', "REFUSING: the dashboard check exited 4 without its warning line. Nothing was checked." )
] )
def test_a_dashboard_check_that_dies_is_refused_not_read_as_a_rise( repo, body, said ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _stub_gate( repo, STUB_CLEAN )
    _write( repo, "src/cosa/repo/doc_lint/doc_metrics.py", body )

    code, text = _run( repo, *BASE )

    assert code == 2
    assert said in text
    assert "Total Tests:" not in text and "PASSED" not in text


def test_a_docstring_step_whose_counts_cannot_be_read_is_refused( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _stub_gate( repo, 'if __name__ == "__main__": print( "DOCLINT GATE PASSED: all 1 files clean." )\n' )
    _write( repo, "src/cosa/repo/doc_lint/doc_metrics.py", 'if __name__ == "__main__": print( "DASHBOARD CHECK PASSED: 1 rows" )\n' )

    code, text = _run( repo, *BASE )

    assert code == 2
    assert "REFUSING: the docstring step printed no counts to add to. Nothing is summarised." in text
    assert "Total Tests:" not in text


def test_the_dashboard_base_option_needs_a_revision( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )

    code, text = _run( repo, "--dashboard-base" )

    assert code == 2
    assert "REFUSING: --dashboard-base needs a revision. Nothing was checked." in text
    assert "PASSED" not in text


def test_the_population_is_tracked_swept_files_only( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/lupin_mcp/tool.py", LOUD )
    _git( repo, "add", "src/app", "src/lupin_mcp" )
    _write( repo, "src/app/untracked.py", LOUD )

    code, text = _run( repo, "--list" )

    assert code == 0
    assert text.split() == [ "src/app/a.py" ]


def test_a_listing_that_fails_exits_nonzero( repo ):
    shutil.rmtree( repo / ".git" )

    code, text = _run( repo, "--list" )

    assert code != 0
    assert "git ls-files failed" in text


def test_a_last_line_that_only_resembles_a_verdict_is_refused( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _stub_gate( repo, 'import sys\nif __name__ == "__main__":\n    print( "DOCLINT GATE EXPLODED: no check ran" )\n    sys.exit( 1 )\n' )

    code, text = _run( repo )

    assert code == 2
    assert "REFUSING: the gate exited 1 without a verdict line. Nothing was checked." in text


def test_what_the_gate_writes_to_standard_error_is_in_the_printed_report( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    _stub_gate( repo, 'if __name__ == "__main__": raise ValueError( "boom" )\n' )

    code, out, err = _run_split( repo )

    assert code == 2
    assert "ValueError: boom" in out
    assert "ValueError: boom" not in err


def test_tree_mode_lints_another_tree_with_this_trees_word_list( repo, tmp_path_factory ):
    other = tmp_path_factory.mktemp( "other" )
    _git( other, "init", "-q" )
    _write( other, "src/app/loud.py", LOUD )
    _write( other, "src/conf/dm-tutor-lowercase-words.txt", "" )
    _git( other, "add", "src" )
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )

    code, text = _run( repo, "--tree", str( other ) )

    assert code == 1
    assert "src/app/loud.py:2: caps: ALL-CAPS word NEVER" in text
    assert f"  tree   : {other}" in text
    assert "DOCLINT GATE FAILED: 1 findings in 1 of 1 files." in text
    assert "Total Tests: 1\nPassed: 0\nFailed: 1\nErrors: 1\n" in text
    assert "Dashboard check: not run with --tree; the whole-tree run of this script runs it." in text
    assert "DASHBOARD CHECK" not in text and "doc-metrics dashboard" not in text


@pytest.mark.parametrize( "args", [ ( "--tree", ), ( "--tree", "/no/such/directory" ) ] )
def test_tree_mode_without_a_directory_refuses( repo, args ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )

    code, text = _run( repo, *args )

    assert code == 2
    assert "REFUSING: --tree needs a directory" in text
    assert "PASSED" not in text


def test_no_swept_file_refuses_rather_than_passing( repo ):
    code, text = _run( repo )

    assert code == 2
    assert "REFUSING: no swept file found" in text
    assert "PASSED" not in text


def test_a_lint_package_that_does_not_import_refuses( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    os.unlink( repo / "src" / "cosa" )

    code, text = _run( repo )

    assert code == 2
    assert "REFUSING: cosa.repo.doc_lint.scope_gate does not import" in text
    assert "PASSED" not in text


def test_a_gate_that_dies_with_exit_one_is_refused_not_read_as_findings( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    os.unlink( repo / "src" / "cosa" )
    _write( repo, "src/cosa/__init__.py", "" )
    _write( repo, "src/cosa/repo/__init__.py", "" )
    _write( repo, "src/cosa/repo/doc_lint/__init__.py", "" )
    _write( repo, "src/cosa/repo/doc_lint/scope_gate.py", 'if __name__ == "__main__": raise ValueError( "boom" )\n' )

    code, text = _run( repo )

    assert code == 2
    assert "REFUSING: the gate exited 1 without a verdict line. Nothing was checked." in text


def test_a_gate_that_exits_with_an_unknown_code_is_refused( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    os.unlink( repo / "src" / "cosa" )
    _write( repo, "src/cosa/__init__.py", "" )
    _write( repo, "src/cosa/repo/__init__.py", "" )
    _write( repo, "src/cosa/repo/doc_lint/__init__.py", "" )
    _write( repo, "src/cosa/repo/doc_lint/scope_gate.py", 'import sys\nif __name__ == "__main__": sys.exit( 7 )\n' )

    code, text = _run( repo )

    assert code == 2
    assert "REFUSING: the gate exited 7, which is not a lint result. Nothing was checked." in text


@pytest.mark.skipif( os.path.exists( "/opt/venv/bin/python3" ), reason="this host has the container interpreter, so the resolver finds one" )
def test_no_interpreter_exits_three( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _git( repo, "add", "src/app" )
    if os.path.islink( repo / ".venv" ): os.unlink( repo / ".venv" )

    code, text = _run( repo )

    assert code == 3
    assert "PASSED" not in text


# The pyramid's side of the contract (row 2c48c717): TestSuiteJob reads this runner's stdout, so
# these cases pass the real runner's output through the real parser. The counts are literals.

def test_the_job_reads_a_red_run_as_files_passed_and_failed( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/b.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src/app" )
    _page( repo )

    code, out, _ = _run_split( repo, *BASE )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )

    assert code == 1
    assert parsed is not None, "the job does not parse the doclint runner's summary, so a red gate would read as not executed"
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 3, 1 ), "two clean files and the dashboard check passed; one file failed"


def test_the_job_reads_a_clean_run_as_all_files_passed( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/b.py", CLEAN )
    _git( repo, "add", "src/app" )
    _page( repo )

    code, out, _ = _run_split( repo, *BASE )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )

    assert code == 0
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 3, 0 ), "two clean files and the dashboard check"


def test_the_job_reads_a_refused_run_as_nothing_parsed( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    code, out, _ = _run_split( repo )

    assert code == 2
    assert TestSuiteJob._parse_non_pytest_stdout( "doclint", out ) is None


def test_the_suite_is_registered_with_this_runner_a_budget_and_a_log_name():
    from cosa.agents.test_suite.job import ALL_SUITE_COMPONENTS, SUITE_SCRIPTS, SUITE_TIMEOUTS_SECONDS, TestSuiteJob

    assert os.path.join( PROJECT_ROOT, SUITE_SCRIPTS[ "doclint" ] ) == GATE
    assert os.access( GATE, os.X_OK )
    assert SUITE_TIMEOUTS_SECONDS[ "doclint" ] == 300
    assert TestSuiteJob._LOG_BASENAMES[ "doclint" ] == "doclint-gate-latest.log"
    assert ALL_SUITE_COMPONENTS.index( "doclint" ) < ALL_SUITE_COMPONENTS.index( "unit" )
