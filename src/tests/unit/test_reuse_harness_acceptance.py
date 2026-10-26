"""
Unit tests of the acceptance test port.

One group runs real pytest on a small frozen test folder in a real git repository, so the junit file is the real producer's.
The other groups use a runner that writes a hand-made report, to reach the cases a real run is slow or unwilling to make.
"""
import os
import subprocess
import sys

import pytest

from lupin_mcp.reuse_harness import acceptance
from lupin_mcp.reuse_harness import commands
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness.freeze import TEST_DIR
from lupin_mcp.reuse_harness.worktree import CLIENT_ROOT

REAL_TESTS = '''import pytest


def test_passes():
    assert True


def test_fails():
    assert False


@pytest.mark.skip( reason="skipped" )
def test_skipped():
    pass


@pytest.mark.parametrize( "value", [ 1, 2 ] )
def test_one_case_fails( value ):
    assert value == 1


def test_errors( missing_fixture ):
    pass
'''
HANDLE     = { "url" : "http://127.0.0.1:18267", "container" : "c", "db_name" : "d" }
CLASS      = TEST_DIR.replace( "/", "." ) + ".test_x"


def git_in( root, *args ):
    """Run git in a test repository and return its output."""
    return subprocess.run( [ "git", "-C", str( root ), "-c", "user.name=t", "-c", "user.email=t@example.com", *args ], check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def tree( tmp_path ):
    """Build a repository of frozen tests, a server file and an old client page."""
    git_in( tmp_path, "init", "-q", "-b", "main" )
    for relative, text in { f"{TEST_DIR}/test_x.py" : REAL_TESTS, "src/cosa/server.py" : "x = 1\n", f"{CLIENT_ROOT}/old.html" : "old" }.items():
        ( tmp_path / relative ).parent.mkdir( parents=True, exist_ok=True )
        ( tmp_path / relative ).write_text( text )
    git_in( tmp_path, "add", "." )
    git_in( tmp_path, "commit", "-q", "-m", "frozen" )
    reports = tmp_path.parent / ( tmp_path.name + "-reports" )
    reports.mkdir()
    return { "path" : str( tmp_path ), "root" : tmp_path, "commit" : git_in( tmp_path, "rev-parse", "HEAD" ), "reports" : str( reports ) }


def case( name, child=None, classname=CLASS ):
    """Return one junit testcase as text, with an optional failure, error or skipped child."""
    body = f"<{child}/>" if child else ""
    return f'<testcase classname="{classname}" name="{name}">{body}</testcase>'


class Runner:
    """A runner that records calls, writes a given report for pytest and answers fixed codes."""

    def __init__( self, report="", pytest_code=0, build_code=0, write=True ):
        """Choose the report text and the exit codes."""
        self.report, self.pytest_code, self.build_code, self.write = report, pytest_code, build_code, write
        self.calls = []

    def __call__( self, argv, env=None, cwd=None, timeout=None ):
        """Record the call; for pytest, write the report its command line names."""
        self.calls.append( { "argv" : argv, "env" : env, "cwd" : cwd, "timeout" : timeout } )
        if "pytest" in argv:
            if self.write: open( [ word for word in argv if word.startswith( "--junitxml=" ) ][ 0 ].split( "=", 1 )[ 1 ], "w" ).write( f"<testsuites><testsuite>{self.report}</testsuite></testsuites>" )
            return self.pytest_code, "collected 2 items\nFAILED something"
        return self.build_code, ""


def make( tree, runner, **options ):
    """Return an Acceptance over the tree's commit and report folder."""
    return acceptance.Acceptance( tree[ "commit" ], "notify-key-value", tree[ "reports" ], runner=runner, **options )


def ids( *names ):
    """Return the test ids of the given function names in the test file."""
    return [ f"{TEST_DIR}/test_x.py::{name}" for name in names ]


def code_of( call ):
    """Return the code of the HarnessError a call raises."""
    with pytest.raises( err.HarnessError ) as caught: call()
    return caught.value.code


def test_real_pytest_report_gives_one_verdict_per_id_and_a_skip_an_error_or_one_failed_case_is_not_a_pass( tree ):
    ( tree[ "root" ] / TEST_DIR / "conftest.py" ).write_text( "" )
    git_in( tree[ "root" ], "add", "." )
    git_in( tree[ "root" ], "commit", "-q", "-m", "conftest" )
    port    = acceptance.Acceptance( git_in( tree[ "root" ], "rev-parse", "HEAD" ), "k", tree[ "reports" ], python=sys.executable, build_command=( sys.executable, "-c", "pass" ) )
    wanted  = ids( "test_passes", "test_fails", "test_skipped", "test_one_case_fails", "test_errors", "test_not_collected" )
    outcome = port.run( HANDLE, tree[ "path" ], wanted )
    assert outcome[ "results" ] == dict( zip( wanted, [ True, False, False, False, False, False ] ) )
    assert outcome[ "client_builds" ] is True


def test_the_build_verdict_follows_the_build_commands_exit_code( tree ):
    runner = Runner( report=case( "test_passes" ), build_code=1 )
    assert make( tree, runner ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )[ "client_builds" ] is False
    assert make( tree, Runner( report=case( "test_passes" ) ) ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )[ "client_builds" ] is True


def test_a_client_with_no_build_command_to_run_scores_false_and_keeps_the_test_verdicts( tree ):
    port = acceptance.Acceptance( tree[ "commit" ], "k", tree[ "reports" ], python=sys.executable, build_command=( "/no/such/build", ) )
    outcome = port.run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    assert outcome[ "client_builds" ] is False and set( outcome[ "results" ] ) == set( ids( "test_passes" ) )


def test_pytest_gets_the_servers_url_and_the_key_only_in_its_environment_and_runs_in_the_worktree( tree ):
    runner = Runner( report=case( "test_passes" ) )
    make( tree, runner ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    call = runner.calls[ 0 ]
    assert ( call[ "env" ][ "EXPERIMENT_SERVER_URL" ], call[ "env" ][ "EXPERIMENT_NOTIFY_API_KEY" ] ) == ( HANDLE[ "url" ], "notify-key-value" )
    assert "notify-key-value" not in " ".join( call[ "argv" ] ) and call[ "cwd" ] == tree[ "path" ]
    assert call[ "argv" ][ :4 ] == [ os.path.join( tree[ "path" ], ".venv", "bin", "python" ), "-m", "pytest", TEST_DIR ]
    assert call[ "timeout" ] == acceptance.TEST_TIMEOUT


def test_the_build_runs_in_the_worktree_with_the_build_timeout_and_the_chosen_command( tree ):
    runner = Runner( report=case( "test_passes" ) )
    make( tree, runner, build_command=[ "make", "client" ] ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    assert ( runner.calls[ 1 ][ "argv" ], runner.calls[ 1 ][ "cwd" ], runner.calls[ 1 ][ "timeout" ] ) == ( [ "make", "client" ], tree[ "path" ], acceptance.BUILD_TIMEOUT )
    assert make( tree, runner ).build_command == [ "npm", "run", "build" ]


def test_each_call_keeps_its_own_report( tree ):
    port = make( tree, Runner( report=case( "test_passes" ) ) )
    port.run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    port.run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    assert sorted( os.listdir( tree[ "reports" ] ) ) == [ "junit-1.xml", "junit-2.xml" ]


@pytest.mark.parametrize( "child", [ "failure", "error", "skipped" ] )
def test_a_case_with_a_failure_error_or_skip_child_is_not_a_pass( tree, child ):
    outcome = make( tree, Runner( report=case( "test_a", child ) + case( "test_b" ) ) ).run( HANDLE, tree[ "path" ], ids( "test_a", "test_b" ) )
    assert outcome[ "results" ] == dict( zip( ids( "test_a", "test_b" ), [ False, True ] ) )


@pytest.mark.parametrize( "report", [ case( "test_a[1]", "failure" ) + case( "test_a[2]" ), case( "test_a[1]" ) + case( "test_a[2]", "failure" ) ] )
def test_parametrized_cases_pass_only_when_every_case_passes_whatever_their_order( tree, report ):
    assert make( tree, Runner( report=report ) ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )[ "results" ] == { ids( "test_a" )[ 0 ] : False }


def test_parametrized_cases_that_all_pass_make_the_test_pass_under_its_unparametrized_id( tree ):
    outcome = make( tree, Runner( report=case( "test_a[1]" ) + case( "test_a[2]" ) ) ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )
    assert outcome[ "results" ] == { ids( "test_a" )[ 0 ] : True }


def test_a_case_without_a_class_name_matches_no_test_and_the_tests_stay_failed( tree ):
    outcome = make( tree, Runner( report=f'<testcase name="{CLASS}"><error/></testcase>' ) ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )
    assert outcome[ "results" ] == { ids( "test_a" )[ 0 ] : False }
    xml_without_class = '<testcase name="x"/>'
    assert make( tree, Runner( report=xml_without_class ) ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )[ "results" ] == { ids( "test_a" )[ 0 ] : False }


def test_a_test_in_the_report_that_is_not_in_the_frozen_list_is_ignored_and_a_listed_test_missing_from_it_fails( tree ):
    outcome = make( tree, Runner( report=case( "test_extra" ) ) ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )
    assert outcome[ "results" ] == { ids( "test_a" )[ 0 ] : False }


@pytest.mark.parametrize( "runner", [ Runner( pytest_code=2, report="" ), Runner( pytest_code=127, write=False ), Runner( pytest_code=0, write=False ) ] )
def test_pytest_that_did_not_finish_or_wrote_no_report_is_not_a_set_of_failures( tree, runner ):
    with pytest.raises( err.HarnessError ) as caught: make( tree, runner ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )
    assert caught.value.code == err.TESTS_NOT_RUN and "FAILED something" in caught.value.detail
    assert len( runner.calls ) == 1


def test_an_unreadable_report_is_refused_not_read_as_all_failed( tree ):
    runner = Runner( report="<<<not xml" )
    with pytest.raises( err.HarnessError ) as caught: make( tree, runner ).run( HANDLE, tree[ "path" ], ids( "test_a" ) )
    assert caught.value.code == err.TESTS_NOT_RUN and "not readable" in caught.value.detail
    assert len( runner.calls ) == 1


def test_a_clean_tree_is_accepted_even_when_the_run_built_files_in_the_client_folder( tree ):
    ( tree[ "root" ] / CLIENT_ROOT / "old.html" ).write_text( "rewritten by the run" )
    ( tree[ "root" ] / CLIENT_ROOT / "login.html" ).write_text( "built by the run" )
    ( tree[ "root" ] / "client" ).mkdir()
    ( tree[ "root" ] / "client" / "app.ts" ).write_text( "export {}" )
    assert make( tree, Runner( report=case( "test_passes" ) ) ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )[ "results" ] == { ids( "test_passes" )[ 0 ] : True }


@pytest.mark.parametrize( "edit", [
    lambda root: ( root / TEST_DIR / "test_x.py" ).write_text( "def test_passes():\n    assert True\n" ),
    lambda root: ( root / TEST_DIR / "test_added.py" ).write_text( "def test_new():\n    pass\n" ),
    lambda root: ( root / TEST_DIR / "test_x.py" ).unlink(),
    lambda root: ( root / "src/cosa/server.py" ).write_text( "x = 2\n" ),
    lambda root: ( root / "src/lupin_app/main_extra.py" ).write_text( "y = 1\n" ),
] )
def test_a_run_that_changed_the_tests_or_the_server_is_refused_before_pytest_runs( tree, edit ):
    edit( tree[ "root" ] )
    runner = Runner( report=case( "test_passes" ) )
    with pytest.raises( err.HarnessError ) as caught: make( tree, runner ).run( HANDLE, tree[ "path" ], ids( "test_passes" ) )
    assert caught.value.code == err.TESTS_TAMPERED and tree[ "commit" ] in caught.value.detail
    assert runner.calls == []


def test_the_default_runner_environment_and_interpreter_are_the_real_ones( tree ):
    port = acceptance.Acceptance( tree[ "commit" ], "k", tree[ "reports" ] )
    assert ( port.runner, port.environ, port.python ) == ( commands.run_command, os.environ, None )
