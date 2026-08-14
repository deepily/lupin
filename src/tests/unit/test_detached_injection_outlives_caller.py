#!/usr/bin/env python3
"""
The load-bearing mechanism proof for manager self-re-spin (store row 9e0678f6).

Self-re-spin has ONE assumption everything else rests on: the process that types
"/clear" into a pane is DETACHED (subprocess.Popen(..., start_new_session=True))
and sleeps first, so it OUTLIVES the caller that spawned it. In production the
caller is a session that then zeroes its own context; the type still lands. This
test proves that property against real tmux, without touching any live fleet seat.

It mirrors the exact Popen shape shipped at
    lupin/src/lupin_cli/claude_code/hooks/lib/hook_common.py:1061-1072
(a bash -c 'sleep $1 && tmux send-keys -l -- $3 && Enter', start_new_session=True).

Why not in the seam-injected unit suite: this asserts the REAL detach behaviour of
the OS + tmux, which a fake Popen cannot vouch for. The verb's branch/line coverage
lives in the seam-injected suite; this is the whole-chain "does it actually run".

Venue: :7999-eligible / local — creates its OWN throwaway tmux session (never a
fleet seat), kills only that, no persistent state outlives the test, <2 min, no
monopoly. Skipped entirely when tmux is unavailable.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

# The production injector's exact background command (kept verbatim so a drift in
# the real Popen shape would make this proof stale, not silently wrong).
_INJECT_BASH = 'sleep "$1" && tmux send-keys -t "$2" -l -- "$3" && sleep 0.25 && tmux send-keys -t "$2" Enter'

_DELAY = 2.0  # seconds the detached injector sleeps before typing

pytestmark = pytest.mark.skipif(
    shutil.which( "tmux" ) is None, reason="tmux not installed — mechanism proof needs a real tmux server"
)


def _tmux( *args, check=True ):
    """Run a tmux subcommand; capture text output."""
    return subprocess.run( [ "tmux", *args ], capture_output=True, text=True, check=check )


def _pid_alive( pid ):
    """
    Requires:
        - pid is an int

    Ensures:
        - Returns True iff a process with that pid currently exists
    """
    try:
        os.kill( pid, 0 )
        return True
    except (ProcessLookupError, OSError):
        return False


def _spawn_detached_injector_then_exit( session, marker ):
    """
    Run a SHORT-LIVED caller process that spawns the detached injector exactly as
    production does, records its own pid, and exits. When this returns, the caller
    process is gone but the injector (still in its leading sleep) is not.

    Requires:
        - session is a live tmux session name
        - marker is the literal text to inject

    Ensures:
        - Returns ( caller_pid, caller_returncode )
        - The detached injector has been spawned but has NOT yet typed
    """
    pidfile = f"/tmp/arnold_caller_pid_{os.getpid()}_{marker}"
    code = (
        "import subprocess,os,sys\n"
        "sess,marker,delay,pidfile,bash = sys.argv[1:6]\n"
        "subprocess.Popen(['bash','-c',bash,'_',delay,sess,marker],\n"
        "  start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "open(pidfile,'w').write(str(os.getpid()))\n"
    )
    caller = subprocess.run(
        [ sys.executable, "-c", code, session, marker, str( _DELAY ), pidfile, _INJECT_BASH ],
        capture_output=True, text=True
    )
    caller_pid = int( open( pidfile ).read().strip() )
    os.remove( pidfile )
    return caller_pid, caller.returncode


@pytest.fixture
def throwaway_pane():
    """
    A disposable tmux session running `cat`, so injected text echoes into the pane
    buffer where capture-pane can read it. Torn down unconditionally.
    """
    session = f"arnold-respin-proof-{os.getpid()}"
    _tmux( "new-session", "-d", "-s", session, "cat" )
    time.sleep( 0.3 )
    try:
        yield session
    finally:
        _tmux( "kill-session", "-t", session, check=False )


def _capture( session ):
    return _tmux( "capture-pane", "-t", session, "-p", check=False ).stdout


def test_control_pristine_pane_lacks_marker( throwaway_pane ):
    """CONTROL — with no injection, the marker is ABSENT. Proves the capture
    reflects real injection rather than a false positive (the instrument works)."""
    marker = f"CTRL_MARKER_{os.getpid()}"
    assert marker not in _capture( throwaway_pane )


def test_detached_injection_lands_after_caller_death( throwaway_pane ):
    """PROOF — the detached injector types into the pane AFTER its caller has
    exited: the exact property self-re-spin depends on."""
    marker = f"PROOF_MARKER_{os.getpid()}"

    caller_pid, caller_rc = _spawn_detached_injector_then_exit( throwaway_pane, marker )

    # The caller process has returned → it is dead. The injector is mid-sleep.
    assert caller_rc == 0
    assert not _pid_alive( caller_pid ), "caller must be dead before the injection fires"

    # And the type has NOT happened yet — it fires strictly after the caller death.
    assert marker not in _capture( throwaway_pane ), "injection must still be pending during the detached sleep"

    # Wait past the injector's sleep + its trailing 0.25s + margin.
    deadline = time.time() + _DELAY + 3.0
    landed = False
    while time.time() < deadline:
        if marker in _capture( throwaway_pane ):
            landed = True
            break
        time.sleep( 0.2 )

    assert landed, "detached injection failed to land though its caller was gone"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
