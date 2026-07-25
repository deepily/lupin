"""
Unit tests for cosa.utils.secret_drift.

Guards the check that would have caught task-store row 30198303 — the model
server's Secret Manager copy sitting 8 months stale behind the app-side key
file, producing a silent 401 nobody could see until a user pressed the mic.

The tests inject `runner`, so nothing here touches gcloud, the network, or a
real secret. The "unknown is not a pass" cases are the ones that matter most:
an unreadable side must NOT be reported as agreement.
"""

import subprocess

import pytest

from cosa.utils.secret_drift import (
    sha256_of,
    fingerprint_key_file,
    fingerprint_secret_manager,
    check_key_drift,
    format_report,
    quick_smoke_test,
)


class _Result:
    """Minimal stand-in for subprocess.CompletedProcess."""
    def __init__( self, returncode=0, stdout="" ):
        self.returncode = returncode
        self.stdout     = stdout


def _runner_returning( returncode=0, stdout="" ):
    return lambda *args, **kwargs: _Result( returncode, stdout )


def _runner_raising( exc ):
    def _raise( *args, **kwargs ):
        raise exc
    return _raise


# ── sha256_of ────────────────────────────────────────────────────────────────

def test_sha256_of_is_stable_and_hex():
    digest = sha256_of( "ck_live_abc" )
    assert len( digest ) == 64
    assert digest == sha256_of( "ck_live_abc" )
    assert all( c in "0123456789abcdef" for c in digest )


def test_sha256_of_distinguishes_different_inputs():
    assert sha256_of( "a" ) != sha256_of( "b" )


# ── fingerprint_key_file ─────────────────────────────────────────────────────

def test_fingerprint_key_file_hashes_stripped_contents( tmp_path ):
    """A trailing newline must NOT register as drift — both readers strip."""
    with_nl    = tmp_path / "with_nl";    with_nl.write_text( "ck_live_abc\n" )
    without_nl = tmp_path / "without_nl"; without_nl.write_text( "ck_live_abc" )
    assert fingerprint_key_file( str( with_nl ) ) == fingerprint_key_file( str( without_nl ) )
    assert fingerprint_key_file( str( with_nl ) ) == sha256_of( "ck_live_abc" )


def test_fingerprint_key_file_returns_none_when_absent( tmp_path ):
    assert fingerprint_key_file( str( tmp_path / "nope" ) ) is None


def test_fingerprint_key_file_returns_none_on_undecodable_bytes( tmp_path ):
    binary = tmp_path / "binary"
    binary.write_bytes( b"\xff\xfe\x00\x80" )
    assert fingerprint_key_file( str( binary ) ) is None


# ── fingerprint_secret_manager ───────────────────────────────────────────────

def test_fingerprint_secret_manager_hashes_stripped_value():
    got = fingerprint_secret_manager( "sid", "proj", runner=_runner_returning( 0, "ck_live_abc\n" ) )
    assert got == sha256_of( "ck_live_abc" )


def test_fingerprint_secret_manager_builds_the_expected_command():
    seen = {}
    def _capture( cmd, **kwargs ):
        seen[ "cmd" ]    = cmd
        seen[ "kwargs" ] = kwargs
        return _Result( 0, "v" )
    fingerprint_secret_manager( "my-secret", "my-proj", version="7", runner=_capture )
    assert seen[ "cmd" ] == [
        "gcloud", "secrets", "versions", "access", "7",
        "--secret=my-secret", "--project=my-proj",
    ]
    assert seen[ "kwargs" ][ "capture_output" ] is True
    assert seen[ "kwargs" ][ "text" ] is True


@pytest.mark.parametrize( "exc", [
    FileNotFoundError( "no gcloud" ),
    OSError( "boom" ),
    subprocess.TimeoutExpired( cmd="gcloud", timeout=90 ),
] )
def test_fingerprint_secret_manager_returns_none_on_runner_failure( exc ):
    assert fingerprint_secret_manager( "sid", "proj", runner=_runner_raising( exc ) ) is None


def test_fingerprint_secret_manager_returns_none_on_nonzero_exit():
    assert fingerprint_secret_manager( "sid", "proj", runner=_runner_returning( 1, "denied" ) ) is None


def test_fingerprint_secret_manager_returns_none_on_empty_stdout():
    assert fingerprint_secret_manager( "sid", "proj", runner=_runner_returning( 0, "" ) ) is None


# ── check_key_drift ──────────────────────────────────────────────────────────

@pytest.fixture
def key_file( tmp_path ):
    p = tmp_path / "notification-api-claude-code-dev"
    p.write_text( "ck_live_abc\n" )
    return str( p )


