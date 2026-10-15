"""
`process_runs`: a pid read from a bridge file may be a reused number.

Real /proc entries are used: a child started with the marker in its argv.
The no-/proc case points `proc_root` at a path that does not exist.
"""
import subprocess
import sys

from lupin_cli.claude_code.hooks.lib.process_identity import process_runs


def test_a_process_with_the_marker_in_its_command_line_is_the_program():

    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)", "marker_for_identity" ] )
    try:
        assert process_runs( child.pid, "marker_for_identity" ) is True
    finally:
        child.kill()
        child.wait( timeout=5 )


def test_a_live_process_without_the_marker_is_not_the_program():
    """The positive control above names the same pid shape; this one is the reused-number case."""
    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)" ] )
    try:
        assert process_runs( child.pid, "marker_for_identity" ) is False
    finally:
        child.kill()
        child.wait( timeout=5 )


def test_a_pid_that_has_gone_is_not_the_program():

    child = subprocess.Popen( [ sys.executable, "-c", "pass", "marker_for_identity" ] )
    child.wait( timeout=10 )
    assert process_runs( child.pid, "marker_for_identity" ) is False


def test_without_a_proc_filesystem_the_check_cannot_object( tmp_path ):

    assert process_runs( 1, "anything", proc_root=str( tmp_path / "no-such-proc" ) ) is True


def test_a_non_utf8_command_line_is_read_not_raised( tmp_path ):

    proc = tmp_path / "proc" / "77"
    proc.mkdir( parents=True )
    ( proc / "cmdline" ).write_bytes( b"python\0\xff\xfe\0cc_notification_listener\0" )
    assert process_runs( 77, "cc_notification_listener", proc_root=str( tmp_path / "proc" ) ) is True
    assert process_runs( 77, "other", proc_root=str( tmp_path / "proc" ) ) is False
