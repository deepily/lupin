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


def test_a_timeout_keeps_what_the_command_printed_before_it_was_cut_off():
    # the text is computed, because the error line echoes the command and would otherwise hold a literal
    code = "import sys, time\nprint( 'out-' + str( 6 * 7 ), flush=True )\nprint( 'err-' + str( 7 * 8 ), file=sys.stderr, flush=True )\ntime.sleep( 30 )"
    status, output = commands.run_command( [ sys.executable, "-c", code ], timeout=1.5 )
    assert status == 127 and output.startswith( "TimeoutExpired:" ) and "out-42" in output and "err-56" in output


def test_a_timeout_of_a_command_that_printed_nothing_is_only_the_error_line():
    status, output = commands.run_command( [ sys.executable, "-c", "import time; time.sleep( 30 )" ], timeout=0.5 )
    assert status == 127 and output.startswith( "TimeoutExpired:" ) and "\n" not in output
