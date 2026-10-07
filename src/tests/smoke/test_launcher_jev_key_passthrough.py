"""
The launcher hands JEV_API_TOASTER to every seat it starts, without ever showing the value.

Row 53ebe1a9 (Rick, 2026-10-07): the key lives in ~/.bashrc under an interactive-only guard, so
a seat started from a non-interactive parent never had it, and someone copied it into tmux by hand.
These tests run the REAL launcher, headless, on an isolated tmux socket, with a fake `claude` that
dumps its own environment. That dump is the oracle: it is what the process in claude's seat read.

The value used here is an obvious fake. Nothing in this file touches the real key.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import cosa.utils.util as cu
from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS, isolate_fleet_census


LAUNCHER = Path( cu.get_project_root() ) / "src" / "scripts" / "start-cc-with-tmux.sh"
KEY      = "JEV_API_TOASTER"
FAKE     = "fake-jev-sentinel-0123456789.abc"
OTHER    = "other-jev-sentinel-9876543210.xyz"

needs_tmux = pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )


def _tmux( socket_dir, *args ):
    """Run tmux against the ISOLATED server, never the fleet's."""
    env = { k: v for k, v in os.environ.items() if k != KEY }
    for k in TMUX_ISOLATION_STRIP_KEYS: env.pop( k, None )
    env[ "TMUX_TMPDIR" ] = str( socket_dir )
    return subprocess.run( [ "tmux", *args ], capture_output=True, text=True, env=env, timeout=30 )


def _launch( launcher, socket_dir, fake_bin, session_name, key=None, dry_run=False ):
    """
    Run the launcher headless on the isolated socket.

    Requires:
        - key is None (caller shell lacks the variable) or the value the caller shell exports

    Ensures:
        - returns the CompletedProcess; the tmux server, if born, lives on socket_dir
    """
    env = { k: v for k, v in os.environ.items() if k != KEY }
    for k in TMUX_ISOLATION_STRIP_KEYS: env.pop( k, None )
    env[ "TMUX_TMPDIR" ] = str( socket_dir )
    env[ "PATH" ]        = f"{fake_bin}:{env['PATH']}"
    env[ "LUPIN_ROOT" ]  = cu.get_project_root()
    isolate_fleet_census( env, socket_dir )
    if key is not None: env[ KEY ] = key
    args = [ "bash", str( launcher ), "--headless" ] + ( [ "--dry-run" ] if dry_run else [] ) + [ session_name ]
    return subprocess.run( args, capture_output=True, text=True, env=env, timeout=120 )


def _pane_env( dump ):
    """The environment the fake claude read, as a dict; waits briefly for the dump to land."""
    for _ in range( 50 ):
        if dump.exists() and dump.read_text().strip(): break
        time.sleep( 0.1 )
    assert dump.exists(), "the fake claude never ran, so there is no pane environment to read"
    return dict( line.split( "=", 1 ) for line in dump.read_text().splitlines() if "=" in line )


@pytest.fixture
def rig( tmp_path ):
    """An isolated tmux socket, and a fake `claude` that dumps its env and parks."""
    socket_dir = tmp_path / "tmux"
    fake_bin   = tmp_path / "bin"
    socket_dir.mkdir()
    fake_bin.mkdir()
    dump = tmp_path / "claude-env-dump.txt"
    fake = fake_bin / "claude"
    fake.write_text( f'#!/usr/bin/env bash\nenv > "{dump}"\nsleep 20\n' )
    fake.chmod( 0o755 )
    yield socket_dir, fake_bin, dump
    _tmux( socket_dir, "kill-server" )


@needs_tmux
def test_a_caller_with_the_key_and_no_server_reaches_the_pane( rig ):
    socket_dir, fake_bin, dump = rig
    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-birth", key=FAKE )
    assert result.returncode == 0, result.stderr
    assert _pane_env( dump ).get( KEY ) == FAKE


@needs_tmux
def test_a_server_that_lacks_the_key_is_handed_it_and_the_pane_reads_it( rig ):
    """The acceptance case: an existing server whose global environment lacks the variable."""
    socket_dir, fake_bin, dump = rig
    assert _tmux( socket_dir, "new-session", "-d", "-s", "elder", "sleep 60" ).returncode == 0
    assert KEY not in _tmux( socket_dir, "show-environment", "-g" ).stdout.replace( "-" + KEY, "" )

    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-existing", key=FAKE )
    assert result.returncode == 0, result.stderr
    assert _pane_env( dump ).get( KEY ) == FAKE


@needs_tmux
def test_a_caller_without_the_key_inherits_it_from_the_tmux_global_environment( rig ):
    socket_dir, fake_bin, dump = rig
    assert _tmux( socket_dir, "new-session", "-d", "-s", "elder", "sleep 60" ).returncode == 0
    assert _tmux( socket_dir, "set-environment", "-g", KEY, OTHER ).returncode == 0

    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-global", key=None )
    assert result.returncode == 0, result.stderr
    assert _pane_env( dump ).get( KEY ) == OTHER


@needs_tmux
def test_no_source_anywhere_says_so_out_loud_and_the_seat_still_starts( rig ):
    socket_dir, fake_bin, dump = rig
    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-none", key=None )
    assert result.returncode == 0, result.stderr
    assert "WITHOUT the Jev key" in result.stderr
    assert KEY not in _pane_env( dump )


@needs_tmux
def test_a_value_the_launcher_will_not_pass_is_refused_loudly_and_never_echoed( rig ):
    socket_dir, fake_bin, dump = rig
    bad = "has'quote and space"
    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-bad", key=bad )
    assert result.returncode == 0, result.stderr
    assert "will not pass through tmux" in result.stderr
    assert bad not in result.stdout + result.stderr
    assert KEY not in _pane_env( dump )


@needs_tmux
def test_the_value_is_never_printed_or_logged_by_the_launcher( rig ):
    socket_dir, fake_bin, dump = rig
    result = _launch( LAUNCHER, socket_dir, fake_bin, "jev-quiet", key=FAKE )
    assert FAKE not in result.stdout + result.stderr
    dry = _launch( LAUNCHER, socket_dir, fake_bin, "jev-dry", key=FAKE, dry_run=True )
    assert "JEV-KEY: source=launcher-env" in dry.stdout
    assert FAKE not in dry.stdout + dry.stderr


@needs_tmux
def test_the_existing_server_probe_can_fail_without_the_hand_off( rig, tmp_path ):
    """
    NEGATIVE CONTROL. Cut the hand-off to a running server out of a COPY of the launcher: the
    pane of a seat on an existing server must then lack the key. If it still had it, the
    acceptance test above would be measuring something other than the hand-off.
    """
    socket_dir, fake_bin, dump = rig
    source = LAUNCHER.read_text()
    needle = "| tmux source-file - >/dev/null 2>&1"
    assert source.count( needle ) == 1, "the hand-off line moved; this control cannot mutate what it cannot find"
    mutant = tmp_path / "mutant-launcher.sh"
    mutant.write_text( source.replace( needle, "| cat >/dev/null 2>&1" ) )

    assert _tmux( socket_dir, "new-session", "-d", "-s", "elder", "sleep 60" ).returncode == 0
    result = _launch( mutant, socket_dir, fake_bin, "jev-mutant", key=FAKE )
    assert result.returncode == 0, result.stderr
    assert KEY not in _pane_env( dump ), "the mutant still delivered the key, so the hand-off is not what delivers it"
