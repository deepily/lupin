#!/usr/bin/env python3
"""
Tests for the dev container's Claude login check.

Three doors read the one expiry field. None reads a token or calls the CLI, because a call would refresh the login.

    lib/claude-login-probe.sh        the shared probe, sourced by the other two
    check-claude-login.sh            standalone, default container lupin-rest-dev
    bounce-dev-server.sh             warns after a healthy bounce, never changes the exit code

Every test drives the real script against a stand-in docker command. No test touches a container.
"""

import datetime
import glob
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

import cosa.utils.util as cu

ROOT    = cu.get_project_root()
CHECK   = os.path.join( ROOT, "src/scripts/check-claude-login.sh" )
PROBE   = os.path.join( ROOT, "src/scripts/lib/claude-login-probe.sh" )
BOUNCE  = os.path.join( ROOT, "src/scripts/bounce-dev-server.sh" )

EXPIRED   = 1_787_808_859_236     # 2026-08-27T05:34:19Z, the value seen in the test container
FAR_AHEAD = 4_102_444_800_000     # 2100-01-01T00:00:00Z


def _iso( ms ):
    return datetime.datetime.fromtimestamp( ms / 1000, datetime.timezone.utc ).isoformat()


def _fake_docker( bin_dir ):
    bin_dir.mkdir( exist_ok=True )
    path = bin_dir / "docker"
    path.write_text(
        '#!/bin/bash\n'
        'echo "$@" >> "$FAKE_DOCKER_LOG"\n'
        'case "$1" in\n'
        '  info) if [ -n "${FAKE_INFO_FAIL:-}" ]; then exit 1; fi; exit 0 ;;\n'
        '  ps) echo "$FAKE_CONTAINER"; exit 0 ;;\n'
        '  inspect) date -u +%Y-%m-%dT%H:%M:%S.000000000Z; exit 0 ;;\n'
        'esac\n'
        'case "$*" in\n'
        '  *expiresAt*) if [ -n "${FAKE_EXPIRES_FAIL:-}" ]; then echo "KeyError" >&2; exit 1; fi; echo "$FAKE_EXPIRES"; exit 0 ;;\n'
        'esac\n'
        'exit 0\n' )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return bin_dir


def _env( tmp_path, expires="", fail=False, container="lupin-rest-dev", info_fail=False ):
    env = dict( os.environ, PATH=f"{_fake_docker( tmp_path / 'bin' )}:{os.environ[ 'PATH' ]}", FAKE_CONTAINER=container,
                FAKE_EXPIRES=str( expires ), FAKE_DOCKER_LOG=str( tmp_path / "docker.log" ) )
    if fail: env[ "FAKE_EXPIRES_FAIL" ] = "1"
    if info_fail: env[ "FAKE_INFO_FAIL" ] = "1"
    return env


def _docker_log( tmp_path ):
    log = tmp_path / "docker.log"
    return log.read_text() if log.exists() else ""


def _standalone( tmp_path, args=(), **kw ):
    done = subprocess.run( [ "bash", CHECK, *args ], capture_output=True, text=True, env=_env( tmp_path, **kw ), cwd=ROOT )
    return done


# ── the standalone check ────────────────────────────────────────────────────

def test_a_valid_login_passes_with_its_expiry_and_exits_zero( tmp_path ):
    done = _standalone( tmp_path, expires=FAR_AHEAD )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "[OK]" in done.stdout and _iso( FAR_AHEAD ) in done.stdout and "lupin-rest-dev" in done.stdout


def test_an_expired_login_fails_with_the_remedy_for_the_dev_container( tmp_path ):
    done = _standalone( tmp_path, expires=EXPIRED )
    assert done.returncode == 1
    assert "[FAIL]" in done.stdout and "expired" in done.stdout and _iso( EXPIRED ) in done.stdout
    assert "docker exec -it lupin-rest-dev claude /login" in done.stdout


def test_an_unreadable_expiry_fails_with_the_same_remedy( tmp_path ):
    done = _standalone( tmp_path, fail=True )
    assert done.returncode == 1
    assert "could not be read" in done.stdout and "docker exec -it lupin-rest-dev claude /login" in done.stdout


def test_a_container_named_on_the_command_line_is_the_one_checked( tmp_path ):
    done = _standalone( tmp_path, args=( "lupin-rest-test", ), expires=EXPIRED, container="lupin-rest-test" )
    assert done.returncode == 1
    assert "docker exec -it lupin-rest-test claude /login" in done.stdout
    assert "lupin-rest-dev" not in done.stdout


def test_a_container_that_is_not_running_exits_two_and_reads_nothing( tmp_path ):
    done = _standalone( tmp_path, expires=FAR_AHEAD, container="" )
    assert done.returncode == 2
    assert "not running" in done.stdout
    assert "expiresAt" not in _docker_log( tmp_path )


def test_an_unreachable_docker_daemon_exits_two( tmp_path ):
    done = _standalone( tmp_path, info_fail=True )
    assert done.returncode == 2 and "docker daemon not reachable" in done.stdout


