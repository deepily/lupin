"""
Unit tests of the shared command runner, run for real against a local interpreter.
"""
import sys

from lupin_mcp.reuse_harness import commands


def test_run_command_returns_the_exit_code_and_both_output_streams():
    code, output = commands.run_command( [ sys.executable, "-c", "import sys; print( 'out' ); print( 'err', file=sys.stderr ); sys.exit( 3 )" ] )
    assert code == 3 and output == "out\nerr"


def test_run_command_passes_the_given_environment():
    code, output = commands.run_command( [ sys.executable, "-c", "import os; print( os.environ[ 'HARNESS_PROBE' ] )" ], env={ "HARNESS_PROBE" : "seen" } )
    assert ( code, output ) == ( 0, "seen" )


def test_run_command_reports_a_command_that_cannot_start_as_127():
    code, output = commands.run_command( [ "/no/such/binary" ] )
    assert code == 127 and "FileNotFoundError" in output




def test_run_command_runs_in_the_given_folder(tmp_path):
    code, output = commands.run_command( [ sys.executable, "-c", "import os; print( os.getcwd() )" ], cwd=str( tmp_path ) )
    assert ( code, output ) == ( 0, str( tmp_path.resolve() ) )


def test_run_command_reports_a_timeout_as_127_and_not_as_an_exception():
    code, output = commands.run_command( [ sys.executable, "-c", "import time; time.sleep( 5 )" ], timeout=0.2 )
    assert code == 127 and "TimeoutExpired" in output
