"""
The MCP server's hard exit must say why on the way out.

Row `87ae7234`. `_die_no_session_id()` ends in `os._exit( 1 )`, which skips every
flush, atexit hook and exception path. Its `logger.critical` is captured by pytest
and lost with the process, so a test that trips this path used to kill the whole
run with no traceback, no summary and nothing anywhere naming the cause — measured:
`EXIT=1` after 17 of 333 tests, output ending mid-line.

The exit itself is correct FOR THE SERVER and still happens. **CHANGED 2026-08-26**:
it is now gated on `_IS_MCP_SERVER`, the positive discriminator set at the single
`if __name__ == "__main__":` entry point. An importing process gets a named
`SessionIdUnavailable` instead of losing its host to `os._exit`. The server arm below
therefore sets the flag exactly as the entry point does — that is not the test
working around the change, it is the test standing where the server stands.

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


# 🔴 THE NOTIFIER IS NEUTERED IN THE CHILD, AND THIS IS RICK'S P0 (row f6a43e37).
#
# `_die_no_session_id` sends a HIGH-priority alert to the OPERATOR before it exits.
# Every snippet in this file calls that function for real, in a real interpreter, so
# until 2026-09-03 running this one file put TWO genuine alerts on Rick's screen —
# and the whole unit tier put them there every time any seat ran it.
#
# MEASURED, and this is the receipt rather than a deduction: with the notifications
# table counted either side of a single `pytest test_hard_exit_names_itself.py`, the
# delta was EXACTLY 2. That is the ~2-second pair he was seeing all evening; five
# pairs in fourteen minutes was five tier runs, not five failures.
#
# ⚠️ THE RETRY GUARD DOES NOT COVER THIS PATH, deliberately said out loud. The retry
# added to `_wait_for_sender_id` sits in front of the alert for a caller that goes
# through the GATE; these snippets call `_die_no_session_id` DIRECTLY, which is the
# right thing for a test about the exit to do. Fixing the gate would have left the
# storm running.
#
# The stub goes in the SHARED helper rather than in each snippet, because a rule that
# every future snippet must remember is not a control — the next test added to this
# file would page him again.
_SILENCE_THE_OPERATOR = (
    "import lupin_mcp.cosa_voice_mcp as _m\n"
    "_m.notify_user_async = lambda *a, **k: None\n"
)


def _run( body, silence_operator=True ):
    """
    Run `body` in a fresh interpreter; return (returncode, stderr).

    Requires:
        - `body` imports what it needs; it is prefixed, not wrapped

    Ensures:
        - the child's operator alert is neutered unless a caller explicitly opts out,
          so exercising the hard exit cannot put a real alert on a human's screen
        - returns the child's (returncode, stderr) unchanged
    """
    env = dict( os.environ )
    env[ "PYTHONPATH" ] = SRC + os.pathsep + env.get( "PYTHONPATH", "" )
    prefix = _SILENCE_THE_OPERATOR if silence_operator else ""
    proc = subprocess.run(
        [ sys.executable, "-c", prefix + body ], capture_output=True, text=True, timeout=90, env=env
    )
    return proc.returncode, proc.stderr


class TestTheHardExitNamesItself:

    def test_die_no_session_id_writes_a_named_reason_to_stderr_before_exiting( self ):
        """
        The SERVER case: the exit is still a hard exit, and it says why.

        `_IS_MCP_SERVER = True` is what the `if __name__ == "__main__":` block does
        before `mcp.run()`. Setting it here puts this test in the server's position;
        without it we would be testing the importer's path and calling it the
        server's.
        """
        rc, err = _run(
            "import lupin_mcp.cosa_voice_mcp as m\n"
            "m._IS_MCP_SERVER = True\n"
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


class TestTheImporterIsNotKilled:
    """
    The other half of the same change. A library that calls `os._exit` takes its host
    down with no traceback — which is how a suite came to report a truncated run with
    nothing naming the cause. An importer must get an exception it can see and catch.
    """

    def test_an_importing_process_gets_a_named_exception_not_a_hard_exit( self ):
        rc, err = _run(
            "import lupin_mcp.cosa_voice_mcp as m\n"
            "try:\n"
            "    m._die_no_session_id()\n"
            "except m.SessionIdUnavailable as e:\n"
            "    print( 'CAUGHT', e )\n"
            "    raise SystemExit( 7 )\n"
            "raise SystemExit( 99 )\n"
        )

        assert rc == 7, (
            f"the importer should have caught SessionIdUnavailable and exited 7; got {rc}. "
            f"rc=99 means it returned normally; rc=1 means it still hard-exited. stderr: {err!r}"
        )
        assert MARKER not in err, (
            "the server's FATAL line must not be written on the importer's path - "
            f"it announces a process death that did not happen. stderr: {err!r}"
        )

    def test_the_flag_defaults_to_false_so_the_safe_path_is_the_default( self ):
        """
        A discriminator that defaults to the DANGEROUS value is not a control. The
        module must read False on import, and only the entry point may set it True.
        """
        rc, err = _run(
            "import lupin_mcp.cosa_voice_mcp as m\n"
            "assert m._IS_MCP_SERVER is False, m._IS_MCP_SERVER\n"
            "raise SystemExit( 5 )\n"
        )

        assert rc == 5, f"_IS_MCP_SERVER was not False on a bare import; stderr: {err!r}"
