"""
The test container's start script and compose env for server coverage.

With LUPIN_SERVER_COVERAGE unset, the script's last command is the unchanged
`exec python3 -m lupin_app.main`. With it set to 1, the server runs under `coverage run` after
`write-boot`. The compose env passes the variable to lupin-rest-test and to no other service.
The script runs against a stub `python3` that logs its argv.

Venue: :7999-eligible. No server and no container; everything lives under tmp_path.
"""

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest
import yaml

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
SCRIPT       = f"{PROJECT_ROOT}/src/scripts/run-fastapi-lupin-test.sh"
COMPOSE      = f"{PROJECT_ROOT}/docker-compose.yml"


def _run( tmp_path, coverage_value ):
    """Run a copy of the start script with a stub python3; return the logged invocations."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    log = tmp_path / "calls.log"
    stub = stub_dir / "python3"
    stub.write_text( f'#!/bin/bash\necho "$*" >> "{log}"\nexit 0\n' )
    stub.chmod( 0o755 )
    text = open( SCRIPT ).read().replace( "cd /var/lupin/src", f'cd "{tmp_path}"' )
    text = text.replace( "/home/rruiz/.lupin/test-env.sh", str( tmp_path / "absent-env.sh" ) )
    copy = tmp_path / "start.sh"
    copy.write_text( text )
    env = { **os.environ, "PATH": f"{stub_dir}:{os.environ[ 'PATH' ]}", "LUPIN_ROOT": "/var/lupin" }
    env.pop( "LUPIN_SERVER_COVERAGE", None )
    if coverage_value is not None: env[ "LUPIN_SERVER_COVERAGE" ] = coverage_value
    done = subprocess.run( [ "bash", str( copy ) ], env=env, capture_output=True, text=True, timeout=30 )
    assert done.returncode == 0, done.stderr
    return log.read_text().splitlines()


@pytest.mark.parametrize( "value", [ None, "", "0", "yes" ] )
def test_without_the_flag_the_start_is_the_unchanged_exec( tmp_path, value ):
    calls = _run( tmp_path, value )
    assert calls[ -1 ] == "-m lupin_app.main"
    assert not any( "coverage" in call for call in calls )


def test_with_the_flag_the_server_runs_under_coverage_after_write_boot( tmp_path ):
    calls = _run( tmp_path, "1" )
    assert "-m cosa.utils.server_coverage write-boot" in calls
    assert calls.index( "-m cosa.utils.server_coverage write-boot" ) < len( calls ) - 1
    last = calls[ -1 ]
    assert last.startswith( "-m coverage run --parallel-mode --branch --rcfile=" )
    assert " --data-file=" in last
    assert "--include=/var/lupin/src/lupin_app/main.py" in last
    assert "--rcfile=/var/lupin/src/conf/coverage-server.rc" in last
    assert last.endswith( "-m lupin_app.main" )


def test_a_failed_write_boot_stops_the_start( tmp_path ):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "python3"
    stub.write_text( '#!/bin/bash\n[[ "$*" == *write-boot* ]] && exit 7\nexit 0\n' )
    stub.chmod( 0o755 )
    text = open( SCRIPT ).read().replace( "cd /var/lupin/src", f'cd "{tmp_path}"' ).replace(
        "/home/rruiz/.lupin/test-env.sh", str( tmp_path / "absent-env.sh" ) )
    copy = tmp_path / "start.sh"
    copy.write_text( text )
    env  = { **os.environ, "PATH": f"{stub_dir}:{os.environ[ 'PATH' ]}", "LUPIN_SERVER_COVERAGE": "1" }
    done = subprocess.run( [ "bash", str( copy ) ], env=env, capture_output=True, text=True, timeout=30 )
    assert done.returncode == 1


def test_the_compose_env_passes_the_flag_to_the_test_service_only():
    services = yaml.safe_load( open( COMPOSE ) )[ "services" ]
    carriers = [ name for name, spec in services.items()
                 if "LUPIN_SERVER_COVERAGE" in ( spec.get( "environment" ) or {} ) ]
    assert carriers == [ "lupin-rest-test" ]


SERVER_RC = f"{PROJECT_ROOT}/src/conf/coverage-server.rc"

# A server that finishes its shutdown cleanly, restores the handler it found, and re-raises SIGTERM
# on itself, as uvicorn does.
GRACEFUL_THEN_DIE = textwrap.dedent( """
    import os, signal, sys, time
    got = []
    original = signal.signal( signal.SIGTERM, lambda *a: got.append( 1 ) )
    open( sys.argv[ 1 ], "w" ).write( "up" )
    while not got: time.sleep( 0.05 )
    signal.signal( signal.SIGTERM, original )
    os.kill( os.getpid(), signal.SIGTERM )
    time.sleep( 5 )
""" )


def _sigterm_run( tmp_path, rcfile ):
    """Run the server under `coverage run`, SIGTERM it; return ( exit code, data files )."""
    script = tmp_path / "srv.py"
    script.write_text( GRACEFUL_THEN_DIE )
    ready  = tmp_path / "ready"
    data   = tmp_path / "data"
    data.mkdir()
    cmd    = [ sys.executable, "-m", "coverage", "run", "--parallel-mode", f"--data-file={data}/.coverage" ]
    if rcfile is not None: cmd.append( f"--rcfile={rcfile}" )
    proc   = subprocess.Popen( cmd + [ str( script ), str( ready ) ], cwd=tmp_path )
    deadline = time.time() + 20
    while not ready.exists():
        assert time.time() < deadline, "server never came up"
        time.sleep( 0.05 )
    time.sleep( 0.3 )
    proc.send_signal( signal.SIGTERM )
    code = proc.wait( timeout=20 )
    return code, [ p.name for p in data.iterdir() ]


def test_without_the_server_rcfile_a_sigtermed_server_leaves_no_data( tmp_path ):
    """Control for the defect: the process dies by SIGTERM and no data file exists."""
    code, files = _sigterm_run( tmp_path, None )
    assert code == -signal.SIGTERM
    assert files == []


def test_with_the_server_rcfile_a_sigtermed_server_writes_its_data( tmp_path ):
    code, files = _sigterm_run( tmp_path, SERVER_RC )
    assert code == -signal.SIGTERM
    assert len( files ) == 1 and files[ 0 ].startswith( ".coverage." )


def test_the_server_rcfile_sets_sigterm_and_nothing_that_widens_the_frame():
    import configparser
    parser = configparser.ConfigParser()
    parser.read( SERVER_RC )
    assert dict( parser[ "run" ] ) == { "sigterm": "true" }
    assert parser.sections() == [ "run" ]
