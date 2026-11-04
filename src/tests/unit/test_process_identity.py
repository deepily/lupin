"""
`process_runs`: a pid read from a bridge file may be a reused number.

Real children are used for the live cases, and fabricated /proc entries for the argv shapes.
The no-/proc case points `proc_root` at a path that does not exist.
"""
import os
import subprocess
import sys
import time

from lupin_cli.claude_code.hooks.lib.process_identity import process_runs


def _settled( child, seconds=5 ):
    """
    Wait until the kernel shows the child's command line, then return the child.

    Popen returns as soon as the child has exec'd, and the command line is filled in a moment later.
    Read in between, `/proc/<pid>/cmdline` is empty, which `process_runs` correctly calls "not the program".
    Measured on this host: 17% of reads right after Popen were empty when idle, 23% under load.
    """
    path = f"/proc/{child.pid}/cmdline"
    if not os.path.isdir( "/proc" ): return child
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with open( path, "rb" ) as handle:
            if handle.read(): return child
        time.sleep( 0.001 )
    raise AssertionError( f"{path} stayed empty for {seconds} seconds" )


def _start( tmp_path, *arguments ):
    """A real child: `python -m identity_probe_module`, run in a folder holding that module."""
    ( tmp_path / "identity_probe_module.py" ).write_text( "import time\ntime.sleep( 30 )\n" )
    return _settled( subprocess.Popen( [ sys.executable, "-m", "identity_probe_module", *arguments ], cwd=str( tmp_path ) ) )


def _stop( child ):
    child.kill()
    child.wait( timeout=5 )


def test_a_real_process_started_with_dash_m_is_the_program( tmp_path ):

    child = _start( tmp_path )
    try:
        assert process_runs( child.pid, "identity_probe_module" ) is True
    finally:
        _stop( child )


def test_a_child_read_right_after_it_starts_is_the_program_every_time( tmp_path ):
    """Fifty starts; without the wait in `_start` about one in six reads an empty line."""
    for _ in range( 50 ):
        child = _start( tmp_path )
        try:
            assert process_runs( child.pid, "identity_probe_module" ) is True
        finally:
            _stop( child )


def test_a_live_process_that_is_another_program_is_not_the_program():
    """The positive control above has the same shape; this one is the reused-number case."""
    child = _settled( subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)" ] ) )
    try:
        assert process_runs( child.pid, "identity_probe_module" ) is False
    finally:
        _stop( child )


def test_a_pid_that_has_gone_is_not_the_program():

    child = subprocess.Popen( [ sys.executable, "-c", "pass" ] )
    child.wait( timeout=10 )
    assert process_runs( child.pid, "identity_probe_module" ) is False


def test_without_a_proc_filesystem_the_check_cannot_object( tmp_path ):

    assert process_runs( 1, "anything", proc_root=str( tmp_path / "no-such-proc" ) ) is True


def test_a_non_utf8_command_line_is_read_not_raised( tmp_path ):

    proc = tmp_path / "proc" / "77"
    proc.mkdir( parents=True )
    ( proc / "cmdline" ).write_bytes( b"python\0-m\0cc_notification_listener\0\xff\xfe\0" )
    assert process_runs( 77, "cc_notification_listener", proc_root=str( tmp_path / "proc" ) ) is True
    assert process_runs( 77, "other", proc_root=str( tmp_path / "proc" ) ) is False


def test_a_program_that_is_not_python_is_never_the_program( tmp_path ):
    """`vim -m cc_notification_listener` and similar share the arguments, not the program."""
    root = _fake_cmdline( tmp_path, 20, [ "vim", "-m", "cc_notification_listener" ] )
    assert process_runs( 20, "cc_notification_listener", proc_root=root ) is False


def test_an_interpreter_option_with_a_value_does_not_become_the_script( tmp_path ):

    root = _fake_cmdline( tmp_path, 21, [ "python3", "-W", "ignore", "-X", "dev", "-m", "pkg.cc_notification_listener" ] )
    assert process_runs( 21, "cc_notification_listener", proc_root=root ) is True


