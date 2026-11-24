#!/usr/bin/env python3
"""
Tests for the timed Claude login check (the podcast login bug).

The fixtures are the numbers measured in lupin-rest-dev on 23 Nov 2026: refresh token empty, access expiry 0,
refresh expiry 1795463156832 (19:45:56 UTC).
"""

import os
import subprocess
import sys

import cosa.utils.util as cu

LIB    = os.path.join( cu.get_project_root(), "src/scripts/lib" )
TICK   = os.path.join( cu.get_project_root(), "src/scripts/claude-login-tick.sh" )
sys.path.insert( 0, LIB )
import claude_login_expiry as cle  # noqa: E402

NOW      = 1795463156832 + 5 * 3600 * 1000
DAY_MS   = 86400 * 1000


def test_the_measured_blank_login_is_blank():
    assert cle.classify_refresh( 0, 1795463156832, NOW )[ 0 ] == "blank"


def test_a_present_token_past_its_expiry_is_lapsed_and_names_the_instant():
    assert cle.classify_refresh( 100, 1795463156832, NOW ) == ( "lapsed", "2026-11-23T19:45:56.832000+00:00" )


def test_a_token_lapsing_inside_the_window_is_soon_and_outside_is_ok():
    assert cle.classify_refresh( 100, NOW + 3 * DAY_MS, NOW )[ 0 ] == "soon"
    assert cle.classify_refresh( 100, NOW + 30 * DAY_MS, NOW )[ 0 ] == "ok"
    assert cle.classify_refresh( 100, 0, NOW ) == ( "ok", "no expiry recorded" )


def _run( *args ):
    return subprocess.run( [ sys.executable, os.path.join( LIB, "claude_login_expiry.py" ), *args ], capture_output=True, text=True )


def test_the_command_line_is_silent_when_ok_and_names_the_remedy_otherwise():
    far = str( ( 10**13 ) )
    ok = _run( "--refresh", "c1", "100", far )
    assert ( ok.returncode, ok.stdout ) == ( 0, "" )
    bad = _run( "--refresh", "c1", "0", "1795463156832" )
    assert bad.returncode == 2 and "docker exec -it c1 claude /login" in bad.stdout and "is blank" in bad.stdout


def test_print_install_prints_one_crontab_line_and_touches_nothing_else():
    out = subprocess.run( [ "bash", TICK, "--print-install" ], capture_output=True, text=True )
    assert out.returncode == 0 and out.stdout.count( "\n" ) == 1 and out.stdout.rstrip().endswith( "# claude-login-tick" )


def test_a_missing_container_is_exit_one_not_a_false_all_clear(tmp_path):
    fake = tmp_path / "docker"
    fake.write_text( "#!/bin/sh\nexit 1\n" ); fake.chmod( 0o755 )
    env = dict( os.environ, PATH=f"{tmp_path}:{os.environ[ 'PATH' ]}" )
    out = subprocess.run( [ "bash", TICK, "nope" ], capture_output=True, text=True, env=env )
    assert out.returncode == 1 and "cannot read the login" in out.stderr
