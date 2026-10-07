"""
The runner script of the documentation lint gate, driven in a scratch git tree.

The script is what the merge pyramid and the pre-push hook call. These tests pin its exit codes:
0 clean, 1 a finding, 2 nothing checked, 3 no interpreter. A run that could not check must never
print what a clean tree prints.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
GATE         = os.path.join( PROJECT_ROOT, "src", "tests", "run-doclint-gate.sh" )
RESOLVER     = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "resolve-venv-pytest.sh" )
WORD_LIST    = os.path.join( PROJECT_ROOT, "src", "conf", "dm-tutor-lowercase-words.txt" )
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
CLEAN        = '"""\nAdd two numbers.\n"""\n'
LOUD         = '"""\nThis module must NEVER change.\n"""\n'

pytestmark = pytest.mark.skipif( not os.path.isdir( VENV ), reason="the gate needs a .venv beside the tree, and this tree has none" )


def _git( repo, *args ):
    subprocess.run( [ "git", *args ], cwd=repo, check=True, timeout=60, capture_output=True )


def _write( repo, rel, text ):
    path = repo / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )


@pytest.fixture
def repo( tmp_path ):
    """A scratch git tree holding the real runner, the real resolver and the real lint package."""
    _git( tmp_path, "init", "-q" )
    for src, rel in ( ( GATE, "src/tests/run-doclint-gate.sh" ), ( RESOLVER, "src/scripts/lib/resolve-venv-pytest.sh" ), ( WORD_LIST, "src/conf/dm-tutor-lowercase-words.txt" ) ):
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( src, tmp_path / rel )
    os.symlink( os.path.join( PROJECT_ROOT, "src", "cosa" ), tmp_path / "src" / "cosa" )
    os.symlink( VENV, tmp_path / ".venv" )
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

    code, text = _run( repo )

    assert code == 0
    assert "Total Tests: 1\nPassed: 1\nFailed: 0\n" in text
    assert "DOCLINT GATE PASSED: all 1 files clean." in text


def test_one_planted_finding_exits_one_and_names_its_line( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src/app" )

    code, text = _run( repo )

    assert code == 1
    assert "src/app/loud.py:2: caps: ALL-CAPS word NEVER" in text
    assert "DOCLINT GATE FAILED: 1 findings in 1 of 2 files." in text


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
    os.unlink( repo / ".venv" )

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

    code, out, _ = _run_split( repo )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )

    assert code == 1
    assert parsed is not None, "the job does not parse the doclint runner's summary, so a red gate would read as not executed"
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 2, 1 )


def test_the_job_reads_a_clean_run_as_all_files_passed( repo ):
    from cosa.agents.test_suite.job import TestSuiteJob

    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/b.py", CLEAN )
    _git( repo, "add", "src/app" )

    code, out, _ = _run_split( repo )
    parsed       = TestSuiteJob._parse_non_pytest_stdout( "doclint", out )

    assert code == 0
    assert ( parsed[ "passed" ], parsed[ "failed" ] ) == ( 2, 0 )


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