def test_a_plain_option_before_the_script_is_skipped( tmp_path ):

    root = _fake_cmdline( tmp_path, 22, [ "python3", "-u", "/x/cc_notification_listener.py" ] )
    assert process_runs( 22, "cc_notification_listener", proc_root=root ) is True


def test_only_options_and_no_program_is_not_the_program( tmp_path ):

    root = _fake_cmdline( tmp_path, 23, [ "python3", "-u", "-B" ] )
    assert process_runs( 23, "cc_notification_listener", proc_root=root ) is False


def _fake_cmdline( tmp_path, pid, argv ):
    proc = tmp_path / "proc" / str( pid )
    proc.mkdir( parents=True )
    ( proc / "cmdline" ).write_bytes( b"\0".join( part.encode() for part in argv ) + b"\0" )
    return str( tmp_path / "proc" )


def test_the_name_as_only_an_argument_of_another_program_is_not_the_program( tmp_path ):
    """A reused pid running a test file on the listener must not read as the listener."""
    root = _fake_cmdline( tmp_path, 10, [ "python", "-c", "import time", "tests/test_cc_notification_listener.py" ] )
    assert process_runs( 10, "cc_notification_listener", proc_root=root ) is False


def test_pytest_naming_the_listener_test_is_not_the_listener( tmp_path ):

    root = _fake_cmdline( tmp_path, 11, [ "pytest", "src/tests/unit/test_cc_notification_listener.py" ] )
    assert process_runs( 11, "cc_notification_listener", proc_root=root ) is False


def test_dash_m_followed_by_the_module_is_the_program( tmp_path ):

    root = _fake_cmdline( tmp_path, 12, [
        "/usr/bin/python3", "-m", "lupin_cli.claude_code.hooks.lib.cc_notification_listener", "--session-id", "abc12345",
    ] )
    assert process_runs( 12, "cc_notification_listener", proc_root=root ) is True


def test_the_full_dotted_module_matches_exactly( tmp_path ):

    module = "lupin_cli.claude_code.hooks.lib.idle_waiter"
    root   = _fake_cmdline( tmp_path, 13, [ "python", "-m", module, "--cc-pid", "7" ] )
    assert process_runs( 13, module, proc_root=root ) is True
    assert process_runs( 13, "other.idle_waiter", proc_root=root ) is False


def test_a_module_that_only_ends_with_the_name_is_not_the_program( tmp_path ):
    """`my_cc_notification_listener` is another module: the match is the whole last component."""
    root = _fake_cmdline( tmp_path, 14, [ "python", "-m", "pkg.my_cc_notification_listener" ] )
    assert process_runs( 14, "cc_notification_listener", proc_root=root ) is False


def test_dash_m_after_dash_c_is_an_argument_not_the_program( tmp_path ):

    root = _fake_cmdline( tmp_path, 15, [ "python", "-c", "pass", "-m", "cc_notification_listener" ] )
    assert process_runs( 15, "cc_notification_listener", proc_root=root ) is False


def test_the_script_form_is_the_program_only_for_a_python_interpreter( tmp_path ):

    first  = _fake_cmdline( tmp_path, 16, [ "python3", "/x/lib/cc_notification_listener.py", "--session-id", "a" ] )
    assert process_runs( 16, "cc_notification_listener", proc_root=first ) is True
    second = _fake_cmdline( tmp_path, 17, [ "vim", "/x/lib/cc_notification_listener.py" ] )
    assert process_runs( 17, "cc_notification_listener", proc_root=second ) is False


def test_a_dash_m_with_nothing_after_it_is_not_the_program( tmp_path ):

    root = _fake_cmdline( tmp_path, 18, [ "python", "-m" ] )
    assert process_runs( 18, "cc_notification_listener", proc_root=root ) is False


def test_a_process_with_an_empty_command_line_is_not_the_program( tmp_path ):
    """A zombie reads as an empty command line."""
    proc = tmp_path / "proc" / "19"
    proc.mkdir( parents=True )
    ( proc / "cmdline" ).write_bytes( b"" )
    assert process_runs( 19, "cc_notification_listener", proc_root=str( tmp_path / "proc" ) ) is False
