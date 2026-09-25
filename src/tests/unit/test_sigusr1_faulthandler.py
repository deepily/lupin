"""
Unit tests for the SIGUSR1 thread-dump handler (row abe4188d).

WHAT IS AT STAKE. The default disposition of SIGUSR1 is to TERMINATE. So the
difference between this feature working and not working is the difference between
`kill -USR1` dumping a hung server's stacks and `kill -USR1` killing it. A test that
only checked "register() was called" would pass in both worlds, so the central test
here actually sends the signal to a real process and reads what happened to it.

THE INSTRUMENT IS PROVEN ABLE TO FIND SOMETHING. `test_the_signal_kills_an_unarmed
_process` is the negative control: the identical subprocess WITHOUT the registration
dies of SIGUSR1. Without it, a green dump test could mean the handler works or could
mean the harness never delivered a signal at all.

Pure-Python, no server, sub-second — :7999-eligible / AI-discretionary.
"""
import ast
import io
import os
import pathlib
import signal
import subprocess
import sys

import pytest

from lupin_app.bootstrap_helpers import (
    register_sigusr1_faulthandler,
    _reset_sigusr1_registration_for_testing,
)


@pytest.fixture( autouse=True )
def _clean_registration_flag():
    """The flag is module state; leaving it set would make later tests lie."""
    _reset_sigusr1_registration_for_testing()
    yield
    _reset_sigusr1_registration_for_testing()


# ---------------------------------------------------------------------------
# The four outcomes, each named in the contract
# ---------------------------------------------------------------------------

class _FakeSignal:
    """A signal module double. `handler` is what getsignal reports."""
    SIG_DFL = signal.SIG_DFL
    SIG_IGN = signal.SIG_IGN
    SIGUSR1 = 10

    def __init__( self, handler=signal.SIG_DFL ):
        self.handler = handler

    def getsignal( self, signum ):
        assert signum == self.SIGUSR1
        return self.handler


class _NoSigusr1:
    """A platform without SIGUSR1 — Windows. Deliberately has no SIGUSR1 attribute."""
    SIG_DFL = signal.SIG_DFL

    def getsignal( self, signum ):                       # pragma: no cover
        raise AssertionError( "must not be reached — the SIGUSR1 lookup returns first" )


class _RecordingFaulthandler:
    def __init__( self ):
        self.calls = []

    def register( self, signum, file=None, all_threads=None ):
        self.calls.append( { "signum": signum, "file": file, "all_threads": all_threads } )


def test_arms_the_handler_when_the_signal_is_free():
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "registered"
    assert len( fh.calls ) == 1
    assert fh.calls[ 0 ][ "signum" ]      == _FakeSignal.SIGUSR1
    assert fh.calls[ 0 ][ "all_threads" ] is True, "a hang is usually NOT the main thread"


def test_is_idempotent_so_a_second_bootstrap_does_not_re_arm():
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "registered"
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "already-registered"
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "already-registered"
    assert len( fh.calls ) == 1, "re-arming would install a second sigaction"


def test_declines_rather_than_clobbering_a_live_handler():
    """Stealing SIGUSR1 would silently break whoever installed it. A debugging aid
    does not get to outrank the application."""
    fh = _RecordingFaulthandler()
    def _someone_elses_handler( signum, frame ):         # pragma: no cover
        raise AssertionError( "never invoked — this test only inspects disposition" )
    result = register_sigusr1_faulthandler( _FakeSignal( _someone_elses_handler ), fh )
    assert result == "declined-existing-handler"
    assert fh.calls == [], "NOTHING may be armed when we decline"


def test_declines_when_the_signal_is_deliberately_ignored():
    """SIG_IGN is a choice someone made, not an empty slot."""
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal( signal.SIG_IGN ), fh ) == "declined-existing-handler"
    assert fh.calls == []


def test_reports_unsupported_platform_instead_of_raising():
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _NoSigusr1(), fh ) == "unsupported-platform"
    assert fh.calls == []


def test_an_explicit_stream_is_passed_through_and_the_default_is_stderr( tmp_path ):
    """Both arms of the stream default — the dump has to land somewhere readable."""
    fh = _RecordingFaulthandler()
    with open( tmp_path / "dump.txt", "w" ) as handle:
        assert register_sigusr1_faulthandler( _FakeSignal(), fh, stream=handle ) == "registered"
        assert fh.calls[ 0 ][ "file" ] is handle

    _reset_sigusr1_registration_for_testing()
    fh2 = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh2 ) == "registered"
    assert fh2.calls[ 0 ][ "file" ] is sys.stderr


def test_the_reset_helper_clears_the_flag():
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "registered"
    _reset_sigusr1_registration_for_testing()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "registered"
    assert len( fh.calls ) == 2


