#!/usr/bin/env python3
"""
Real-tmux proof of the self-re-spin FIRE-POINT one-shot guard (row 9e0678f6, WI-2).

Krishna's ruling: a detached, already-sleeping `/clear` injection cannot be
recalled by any Python that runs later, so the double-fire guard must sit WHERE
THE KEYSTROKES LAND — inside the injected command. build_guarded_clear_argv puts
`rm "$4"` before `send-keys`, so the FIRST fire consumes the one-shot token and a
SECOND fire (e.g. a stale injection waking after the seat already rehydrated)
finds the token gone and types nothing.

This mirrors Arnold's test_detached_injection_outlives_caller.py but asserts the
GUARD, not just the detach: the seam-injected unit suite proves the argv SHAPE;
this proves the shape actually consumes-then-types against a real tmux + real rm.

Venue: :7999-eligible / local — its own throwaway tmux session (never a fleet
seat), a tmp token, <2 min, no monopoly. Skipped when tmux is unavailable.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

import lupin_mcp.self_respin_core as sr


_DELAY = 1.5   # seconds the detached injector sleeps before firing

pytestmark = pytest.mark.skipif(
    shutil.which( "tmux" ) is None, reason="tmux not installed — fire-point guard proof needs a real tmux server"
)


def _tmux( *args, check=True ):
    return subprocess.run( [ "tmux", *args ], capture_output=True, text=True, check=check )


def _capture( session ):
    return _tmux( "capture-pane", "-t", session, "-p", check=False ).stdout


@pytest.fixture
def throwaway_pane():
    """A disposable tmux session running `cat`, so injected text echoes into the
    pane buffer where capture-pane can read it. Torn down unconditionally."""
    session = f"tiffany-firepoint-{os.getpid()}"
    _tmux( "new-session", "-d", "-s", session, "cat" )
    time.sleep( 0.3 )
    try:
        yield session
    finally:
        _tmux( "kill-session", "-t", session, check=False )


def _fire( session, token_path, marker ):
    """Spawn the guarded injector detached, exactly as production will."""
    argv = sr.build_guarded_clear_argv( session, token_path, _DELAY, text=marker )
    subprocess.Popen( argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )


def _wait_for( session, marker, extra=3.0 ):
    deadline = time.time() + _DELAY + extra
    while time.time() < deadline:
        if marker in _capture( session ):
            return True
        time.sleep( 0.15 )
    return False


def test_first_fire_consumes_token_and_types( throwaway_pane, tmp_path ):
    """CONTROL/positive arm — with the token present, the guarded fire types AND
    removes the token (the consume)."""
    token  = str( tmp_path / ".self-respin-fire-sid1.token" )
    open( token, "w" ).write( "x" )
    marker = f"FIRST_{os.getpid()}"

    _fire( throwaway_pane, token, marker )

    assert _wait_for( throwaway_pane, marker ), "first fire (token present) must type"
    assert not os.path.exists( token ), "first fire must CONSUME the token (rm) at the fire point"


def test_second_fire_after_consume_types_nothing( throwaway_pane, tmp_path ):
    """PROOF — once the token is gone, a second detached fire no-ops: `rm` fails,
    short-circuiting send-keys. This is the double-fire-after-rehydrate guard."""
    token  = str( tmp_path / ".self-respin-fire-sid1.token" )   # deliberately NOT created
    marker = f"SECOND_{os.getpid()}"
    assert not os.path.exists( token )

    _fire( throwaway_pane, token, marker )

    # Give it strictly longer than the happy path would need, then assert ABSENCE.
    assert not _wait_for( throwaway_pane, marker, extra=2.0 ), \
        "a fire with no token must type NOTHING — the fire-point guard failed"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
