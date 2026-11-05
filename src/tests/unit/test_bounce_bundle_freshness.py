"""
bounce-dev-server.sh checks that the served client bundle is not stale.

Merged TypeScript does not rebuild src/lupin_app/static/dist/, so a healthy bounce can serve old client code.
After the health poll the script runs check_bundle_freshness.py.
A stale bundle exits 5 and names the rebuild command.
An unanswerable check only warns, and a skip variable turns it off.
The bounce runs for real with a stub docker and a stub checker; nothing reaches a server.
Venue: :7999 (unit).
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT   = os.environ[ "LUPIN_ROOT" ]
BOUNCE = os.path.join( ROOT, "src/scripts/bounce-dev-server.sh" )


def _bounce( checker_rc=None, *, quiet=True, **extra ):
    tmp     = tempfile.mkdtemp()
    scripts = Path( tmp ) / "src" / "scripts"
    scripts.mkdir( parents=True )
    for name in ( "bounce_dev_warn.py", "bounce_busy_probe.py" ): ( scripts / name ).write_text( "import sys\nsys.exit( 0 )\n" )
    fakebin = Path( tmp ) / "bin"
    fakebin.mkdir()
    ( fakebin / "docker" ).write_text( "#!/bin/sh\nif [ \"$1\" = \"inspect\" ]; then date -u +%Y-%m-%dT%H:%M:%S.000000000Z; fi\nexit 0\n" )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    env = dict( os.environ, LUPIN_ROOT=tmp, PATH=str( fakebin ) + os.pathsep + os.environ[ "PATH" ], UNWARNED_PAUSE_SECS="0",
                HEALTH_CONSECUTIVE="1", LUPIN_DB_GRANTS_CHECK="skip", LUPIN_CLAUDE_LOGIN_CHECK="skip" )
    for name in ( "docker", "curl" ): ( fakebin / name ).chmod( 0o755 )
    if checker_rc is not None:
        checker = Path( tmp ) / "stub-checker"
        checker.write_text( f"#!/bin/sh\necho ran >> {tmp}/checker.log\necho 'checker says hello'\nexit {checker_rc}\n" )
        checker.chmod( 0o755 )
        env[ "LUPIN_BUNDLE_FRESHNESS_CMD" ] = str( checker )
    env.update( extra )
    args = [ "bash", BOUNCE ] + ( [ "--quiet" ] if quiet else [ ] )
    done = subprocess.run( args, env=env, capture_output=True, text=True, timeout=60 )
    log  = Path( tmp ) / "checker.log"
    return done, ( log.read_text().split() if log.exists() else [ ] )


def test_a_stale_bundle_exits_five_and_names_the_rebuild_command():
    done, ran = _bounce( 1 )
    assert done.returncode == 5 and ran == [ "ran" ]
    assert "STALE client bundle" in done.stderr and "npm run build" in done.stderr
    assert "checker says hello" in done.stdout, "the checker's own report must reach the operator"


def test_a_fresh_bundle_exits_zero_and_stays_quiet_under_quiet():
    done, ran = _bounce( 0 )
    assert done.returncode == 0 and ran == [ "ran" ]
    assert "checker says hello" not in done.stdout and "STALE" not in done.stderr


def test_a_fresh_bundle_prints_the_report_without_quiet():
    done, _ = _bounce( 0, quiet=False )
    assert done.returncode == 0 and "checker says hello" in done.stdout


@pytest.mark.parametrize( "rc", [ 2, 127 ] )
def test_a_check_that_cannot_answer_warns_and_exits_zero( rc ):
    done, ran = _bounce( rc )
    assert done.returncode == 0 and ran == [ "ran" ]
    assert "could not be checked for staleness" in done.stderr


def test_the_skip_variable_never_runs_the_checker():
    done, ran = _bounce( 1, LUPIN_BUNDLE_FRESHNESS_CHECK="skip" )
    assert done.returncode == 0 and ran == [ ]


def test_the_default_checker_is_the_shipped_script():
    text = Path( BOUNCE ).read_text()
    assert 'bundle_cmd=( python3 "${SCRIPT_DIR}/check_bundle_freshness.py" --quiet )' in text
    assert os.path.isfile( os.path.join( ROOT, "src/scripts/check_bundle_freshness.py" ) )
