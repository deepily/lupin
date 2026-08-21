"""
Row 32e659f1 — bounce-dev-server.sh must not collapse the warn helper's exit 1
(PARTIAL reach: the fleet WAS warned) into exit 2 (FAILED: nobody was warned).

The script used to log one sentence — "partial reach or server unreachable" — and
behave identically for both, so a bounce nobody was warned about read the same as a
bounce most of the fleet acked. This drives BOTH arms (the gate the row demands: a
branch nobody has run down both sides is unverified) by stubbing the warn helper to
exit each code and asserting the script's behaviour differs.

No real bounce happens: LUPIN_ROOT points at a temp tree holding a FAKE
bounce_dev_warn.py that exits a chosen code, and fake `docker`/`curl` on PATH make
the restart + health poll succeed instantly. UNWARNED_PAUSE_SECS=0 keeps the
unwarned-fleet pause from actually sleeping except where the pause itself is asserted.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import cosa.utils.util as cu

_SCRIPT = cu.get_project_root() + "/src/scripts/bounce-dev-server.sh"


def _run( warn_rc, extra_args=(), pause_secs="0" ):
    """Run the REAL bounce script with a stubbed warn helper + fake docker/curl.

    Returns the CompletedProcess (stdout carries the verbose `log` lines)."""
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    # Fake warn helper: exit the code the test asked for.
    ( scripts / "bounce_dev_warn.py" ).write_text(
        "import os, sys\nsys.exit( int( os.environ[ 'FAKE_WARN_RC' ] ) )\n"
    )
    # Busy probe: IDLE. The script runs "${LUPIN_ROOT}/src/scripts/bounce_busy_probe.py"
    # since 2026-08-21 (4b0c621c); without this file python3 exits 2, the guard fails
    # OPEN by design, and the run proceeds to the restart — which is not what these
    # tests are about. Provision it so the guard is satisfied, not bypassed.
    ( scripts / "bounce_busy_probe.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    # Fake docker + curl so `docker restart` and the health poll succeed at once.
    #
    # docker CANNOT be a bare `exit 0` any more. Since 2026-08-21 the script also waits for
    # the container's own StartedAt to be newer than the restart it issued (the identity
    # guard, row 1c36199e) — a bare stub prints nothing, the wait can never be satisfied,
    # and the 30s subprocess timeout kills the test for a reason that has nothing to do
    # with the warn split. So the stub answers `inspect` with a start time of NOW, which is
    # what a real restart would report, and keeps exiting 0 for `restart` and `logs`.
    # The fake sits FIRST on PATH, so no arm here ever reaches the real container.
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
    return subprocess.run(
        [ "bash", _SCRIPT, *extra_args ],
        env=env, capture_output=True, text=True, timeout=30,
    )


class TestBounceWarnExitSplit( unittest.TestCase ):

    def test_exit_0_confirms_the_fleet_was_reached( self ):
        r = _run( 0 )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "reached the fleet", r.stdout )
        self.assertNotIn( "NOBODY", r.stdout )
        self.assertNotIn( "Pausing", r.stdout )

    def test_exit_1_partial_reach_proceeds_without_pause( self ):
        r = _run( 1 )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "PARTIALLY", r.stdout )
        self.assertNotIn( "NOBODY", r.stdout )
        self.assertNotIn( "Pausing", r.stdout )

    def test_exit_2_names_the_unwarned_fleet_and_pauses_then_proceeds( self ):
        r = _run( 2, pause_secs="1" )
        self.assertEqual( r.returncode, 0 )                 # still bounces — recovery is not blocked
        self.assertIn( "NOBODY was warned", r.stdout )
        self.assertIn( "Pausing", r.stdout )

    def test_exit_2_with_force_skips_the_pause( self ):
        r = _run( 2, extra_args=( "--force", ), pause_secs="1" )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "NOBODY was warned", r.stdout )
        self.assertIn( "--force", r.stdout )
        self.assertNotIn( "Pausing", r.stdout )

    def test_an_unexpected_code_is_treated_as_nobody_warned( self ):
        """A code the helper never documents (e.g. 3) must fail LOUD as unwarned,
        not slip through as if it were fine."""
        r = _run( 3, pause_secs="0" )
        self.assertEqual( r.returncode, 0 )
        self.assertIn( "NOBODY was warned", r.stdout )

    def test_exit_1_and_exit_2_are_no_longer_indistinguishable( self ):
        """The crux of row 32e659f1: the two outcomes now read differently."""
        one = _run( 1 ).stdout
        two = _run( 2, pause_secs="0" ).stdout
        self.assertNotEqual( one, two )
        self.assertIn( "PARTIALLY", one )
        self.assertNotIn( "PARTIALLY", two )
        self.assertIn( "NOBODY was warned", two )
        self.assertNotIn( "NOBODY", one )


if __name__ == "__main__":
    unittest.main()
