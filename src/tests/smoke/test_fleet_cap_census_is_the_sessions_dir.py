"""
The fleet-cap gate counts bridges in the sessions directory — not `tmux ls`, and not the
live fleet when a test redirects `LUPIN_HOOK_SESSIONS_DIR`.

Why: `test_vertex_launcher_server_*` run the real launcher, whose fleet-cap gate went red
whenever the LIVE fleet was at its cap. The fix points those tests at an empty private
sessions directory (`tmux_isolation.isolate_fleet_census`), which is only sound if the gate
really reads that directory. This file proves it by running the gate's own CLI three ways,
with the cap at its real live value:

  1. empty sessions dir, NINE live tmux sessions on a private socket  -> ADMITTED (exit 0)
     (tmux sessions are not the census)
  2. sessions dir holding cap+1 live-pid bridges                       -> REFUSED  (exit 3)
     (the bridges ARE the census — this arm is what makes arm 1 mean anything)
  3. the same populated dir after the bridges are removed              -> ADMITTED

VENUE: :7999-eligible — private tmux socket and tmp dirs, no network, no persistent state.
"""
import json
import os
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from lupin_mcp import fleet_size_cap
from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS, isolate_fleet_census


def _gate( env, name ):
    return subprocess.run(
        [ sys.executable, "-m", "lupin_mcp.fleet_cap_admission", "--session-name", name, "--headless" ],
        capture_output=True, text=True, env=env, timeout=60
    )


@pytest.fixture
def env( tmp_path ):
    base = dict( os.environ )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        base.pop( key, None )
    base[ "LUPIN_ROOT" ]    = cu.get_project_root()
    base[ "PYTHONPATH" ]    = f"{cu.get_project_root()}/src:{base.get( 'PYTHONPATH', '' )}"
    base[ "TMUX_TMPDIR" ]   = str( tmp_path / "tmux" )
    ( tmp_path / "tmux" ).mkdir()
    return isolate_fleet_census( base, tmp_path / "tmux" )


@pytest.fixture
def cap():
    return fleet_size_cap.resolve_fleet_cap( None, disk_fn=fleet_size_cap.default_disk_cap_reader )


def test_tmux_sessions_are_not_the_census( env, tmp_path ):
    try:
        for n in range( 9 ):
            subprocess.run( [ "tmux", "new-session", "-d", "-s", f"census-{n}", "sleep 60" ],
                            env=env, check=True, capture_output=True, timeout=30 )
        listed = subprocess.run( [ "tmux", "ls" ], env=env, capture_output=True, text=True ).stdout
        assert listed.count( "census-" ) == 9, "precondition: nine live tmux sessions must exist"

        result = _gate( env, "census-probe" )
        assert result.returncode == 0, f"tmux sessions were counted as seats:\n{result.stderr[ -600: ]}"
    finally:
        subprocess.run( [ "tmux", "kill-server" ], env=env, capture_output=True, timeout=30 )


def test_bridges_in_the_sessions_dir_are_the_census( env, cap ):
    sessions = __import__( "pathlib" ).Path( env[ "LUPIN_HOOK_SESSIONS_DIR" ] )
    sleepers = [ subprocess.Popen( [ "sleep", "60" ] ) for _ in range( cap + 1 ) ]
    try:
        for i, proc in enumerate( sleepers ):
            ( sessions / f"cc-{proc.pid}.json" ).write_text( json.dumps( {
                "session_id": f"fake-{i}", "stable_session_id": f"fake-{i}" } ) )

        refused = _gate( env, "census-probe" )
        assert refused.returncode == 3, f"cap {cap} with {cap + 1} live bridges was not refused:\n{refused.stderr[ -600: ]}"
        assert "FLEET CAP REFUSED" in refused.stderr

        for bridge in sessions.glob( "cc-*.json" ): bridge.unlink()
        admitted = _gate( env, "census-probe-2" )
        assert admitted.returncode == 0, f"emptying the dir did not admit:\n{admitted.stderr[ -600: ]}"
    finally:
        for proc in sleepers: proc.kill()
