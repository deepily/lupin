"""
The test-login secret probe of the container preflight, run as a sourced function.

A scratch file stands in for the compose secret, and the expected owner is this process's own, so no root
and no docker are needed. Venue: :7999 (unit).
"""

import os
import subprocess

import pytest

ROOT  = os.environ[ "LUPIN_ROOT" ]
PROBE = os.path.join( ROOT, "src/scripts/lib/preflight-test-secret-probe.sh" )
SCRIPT = os.path.join( ROOT, "src/scripts/preflight-test-container.sh" )
ME    = f"{os.getuid()}:{os.getgid()}"

DRIVER = """
source "$PROBE"
say_ok()   { echo "OK: $1"; }
say_fail() { echo "FAIL: $1"; }
remedy()   { echo "REMEDY: $1"; }
probe_test_login_secret
"""


def _run( path, mode="440", owner=ME ):
    env = dict( os.environ, PROBE=PROBE, TEST_LOGIN_SECRET_FILE=str( path ), TEST_LOGIN_SECRET_OWNER=owner, TEST_LOGIN_SECRET_MODE=mode )
    return subprocess.run( [ "bash", "-c", DRIVER ], env=env, capture_output=True, text=True, timeout=30 ).stdout


def _secret( tmp_path, text="pw", mode=0o440 ):
    path = tmp_path / "db_test_password"
    path.write_text( text )
    path.chmod( mode )
    return path


def test_a_right_looking_file_is_ok( tmp_path ):
    out = _run( _secret( tmp_path ) )
    assert out.startswith( "OK: test login secret" ) and "FAIL" not in out


def test_an_absent_file_fails_and_names_the_provisioner_and_the_recreate( tmp_path ):
    out = _run( tmp_path / "nowhere" )
    assert "FAIL: test login secret" in out and "is missing" in out
    assert "provision-db-roles.sh --secrets-dir" in out and "--force-recreate lupin-rest-test" in out


def test_an_empty_file_fails_as_empty_not_as_missing( tmp_path ):
    out = _run( _secret( tmp_path, text="" ) )
    assert "is empty" in out and "is missing" not in out


def test_a_wrong_mode_fails_naming_the_mode( tmp_path ):
    out = _run( _secret( tmp_path, mode=0o644 ) )
    assert "wrong MODE" in out and "chmod 440" in out and "wrong OWNER" not in out


def test_a_wrong_owner_fails_naming_the_owner_and_wins_over_the_mode( tmp_path ):
    out = _run( _secret( tmp_path, mode=0o644 ), owner="0:1002" )
    assert "wrong OWNER" in out and f"chown 0:1002" in out and "wrong MODE" not in out


def test_the_probe_never_reads_the_content( tmp_path ):
    path = _secret( tmp_path, text="hunter2-never-printed", mode=0o440 )
    assert "hunter2-never-printed" not in _run( path ) + _run( path, mode="600" )


def test_the_preflight_script_runs_the_probe_after_the_grants_probe():
    text = open( SCRIPT ).read()
    assert text.index( "probe_db_grants\n" ) < text.index( "probe_test_login_secret\n" ) < text.index( "# ── Summary" )
