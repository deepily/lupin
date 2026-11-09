#!/usr/bin/env python3
"""
Unit tests for the preflight check on the test container's Claude Code login.

An expired login makes every Claude Code job in the container fail with the word "success".
The preflight used to check only that the credentials file exists.
It now reads the expiry field alone, never a token. A CLI call is made only for a lapsed expiry, to renew it.
It fails with the remedy in words when the expiry is past or cannot be read.

The helper is tested directly, then the whole script runs against a stand-in docker command.
Nothing here touches a real container.
"""

import datetime
import importlib.util
import os
import stat
import subprocess
import sys

import pytest

import cosa.utils.util as cu

ROOT      = cu.get_project_root()
HELPER    = os.path.join( ROOT, "src/scripts/lib/claude_login_expiry.py" )
PREFLIGHT = os.path.join( ROOT, "src/scripts/preflight-test-container.sh" )

NOW_MS    = 1_790_000_000_000
EXPIRED   = 1_787_808_859_236     # 2026-08-27T05:34:19Z, the value seen in the test container
FAR_AHEAD = 4_102_444_800_000     # 2100-01-01T00:00:00Z


def _helper():
    spec   = importlib.util.spec_from_file_location( "claude_login_expiry", HELPER )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _iso( ms ):
    return datetime.datetime.fromtimestamp( ms / 1000, datetime.timezone.utc ).isoformat()


def test_a_past_expiry_is_expired_and_names_the_date():
    status, detail = _helper().classify( str( EXPIRED ), NOW_MS )
    assert status == "expired" and detail == _iso( EXPIRED )


def test_an_expiry_equal_to_now_is_expired():
    assert _helper().classify( str( NOW_MS ), NOW_MS )[ 0 ] == "expired"


def test_a_future_expiry_is_valid_and_names_the_date():
    status, detail = _helper().classify( str( FAR_AHEAD ), NOW_MS )
    assert status == "valid" and detail == _iso( FAR_AHEAD )


@pytest.mark.parametrize( "raw", [ "", "   ", "abc", "None", "null", "1.5e12", "1787808859.5", "-5", "0", "12 34" ] )
def test_a_value_that_is_not_a_positive_whole_number_is_unreadable( raw ):
    status, detail = _helper().classify( raw, NOW_MS )
    assert status == "unreadable" and detail


def test_surrounding_whitespace_is_ignored():
    assert _helper().classify( f" {FAR_AHEAD}\n", NOW_MS )[ 0 ] == "valid"


@pytest.mark.parametrize( "raw, word, code", [ ( str( EXPIRED ), "expired", 1 ), ( str( FAR_AHEAD ), "valid", 0 ), ( "oops", "unreadable", 1 ) ] )
def test_the_command_line_prints_one_line_and_exits_by_verdict( raw, word, code ):
    done = subprocess.run( [ sys.executable, HELPER, raw ], capture_output=True, text=True )
    assert done.returncode == code, done.stderr
    assert done.stdout.strip().split( " ", 1 )[ 0 ] == word and len( done.stdout.strip().splitlines() ) == 1


def _fake_docker( tmp_path ):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    path = bin_dir / "docker"
    path.write_text(
        '#!/bin/bash\n'
        'echo "$@" >> "$FAKE_DOCKER_LOG"\n'
        'case "$1" in\n'
        '  info) exit 0 ;;\n'
        '  ps) echo "$FAKE_CONTAINER"; exit 0 ;;\n'
        'esac\n'
        'case "$*" in\n'
        '  *"test -f /home/rruiz/.claude/.credentials.json"*) exit 0 ;;\n'
        '  *"claude -p"*) if [ -n "${FAKE_RENEW_HANG:-}" ]; then exec sleep 30; fi; touch "$FAKE_DOCKER_LOG.renewed"; exit 0 ;;\n'
        '  *expiresAt*) if [ -n "${FAKE_EXPIRES_FAIL:-}" ]; then echo "KeyError" >&2; exit 1; fi; if [ -n "${FAKE_EXPIRES_AFTER:-}" ] && [ -e "$FAKE_DOCKER_LOG.renewed" ]; then echo "$FAKE_EXPIRES_AFTER"; else echo "$FAKE_EXPIRES"; fi; exit 0 ;;\n'
        'esac\n'
        'exit 1\n' )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return bin_dir