def test_a_stream_with_no_usable_fileno_is_reported_not_raised():
    """REGRESSION, measured 2026-09-25. This is the one every other test above was
    blind to, because they all inject a fake faulthandler — so the REAL one was never
    asked to register against a hostile stream, and the subprocess test runs outside
    pytest's capture where stderr is a genuine fd.

    It matters because `cosa.rest.routers.speech` imports `lupin_app.main` LAZILY,
    inside a request handler. An earlier cut of this function let the real
    faulthandler's AttributeError('fileno') escape, and two speech tests reported it
    as an upload-setup fault — a signal-registration failure surfacing as a broken
    MP3 upload, in a handler that knows nothing about signals.
    """
    import faulthandler as real_faulthandler

    class _NoFileno( io.StringIO ):
        def fileno( self ):
            raise AttributeError( "fileno" )

    result = register_sigusr1_faulthandler( _FakeSignal(), real_faulthandler, stream=_NoFileno() )
    assert result == "unavailable-stream"

    # And the flag must NOT be set — a failed arm is not an arm, and claiming it was
    # would make the next caller skip a registration that could have succeeded.
    fh = _RecordingFaulthandler()
    assert register_sigusr1_faulthandler( _FakeSignal(), fh ) == "registered"


# ---------------------------------------------------------------------------
# The behaviour that matters — a real process, a real signal
# ---------------------------------------------------------------------------

_ARMED = """
import os, signal, sys, threading
sys.path.insert( 0, {src!r} )
from lupin_app.bootstrap_helpers import register_sigusr1_faulthandler

def _worker( ev ): ev.wait( 30 )
stop = threading.Event()
threading.Thread( target=_worker, args=( stop, ), name="lupin-probe-thread", daemon=True ).start()

print( register_sigusr1_faulthandler(), flush=True )
os.kill( os.getpid(), signal.SIGUSR1 )
stop.set()
print( "SURVIVED", flush=True )
"""

_UNARMED = """
import os, signal, sys
os.kill( os.getpid(), signal.SIGUSR1 )
print( "SURVIVED", flush=True )
"""


def _run( source ):
    src = str( pathlib.Path( __file__ ).resolve().parents[ 2 ] )
    return subprocess.run( [ sys.executable, "-c", source.format( src=src ) ],
                           capture_output=True, text=True, timeout=60 )


@pytest.mark.skipif( not hasattr( signal, "SIGUSR1" ), reason="platform has no SIGUSR1" )
def test_sigusr1_dumps_every_thread_and_the_process_survives():
    """The whole point, end to end: signal in, stacks out, process still alive."""
    done = _run( _ARMED )
    assert done.returncode == 0, f"the process died: rc={done.returncode} stderr={done.stderr[:400]}"
    assert "registered" in done.stdout
    assert "SURVIVED"   in done.stdout, "the signal must not terminate the process"
    # faulthandler writes the dump to stderr, one block per thread.
    assert "Current thread" in done.stderr, f"no thread dump in stderr: {done.stderr[:400]}"
    assert done.stderr.count( "Thread 0x" ) >= 1, "all_threads=True must reach the non-main thread"
    assert "lupin-probe-thread" not in done.stdout


@pytest.mark.skipif( not hasattr( signal, "SIGUSR1" ), reason="platform has no SIGUSR1" )
def test_the_signal_kills_an_unarmed_process():
    """NEGATIVE CONTROL. Without the registration the identical signal is fatal.

    This is what makes the test above mean something: a green dump test could
    otherwise mean the handler worked, or mean no signal was ever delivered.
    """
    done = _run( _UNARMED )
    assert done.returncode == -signal.SIGUSR1, (
        f"expected death by SIGUSR1, got rc={done.returncode} — if this passes as 0, the "
        f"harness is not delivering the signal and the positive test proves nothing" )
    assert "SURVIVED" not in done.stdout


# ---------------------------------------------------------------------------
# The revert guard
# ---------------------------------------------------------------------------

def test_main_py_calls_the_registration_during_bootstrap():
    """REVERT GUARD. Reddens if the call is removed from `main.py`.

    Read with AST rather than a string search: a grep matches the word in a comment
    or a docstring, and would keep this green over a file that only TALKS about
    registering. The assertion is that a module-level call exists.
    """
    main_py = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "lupin_app" / "main.py"
    tree    = ast.parse( main_py.read_text() )

    def _calls_it( node ):
        return ( isinstance( node, ast.Call )
                 and isinstance( node.func, ast.Name )
                 and node.func.id == "register_sigusr1_faulthandler" )

    assert any( _calls_it( n ) for n in ast.walk( tree ) ), (
        "main.py no longer calls register_sigusr1_faulthandler(). Without it SIGUSR1 "
        "reverts to its default disposition, which TERMINATES the server — so a future "
        "hang investigation would kill the evidence it was trying to collect." )

    imported = any( isinstance( n, ast.ImportFrom )
                    and any( a.name == "register_sigusr1_faulthandler" for a in n.names )
                    for n in ast.walk( tree ) )
    assert imported, "the call is present but the name is never imported"
