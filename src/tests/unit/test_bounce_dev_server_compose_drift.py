#!/usr/bin/env python3
"""
Row 92374685 — bounce-dev-server.sh must RECREATE a container whose compose tmpfs, mounts
or environment have drifted, because `docker restart` silently keeps the old values. That
is how the MP3 upload answered 500 on two mornings of 2026-09-15.

The REAL script runs against a temp LUPIN_ROOT holding a FAKE compose_drift_probe.py that
exits a chosen code, fake busy and warn helpers (exit 0), and a fake docker that records
every call it gets. The assertion is on the docker verb the script actually issued, so the
drift and no-drift arms cannot pass by the same path:

    probe 0   → `docker restart`, never `compose up`
    probe 10  → `docker compose ... up -d --force-recreate --no-deps lupin-rest-dev`,
                never `docker restart`, and the recreate is announced even under --quiet
    probe 20  → fail OPEN: `docker restart`, and the script says the probe could not answer
    no probe  → fail OPEN the same way (python3 exits 2 on a missing file)
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import cosa.utils.util as cu

_SCRIPT = cu.get_project_root() + "/src/scripts/bounce-dev-server.sh"


# The recreate the fake probe hands back names a tree that is NOT LUPIN_ROOT, so an assertion
# on the issued command can tell "ran what the probe compared" from "rebuilt from LUPIN_ROOT".
COMPARED_TREE = "/compared/tree"
RECREATE_ARGS = [ "docker", "compose", "--project-name", "lupin", "--project-directory", COMPARED_TREE,
                  "-f", COMPARED_TREE + "/docker-compose.yml", "up", "-d", "--force-recreate", "--no-deps", "lupin-rest-dev" ]


def _run( drift_rc=None, extra_args=(), recreate_args=RECREATE_ARGS ):
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "bounce_busy_probe.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    ( scripts / "bounce_dev_warn.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    if drift_rc is not None:
        ( scripts / "compose_drift_probe.py" ).write_text(
            "import sys\nprint( 'probe saw', sys.argv[ 1: ] )\n"
            + "".join( f"print( {( 'RECREATE_ARG=' + a )!r} )\n" for a in ( recreate_args if drift_rc == 10 else [ ] ) )
            + "sys.exit( %d )\n" % drift_rc
        )

    calls   = Path( tmp ) / "docker-calls.txt"
    fakebin = Path( tmp ) / "bin"
    fakebin.mkdir()
    # Records every invocation; answers `inspect` with a start time of NOW so the script's
    # identity wait (the container started after the bounce was issued) is satisfied.
    ( fakebin / "docker" ).write_text(
        "#!/bin/sh\n"
        f"echo \"$*\" >> {calls}\n"
        "if [ \"$1\" = \"inspect\" ]; then date -u +%Y-%m-%dT%H:%M:%S.000000000Z; fi\n"
        "exit 0\n"
    )
    ( fakebin / "docker" ).chmod( 0o755 )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    ( fakebin / "curl" ).chmod( 0o755 )

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]          = tmp
    env[ "PATH" ]                = str( fakebin ) + os.pathsep + env[ "PATH" ]
    env[ "UNWARNED_PAUSE_SECS" ] = "0"
    env[ "HEALTH_CONSECUTIVE" ]  = "1"
    result = subprocess.run( [ "bash", _SCRIPT, *extra_args ], env=env, capture_output=True, text=True, timeout=30 )
    issued = calls.read_text().splitlines() if calls.exists() else [ ]
    return result, issued, tmp


def _verbs( issued ):
    return [ line for line in issued if not line.startswith( ( "inspect", "logs" ) ) ]


class TestBounceRecreatesOnComposeDrift( unittest.TestCase ):

    def test_no_drift_restarts_and_never_recreates( self ):
        r, issued, _ = _run( drift_rc=0 )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertEqual( _verbs( issued ), [ "restart lupin-rest-dev" ] )
        self.assertIn( "probe saw ['lupin-rest-dev']", r.stdout )

    def test_drift_recreates_through_compose_and_never_restarts( self ):
        r, issued, tmp = _run( drift_rc=10 )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertEqual( _verbs( issued ), [ " ".join( RECREATE_ARGS[ 1: ] ) ] )
        self.assertNotIn( tmp, _verbs( issued )[ 0 ], "the recreate was rebuilt from LUPIN_ROOT, not the compared tree" )
        self.assertIn( "RECREATING", r.stdout )
        self.assertNotIn( "RECREATE_ARG=", r.stdout, "the machine lines leaked into the human output" )

    def test_drift_with_no_recreate_command_refuses_rather_than_restarting( self ):
        r, issued, _ = _run( drift_rc=10, recreate_args=[ ] )
        self.assertEqual( r.returncode, 1 )
        self.assertIn( "no usable recreate command", r.stderr )
        self.assertEqual( _verbs( issued ), [ ] )

    def test_the_recreate_is_announced_even_under_quiet( self ):
        r, issued, _ = _run( drift_rc=10, extra_args=( "--quiet", ) )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertIn( "RECREATING", r.stdout )
        self.assertNotIn( "restart lupin-rest-dev", issued )

    def test_env_drift_restarts_and_says_it_did_not_apply_the_drift_even_under_quiet( self ):
        r, issued, _ = _run( drift_rc=11, extra_args=( "--quiet", ) )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertEqual( _verbs( issued ), [ "restart lupin-rest-dev" ] )
        self.assertIn( "restarting WITHOUT applying it", r.stdout )
        self.assertIn( "probe saw ['lupin-rest-dev']", r.stdout, "the probe's own drift report must reach the caller" )

    def test_an_unknown_probe_fails_open_to_a_restart( self ):
        r, issued, _ = _run( drift_rc=20 )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertEqual( _verbs( issued ), [ "restart lupin-rest-dev" ] )
        self.assertIn( "could not answer (rc 20)", r.stdout )

    def test_a_tree_with_no_probe_fails_open_to_a_restart( self ):
        r, issued, _ = _run( drift_rc=None )
        self.assertEqual( r.returncode, 0, r.stderr )
        self.assertEqual( _verbs( issued ), [ "restart lupin-rest-dev" ] )
        self.assertIn( "failing OPEN", r.stdout )

    def test_a_failed_recreate_is_an_error_not_a_silent_restart( self ):
        r, issued, tmp = _run( drift_rc=10 )
        # Re-run with a docker that fails `compose`, reusing the same shape.
        fake = Path( tmp ) / "bin" / "docker"
        fake.write_text( "#!/bin/sh\nif [ \"$1\" = \"compose\" ]; then exit 1; fi\nexit 0\n" )
        env = dict( os.environ, LUPIN_ROOT=tmp, PATH=str( Path( tmp ) / "bin" ) + os.pathsep + os.environ[ "PATH" ],
                    UNWARNED_PAUSE_SECS="0", HEALTH_CONSECUTIVE="1" )
        failed = subprocess.run( [ "bash", _SCRIPT ], env=env, capture_output=True, text=True, timeout=30 )
        self.assertEqual( failed.returncode, 1 )
        self.assertIn( "--force-recreate failed", failed.stderr )


if __name__ == "__main__":
    unittest.main()
