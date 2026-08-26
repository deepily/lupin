"""
The MCP server's hard exit must say why on the way out.

Row `87ae7234`. `_die_no_session_id()` ends in `os._exit( 1 )`, which skips every
flush, atexit hook and exception path. Its `logger.critical` is captured by pytest
and lost with the process, so a test that trips this path used to kill the whole
run with no traceback, no summary and nothing anywhere naming the cause — measured:
`EXIT=1` after 17 of 333 tests, output ending mid-line.

The exit itself is correct and is NOT changed here. What is asserted is that it
identifies itself on an explicitly-flushed stderr first.

⚠️ WHAT THIS DOES NOT FIX, measured rather than assumed. Under pytest's DEFAULT
fd-level capture the bytes land in a capture file pytest never reads back after
`os._exit`, so the line still does not surface: same directory, suppressed daemon,
`--capture=fd` -> 0 marker hits, `-s` -> 1. The line reaches a reader in the real
MCP-server process and in any run with `-s`/`--capture=no`; a default-captured
suite still dies quietly. The durable remedy is the structural control (row
`87ae7234` Q3), not this write.
"""
import os
import subprocess
import sys

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
SRC        = os.path.join( LUPIN_ROOT, "src" )
MARKER     = "[cosa-voice] FATAL"


def _run( body ):
    """Run `body` in a fresh interpreter; return (returncode, stderr)."""
    env = dict( os.environ )
    env[ "PYTHONPATH" ] = SRC + os.pathsep + env.get( "PYTHONPATH", "" )
    proc = subprocess.run(
        [ sys.executable, "-c", body ], capture_output=True, text=True, timeout=90, env=env
    )
    return proc.returncode, proc.stderr


class TestTheHardExitNamesItself:

    def test_die_no_session_id_writes_a_named_reason_to_stderr_before_exiting( self ):
        """The positive case: the exit is still a hard exit, and it says why."""
        rc, err = _run(
            "import lupin_mcp.cosa_voice_mcp as m\n"
            "m._die_no_session_id()\n"
        )

        assert rc == 1, f"expected the hard exit to keep its exit code, got {rc}"
        assert MARKER in err, (
            "the hard exit produced no named reason on stderr - a caller that "
            f"imports this module dies silently again. stderr was: {err!r}"
        )
        assert "_die_no_session_id" in err, "the reason should name the function it came from"
        assert "the suite did not finish" in err, (
            "the reason should tell a test reader that the run was truncated, "
            "since pytest cannot report it itself"
        )

    def test_importing_the_module_alone_emits_no_fatal_line( self ):
        """
        NEGATIVE CONTROL. Without this, a marker written unconditionally at import
        would satisfy the test above while telling the reader nothing. Importing the
        module starts the watcher daemon and must stay quiet on this channel.
        """
        rc, err = _run(
            "import lupin_mcp.cosa_voice_mcp\n"
            "import time; time.sleep( 0.2 )\n"
        )

        assert rc == 0, f"a bare import should not exit non-zero; stderr was: {err!r}"
        assert MARKER not in err, (
            f"the fatal line was emitted on a path that did not die: {err!r}"
        )
