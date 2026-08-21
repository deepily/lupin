#!/usr/bin/env python3
"""
Row 08919110 — bounce-dev-server.sh must REFUSE a bounce when a job is running on :7999,
not merely warn (Rick lost a podcast job to a pending bounce). This drives all three arms
the row requires by stubbing bounce_busy_probe.py to each exit code and asserting the
script's behaviour DIFFERS:

    probe 0  (idle)        → the script proceeds and bounces
    probe 10 (busy)        → the script REFUSES (exit 4) before it warns or restarts
    probe 10 (busy)+--force→ the script proceeds anyway (the deliberate override)
    probe 20 (unreachable) → the script FAILS OPEN and proceeds (never block recovery)

No real bounce happens: LUPIN_ROOT points at a temp tree holding a FAKE bounce_busy_probe.py
(exits a chosen code) and a FAKE bounce_dev_warn.py (exit 0), with fake docker/curl on PATH
so the restart + health poll succeed instantly. A check whose idle and busy paths cannot
diverge is not a check — test_idle_and_busy_paths_diverge nails that down.
"""
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

import cosa.utils.util as cu

_SCRIPT     = cu.get_project_root() + "/src/scripts/bounce-dev-server.sh"
_REAL_PROBE = cu.get_project_root() + "/src/scripts/bounce_busy_probe.py"


def _free_port():
    """A port guaranteed free RIGHT NOW: bind to 0 (OS assigns), read it, release it.

    A hardcoded 'dead' port is only dead until something else takes it, and then the
    real-probe fail-open arm would silently reach a live socket instead of nothing
    (Maria's caution). Binding port 0 and closing hands back a port nobody is on."""
    s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    s.bind( ( "127.0.0.1", 0 ) )
    port = s.getsockname()[ 1 ]
    s.close()
    return port


def _run( busy_rc=None, warn_rc=0, extra_args=(), pause_secs="0", real_probe_url=None ):
    """Run the REAL bounce script with the warn helper stubbed.

    busy-probe modes:
      · real_probe_url is None → a FAKE probe that exits FAKE_BUSY_RC (busy_rc), for the
        stubbed arms that assert the script's response to each code;
      · real_probe_url set → the ACTUAL bounce_busy_probe.py, pointed at that URL, so the
        probe's OWN exit code drives the script (couples the two sides end-to-end).

    Returns the CompletedProcess (stdout carries the verbose `log` lines; stderr carries
    the REFUSED message)."""
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    # Busy probe: the REAL helper (coupling arm) or a fake that exits the asked-for code.
    if real_probe_url is not None:
        shutil.copy( _REAL_PROBE, scripts / "bounce_busy_probe.py" )
    else:
        ( scripts / "bounce_busy_probe.py" ).write_text(
            "import os, sys\nsys.exit( int( os.environ[ 'FAKE_BUSY_RC' ] ) )\n"
        )
    ( scripts / "bounce_dev_warn.py" ).write_text(
        "import os, sys\nsys.exit( int( os.environ[ 'FAKE_WARN_RC' ] ) )\n"
    )
    # Fake docker + curl so `docker restart` and the health poll succeed at once.
    #
    # docker CANNOT be a bare `exit 0` any more. Since 2026-08-21 the script also waits for
    # the container's own StartedAt to be newer than the restart it issued (the identity
    # guard, row 1c36199e) — a bare stub prints nothing, the wait can never be satisfied,
    # and every arm below fails for a reason that has nothing to do with the busy guard.
    # So the stub answers `inspect` with a start time of NOW, which is what a real restart
    # would report, and keeps exiting 0 for `restart` and `logs`.
    fakebin = Path( tmp ) / "bin"
    fakebin.mkdir()
    ( fakebin / "docker" ).write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"inspect\" ]; then date -u +%Y-%m-%dT%H:%M:%S.000000000Z; fi\n"
        "exit 0\n"
    )
    ( fakebin / "docker" ).chmod( 0o755 )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    ( fakebin / "curl" ).chmod( 0o755 )

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]          = tmp
    env[ "PATH" ]                = str( fakebin ) + os.pathsep + env[ "PATH" ]
    env[ "FAKE_WARN_RC" ]        = str( warn_rc )
    env[ "UNWARNED_PAUSE_SECS" ] = pause_secs
    if real_probe_url is not None:
        env[ "BOUNCE_BUSY_URL" ] = real_probe_url   # the real probe reads this
    else:
        env[ "FAKE_BUSY_RC" ]    = str( busy_rc )
    return subprocess.run(
        [ "bash", _SCRIPT, *extra_args ],
        env=env, capture_output=True, text=True, timeout=30,
    )


class TestBounceBusyGuard( unittest.TestCase ):

    def test_idle_probe_proceeds_to_the_bounce( self ):
        r = _run( busy_rc=0 )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "No job running", r.stdout )
        self.assertIn( "Restarting container", r.stdout )   # got past the guard

    def test_busy_probe_refuses_before_warning_or_restarting( self ):
        r = _run( busy_rc=10 )
        self.assertEqual( r.returncode, 4 )                 # the refusal exit
        self.assertIn( "REFUSED", r.stderr )
        # It must stop BEFORE the warn broadcast and the restart, or the refusal is cosmetic.
        self.assertNotIn( "Warning the fleet", r.stdout )
        self.assertNotIn( "Restarting container", r.stdout )

    def test_busy_probe_with_force_proceeds_and_says_it_is_destroying_the_job( self ):
        r = _run( busy_rc=10, extra_args=( "--force", ) )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "DESTROYING", r.stdout )
        self.assertIn( "Restarting container", r.stdout )

    def test_unreachable_probe_fails_open_and_proceeds( self ):
        r = _run( busy_rc=20 )
        self.assertEqual( r.returncode, 0 )                 # a broken probe never blocks recovery
        self.assertIn( "failing OPEN", r.stdout )
        self.assertIn( "Restarting container", r.stdout )

    def test_idle_and_busy_paths_diverge( self ):
        """The crux: the two probe outcomes must NOT produce the same result."""
        idle = _run( busy_rc=0 )
        busy = _run( busy_rc=10 )
        self.assertNotEqual( idle.returncode, busy.returncode )
        self.assertEqual( idle.returncode, 0 )
        self.assertEqual( busy.returncode, 4 )

    def test_real_probe_against_a_free_port_fails_open_end_to_end( self ):
        # The coupling arm Maria demanded: NO stub. The ACTUAL bounce_busy_probe.py hits a
        # port that was bound-then-released (guaranteed free right now), returns its OWN
        # unreachable code, and the script must FAIL OPEN on it. Maria's mutation 2
        # (EXIT_UNREACHABLE -> 10) makes the real probe return the REFUSE code here, so the
        # script would exit 4 and redden this — the gap the stubbed arms and the
        # symbol-relative probe asserts could not catch.
        url = f"http://127.0.0.1:{_free_port()}/api/busy"
        r   = _run( real_probe_url=url )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "failing OPEN", r.stdout )
        self.assertIn( "Restarting container", r.stdout )


if __name__ == "__main__":
    unittest.main()