def test_check_key_drift_match( key_file ):
    r = check_key_drift( key_file, "sid", "proj", runner=_runner_returning( 0, "ck_live_abc" ) )
    assert r[ "status" ] == "match"
    assert r[ "key_file_sha256" ] == r[ "secret_sha256" ]
    assert "OK" in r[ "detail" ]


def test_check_key_drift_detects_the_30198303_failure( key_file ):
    """The real defect: both sides readable, both well-formed, DIFFERENT."""
    r = check_key_drift( key_file, "sid", "proj", runner=_runner_returning( 0, "ck_live_stale" ) )
    assert r[ "status" ] == "drift"
    assert r[ "key_file_sha256" ] != r[ "secret_sha256" ]
    assert "401" in r[ "detail" ]
    assert "gcloud secrets versions add sid" in r[ "detail" ]


def test_check_key_drift_unknown_when_key_file_missing( tmp_path ):
    r = check_key_drift( str( tmp_path / "gone" ), "sid", "proj", runner=_runner_returning( 0, "x" ) )
    assert r[ "status" ] == "unknown"
    assert r[ "key_file_sha256" ] is None
    assert "gone" in r[ "detail" ]


def test_check_key_drift_unknown_when_secret_unreadable( key_file ):
    r = check_key_drift( key_file, "sid", "proj", runner=_runner_returning( 1, "" ) )
    assert r[ "status" ] == "unknown"
    assert r[ "secret_sha256" ] is None
    assert "Secret Manager (sid:latest)" in r[ "detail" ]


def test_check_key_drift_unknown_names_both_sides_when_both_unreadable( tmp_path ):
    r = check_key_drift( str( tmp_path / "gone" ), "sid", "proj", runner=_runner_returning( 1, "" ) )
    assert r[ "status" ] == "unknown"
    assert "gone" in r[ "detail" ] and "sid:latest" in r[ "detail" ]
    assert " and " in r[ "detail" ]


def test_check_key_drift_unknown_is_not_reported_as_a_pass( tmp_path ):
    """Regression guard: 'could not check' must never read as agreement."""
    r = check_key_drift( str( tmp_path / "gone" ), "sid", "proj", runner=_runner_returning( 1, "" ) )
    assert r[ "status" ] != "match"
    assert "NOT a pass" in r[ "detail" ]


@pytest.mark.parametrize( "secret_value,expected_status", [
    ( "ck_live_abc",   "match"   ),   # match branch
    ( "ck_live_stale", "drift"   ),   # drift branch
] )
def test_check_key_drift_never_leaks_plaintext( key_file, secret_value, expected_status ):
    """
    EVERY branch must be leak-free, not just the interesting one.

    The single-branch version of this test passed while the MATCH branch was
    mutated to interpolate the raw key into `detail` — 100% line+branch
    coverage did not reveal the hole, because coverage asks "was this line
    executed", not "would a leak here be noticed". Found by mutation probe
    M4, 2026-07-25.
    """
    r = check_key_drift( key_file, "sid", "proj", runner=_runner_returning( 0, secret_value ) )
    assert r[ "status" ] == expected_status
    blob = repr( r ) + format_report( r )
    assert "ck_live_abc"   not in blob
    assert "ck_live_stale" not in blob


def test_check_key_drift_unknown_branch_never_leaks_plaintext( key_file ):
    """The unknown branch echoes the key PATH; it must not echo the key VALUE."""
    r = check_key_drift( key_file, "sid", "proj", runner=_runner_returning( 1, "" ) )
    assert r[ "status" ] == "unknown"
    blob = repr( r ) + format_report( r )
    assert "ck_live_abc" not in blob


def test_check_key_drift_passes_version_through( key_file ):
    r = check_key_drift( key_file, "sid", "proj", version="3", runner=_runner_returning( 0, "ck_live_abc" ) )
    assert r[ "version" ] == "3"


# ── format_report ────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "status,marker", [
    ( "match", "[OK]" ), ( "drift", "[FAIL]" ), ( "unknown", "[WARN]" ), ( "bogus", "[????]" ),
] )
def test_format_report_marker_per_status( status, marker ):
    report = {
        "status": status, "detail": "d", "key_path": "/k", "secret_id": "s",
    }
    assert format_report( report ).startswith( marker )


def test_format_report_includes_both_authorities():
    report = { "status": "drift", "detail": "d", "key_path": "/k", "secret_id": "s" }
    line = format_report( report )
    assert "/k" in line and "s" in line


# ── inline smoke ─────────────────────────────────────────────────────────────

def test_quick_smoke_test_runs_clean():
    quick_smoke_test()