def test_the_check_reads_the_expiry_field_once_and_never_a_token_or_the_cli( tmp_path ):
    _standalone( tmp_path, expires=FAR_AHEAD )
    log = _docker_log( tmp_path )
    assert len( [ l for l in log.splitlines() if "expiresAt" in l ] ) == 1, log
    for forbidden in ( "accessToken", "refreshToken", "claude -p", "claude --" ):
        assert forbidden not in log, log


# ── the shared probe ────────────────────────────────────────────────────────

def test_the_probe_finds_its_helper_from_any_working_directory( tmp_path ):
    """The probe names its helper by its own directory, not by a lib spelling."""
    script = ( 'run_cmd() { "$@"; }; say_ok() { echo "OK: $1"; }; say_fail() { echo "FAIL: $1"; }; remedy() { echo "REMEDY: $1"; }\n'
               f'source "{PROBE}"\nprobe_claude_login lupin-rest-dev\n' )
    elsewhere = tempfile.mkdtemp()
    done = subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, cwd=elsewhere,
                           env=_env( tmp_path, expires=FAR_AHEAD ) )
    assert "OK: claude login in lupin-rest-dev expires" in done.stdout, done.stdout + done.stderr
    assert _iso( FAR_AHEAD ) in done.stdout


def test_the_probe_survives_a_shell_that_exits_on_error( tmp_path ):
    """A failing docker exec or an expired verdict must not end a script that exits on error."""
    script = ( 'set -euo pipefail\nrun_cmd() { "$@"; }; say_ok() { echo "OK: $1"; }; say_fail() { echo "FAIL: $1"; }; remedy() { echo "REMEDY: $1"; }\n'
               f'source "{PROBE}"\nprobe_claude_login lupin-rest-dev\necho AFTER\n' )
    for kw in ( dict( fail=True ), dict( expires=EXPIRED ) ):
        done = subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, cwd=ROOT, env=_env( tmp_path, **kw ) )
        assert done.returncode == 0 and "AFTER" in done.stdout, done.stdout + done.stderr


# ── the bounce script ───────────────────────────────────────────────────────

def _bounce( tmp_path, expires="", fail=False, skip=False ):
    """Run the real bounce script in a stub tree whose docker answers the expiry read."""
    tree    = Path( tempfile.mkdtemp() )
    scripts = tree / "src" / "scripts"
    scripts.mkdir( parents=True )
    ( scripts / "bounce_busy_probe.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    ( scripts / "bounce_dev_warn.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    fakebin = _fake_docker( tmp_path / "bin" )
    ( fakebin / "curl" ).write_text( "#!/bin/sh\nexit 0\n" )
    ( fakebin / "curl" ).chmod( 0o755 )
    env = _env( tmp_path, expires=expires, fail=fail )
    env.update( LUPIN_ROOT=str( tree ), UNWARNED_PAUSE_SECS="0", LUPIN_DB_GRANTS_CHECK="skip" )
    if skip: env[ "LUPIN_CLAUDE_LOGIN_CHECK" ] = "skip"
    return subprocess.run( [ "bash", BOUNCE, "--quiet" ], capture_output=True, text=True, env=env, timeout=60 )


def test_a_healthy_bounce_with_an_expired_login_warns_with_the_remedy_and_still_exits_zero( tmp_path ):
    done = _bounce( tmp_path, expires=EXPIRED )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "bounced lupin-rest-dev" in done.stdout
    assert "claude login in lupin-rest-dev expired" in done.stderr and _iso( EXPIRED ) in done.stderr
    assert "docker exec -it lupin-rest-dev claude /login" in done.stderr


def test_a_healthy_bounce_with_a_valid_login_prints_no_warning( tmp_path ):
    done = _bounce( tmp_path, expires=FAR_AHEAD )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "claude login" not in done.stderr and "claude /login" not in done.stdout + done.stderr


def test_a_bounce_whose_expiry_read_fails_warns_and_still_exits_zero( tmp_path ):
    done = _bounce( tmp_path, fail=True )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "could not be read" in done.stderr and "bounced lupin-rest-dev" in done.stdout


def test_the_skip_variable_turns_the_login_check_off_and_reads_nothing( tmp_path ):
    done = _bounce( tmp_path, expires=EXPIRED, skip=True )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "claude login" not in done.stderr
    assert "expiresAt" not in _docker_log( tmp_path )


def test_every_bounce_test_that_stubs_docker_for_the_grants_step_skips_the_login_check_too():
    """A stubbed docker answers the login step with an empty read, so those tests must skip it."""
    tests = sorted( glob.glob( os.path.join( ROOT, "src/tests/unit/test_bounce_dev_server*.py" ) ) )
    sets_grants = [ t for t in tests if "LUPIN_DB_GRANTS_CHECK" in open( t, encoding="utf-8" ).read() ]
    assert len( sets_grants ) >= 4, sets_grants
    missing = [ os.path.basename( t ) for t in sets_grants if "LUPIN_CLAUDE_LOGIN_CHECK" not in open( t, encoding="utf-8" ).read() ]
    assert missing == [], missing