def _preflight( tmp_path, expires="", fail=False, after=None ):
    env = dict( os.environ, PATH=f"{_fake_docker( tmp_path )}:{os.environ[ 'PATH' ]}", FAKE_CONTAINER="fake-test",
                PREFLIGHT_CONTAINER="fake-test", FAKE_EXPIRES=str( expires ), FAKE_DOCKER_LOG=str( tmp_path / "docker.log" ) )
    if fail: env[ "FAKE_EXPIRES_FAIL" ] = "1"
    if after is not None: env[ "FAKE_EXPIRES_AFTER" ] = str( after )
    done = subprocess.run( [ "bash", PREFLIGHT ], capture_output=True, text=True, env=env, cwd=ROOT )
    log  = ( tmp_path / "docker.log" ).read_text() if ( tmp_path / "docker.log" ).exists() else ""
    return done.stdout, log


def _login_line( out ):
    return next( l for l in out.splitlines() if "claude login" in l )


def test_an_expired_login_fails_the_preflight_with_the_remedy_in_words( tmp_path ):
    out, _ = _preflight( tmp_path, expires=EXPIRED )
    line = _login_line( out )
    assert "[FAIL]" in line and "expired" in line and _iso( EXPIRED ) in line, out
    assert "docker exec -it fake-test claude /login" in out and "browser" in out, out


def test_an_unreadable_login_fails_the_preflight_with_the_same_remedy( tmp_path ):
    out, _ = _preflight( tmp_path, fail=True )
    line = _login_line( out )
    assert "[FAIL]" in line and "could not be read" in line, out
    assert "docker exec -it fake-test claude /login" in out, out


def test_a_valid_login_passes_the_check_and_prints_its_expiry( tmp_path ):
    out, _ = _preflight( tmp_path, expires=FAR_AHEAD )
    line = _login_line( out )
    assert "[OK]" in line and _iso( FAR_AHEAD ) in line, out


def test_the_check_reads_the_expiry_field_and_never_a_token_or_the_cli( tmp_path ):
    _, log = _preflight( tmp_path, expires=FAR_AHEAD )
    asked = [ l for l in log.splitlines() if "expiresAt" in l ]
    assert len( asked ) == 1, log
    for forbidden in ( "accessToken", "refreshToken", "claude -p", "claude --" ):
        assert forbidden not in log, log


def test_a_lapsed_expiry_that_one_call_renews_passes_without_a_login( tmp_path ):
    out, log = _preflight( tmp_path, expires=EXPIRED, after=FAR_AHEAD )
    line = _login_line( out )
    assert "[OK]" in line and _iso( FAR_AHEAD ) in line and "renewed from the refresh token" in line, out
    assert "claude /login" not in out, "no remedy for a login that was never lost"
    assert len( [ l for l in log.splitlines() if "claude -p" in l ] ) == 1, log
    assert len( [ l for l in log.splitlines() if "expiresAt" in l ] ) == 2, "one read before the call, one after"


def test_a_lapsed_expiry_that_the_call_does_not_move_still_fails_with_the_remedy( tmp_path ):
    out, log = _preflight( tmp_path, expires=EXPIRED, after=EXPIRED )
    line = _login_line( out )
    assert "[FAIL]" in line and "expired" in line and _iso( EXPIRED ) in line, out
    assert "docker exec -it fake-test claude /login" in out, out
    assert len( [ l for l in log.splitlines() if "claude -p" in l ] ) == 1, log


def test_an_unreadable_expiry_is_never_renewed( tmp_path ):
    _, log = _preflight( tmp_path, fail=True )
    assert "claude -p" not in log, log


def test_a_renewing_call_that_hangs_is_cut_off_and_reads_as_not_renewed( tmp_path, monkeypatch ):
    import time
    monkeypatch.setenv( "FAKE_RENEW_HANG", "1" )
    monkeypatch.setenv( "CLAUDE_LOGIN_RENEW_TIMEOUT", "1" )
    start = time.monotonic()
    out, log = _preflight( tmp_path, expires=EXPIRED, after=FAR_AHEAD )
    assert time.monotonic() - start < 20, "the 30-second hang was cut off by the timeout"
    line = _login_line( out )
    assert "[FAIL]" in line and "expired" in line and "renewed from the refresh token" not in line, out
    assert "docker exec -it fake-test claude /login" in out, out
    assert len( [ l for l in log.splitlines() if "claude -p" in l ] ) == 1, log


def test_the_renewing_call_runs_under_a_sixty_second_timeout_by_default( ):
    text = open( os.path.join( ROOT, "src/scripts/lib/claude-login-probe.sh" ) ).read()
    assert 'timeout "${CLAUDE_LOGIN_RENEW_TIMEOUT:-60}" docker exec' in text
