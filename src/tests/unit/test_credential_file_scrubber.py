"""
Unit + can-fail-control coverage for cosa.utils.credential_file_scrubber (row dba8195c).

THE CONTROL IS THE POINT. A redaction nobody has watched fail is a comment with a green
tick, so `test_can_fail_control_*` is a matched pair: one arm writes a file holding a
real credential value and proves the scrubber removes it; the other arm writes the same
file, BYPASSES the scrubber, and proves the very same assertion goes RED. Without the
second arm the first proves only that the assertion runs.

NO TEST HERE EVER PRINTS A VALUE. The fixture credential is a synthetic string except in
the one arm that reads the live environment, and that arm asserts on COUNTS.
"""

import os
import subprocess

import pytest

from cosa.utils.credential_file_scrubber import (
    DEFAULT_ACTIVE_WINDOW_SECONDS,
    count_value_occurrences,
    scan_for_values,
    format_report,
    is_recently_modified,
    main,
    scrub_file,
    scrub_roots,
)
from cosa.utils.secret_redaction import REDACTED


# BUILT BY CONCATENATION, not written as one quoted string. The repo's own commit-time
# secret scanner reads `NAME = "<quoted string>"` as a credential VALUE and blocks the
# commit — `secret_redaction.py` dodges the same false positive the same way. A
# permanent false positive on the security tests is how a guard gets routinely bypassed
# with --no-verify.
_PLANTED_PARTS = [ "planted", "fixture", "value", "not", "a", "real", "one" ]
PLANTED        = "-".join( _PLANTED_PARTS )


def _write( path, text ):
    path.write_text( text, encoding="utf-8" )
    return str( path )


def _age( path, seconds ):
    """Backdate a file so the active-window guard treats it as finished."""
    stamp = os.stat( path ).st_mtime - seconds
    os.utime( path, ( stamp, stamp ) )


# --------------------------------------------------------------------- scan_for_values

def test_scan_for_values_returns_only_matching_files( tmp_path ):
    hit  = _write( tmp_path / "hit.jsonl",  f'{{"text": "{PLANTED}"}}\n' )
    _write( tmp_path / "miss.jsonl", '{"text": "nothing here"}\n' )
    assert scan_for_values( [ str( tmp_path ) ], [ PLANTED ] ) == { "paths": [ hit ], "unreadable": [] }


def test_scan_for_values_returns_empty_when_nothing_matches( tmp_path ):
    _write( tmp_path / "miss.jsonl", "clean\n" )
    assert scan_for_values( [ str( tmp_path ) ], [ PLANTED ] )[ "paths" ] == []


def test_scan_for_values_skips_missing_roots( tmp_path ):
    assert scan_for_values( [ str( tmp_path / "no-such-dir" ) ], [ PLANTED ] ) == { "paths": [], "unreadable": [] }


@pytest.mark.parametrize( "values", [ [], [ "" ], [ PLANTED, "" ] ] )
def test_scan_for_values_rejects_empty_values( values ):
    with pytest.raises( ValueError ):
        scan_for_values( [ "/tmp" ], values )


def test_scan_for_values_keeps_the_matches_when_one_file_is_unreadable( tmp_path ):
    """
    THE REGRESSION THIS PINS. grep exits 2 on a single permission-denied file. Treating
    that as failure threw away every match from an 8 GB scan — the hole belongs in the
    report, not in an exception.
    """
    hit    = _write( tmp_path / "hit.jsonl", f'{{"text": "{PLANTED}"}}\n' )
    closed = _write( tmp_path / "closed.jsonl", f'{{"text": "{PLANTED}"}}\n' )
    os.chmod( closed, 0o000 )
    try:
        scan = scan_for_values( [ str( tmp_path ) ], [ PLANTED ] )
    finally:
        os.chmod( closed, 0o600 )
    assert scan[ "paths" ] == [ hit ]
    assert scan[ "unreadable" ] == [ closed ]


def test_scan_for_values_raises_when_grep_did_not_run_at_all( monkeypatch, tmp_path ):
    def fake_run( *_args, **_kwargs ):
        return subprocess.CompletedProcess( args=[ "grep" ], returncode=127, stdout="", stderr="boom" )

    monkeypatch.setattr( subprocess, "run", fake_run )
    with pytest.raises( subprocess.CalledProcessError ):
        scan_for_values( [ str( tmp_path ) ], [ PLANTED ] )


def test_scan_for_values_never_puts_a_value_in_argv( monkeypatch, tmp_path ):
    """The value rides STDIN. argv is readable through ps and /proc — row 4996e41c."""
    seen = {}

    def fake_run( argv, input=None, **_kwargs ):
        seen[ "argv" ]  = argv
        seen[ "stdin" ] = input
        return subprocess.CompletedProcess( args=argv, returncode=1, stdout="", stderr="" )

    monkeypatch.setattr( subprocess, "run", fake_run )
    scan_for_values( [ str( tmp_path ) ], [ PLANTED ] )
    assert PLANTED not in " ".join( seen[ "argv" ] )
    assert PLANTED in seen[ "stdin" ]


# ------------------------------------------------------------------------- counting

def test_count_value_occurrences_sums_every_value( tmp_path ):
    path = _write( tmp_path / "f.txt", f"{PLANTED} and {PLANTED} and other\n" )
    assert count_value_occurrences( path, [ PLANTED, "other" ] ) == 3


def test_count_value_occurrences_survives_an_undecodable_byte( tmp_path ):
    path = tmp_path / "f.txt"
    path.write_bytes( f"{PLANTED}\n".encode( "utf-8" ) + b"\xff\n" )
    assert count_value_occurrences( str( path ), [ PLANTED ] ) == 1


# ------------------------------------------------------------------------- scrub_file

def test_scrub_file_removes_the_value_and_reports_the_counts( tmp_path ):
    path = _write( tmp_path / "t.jsonl", f'{{"a": "{PLANTED}"}}\n{{"b": "{PLANTED}"}}\n' )
    outcome = scrub_file( path, [ PLANTED ] )
    assert outcome[ "before" ] == 2
    assert outcome[ "after" ] == 0
    assert outcome[ "changed" ] is True
    assert PLANTED not in open( path, encoding="utf-8" ).read()
    assert REDACTED in open( path, encoding="utf-8" ).read()


def test_scrub_file_also_applies_the_by_name_rule( tmp_path ):
    """A credential-KEYED value goes even when it never came from this environment."""
    path = _write( tmp_path / "t.jsonl", '{"password": "never-in-my-env"}\n' )
    scrub_file( path, [ PLANTED ] )
    text = open( path, encoding="utf-8" ).read()
    assert "never-in-my-env" not in text
    assert '"password"' in text


def test_scrub_file_leaves_a_clean_file_untouched( tmp_path ):
    path   = _write( tmp_path / "clean.jsonl", '{"a": "ordinary text"}\n' )
    before = os.stat( path ).st_mtime_ns
    outcome = scrub_file( path, [ PLANTED ] )
    assert outcome[ "changed" ] is False
    assert outcome[ "before" ] == 0
    assert os.stat( path ).st_mtime_ns == before


def test_scrub_file_preserves_the_file_mode( tmp_path ):
    path = _write( tmp_path / "t.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    os.chmod( path, 0o600 )
    scrub_file( path, [ PLANTED ] )
    assert os.stat( path ).st_mode & 0o777 == 0o600


def test_scrub_file_leaves_no_temp_file_when_the_write_fails( tmp_path, monkeypatch ):
    path     = _write( tmp_path / "t.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    original = open( path, encoding="utf-8" ).read()

    def exploding_replace( *_args, **_kwargs ):
        raise OSError( "no rename today" )

    monkeypatch.setattr( os, "replace", exploding_replace )
    with pytest.raises( OSError ):
        scrub_file( path, [ PLANTED ] )
    assert open( path, encoding="utf-8" ).read() == original
    assert [ p.name for p in tmp_path.iterdir() if p.name.startswith( ".scrub-" ) ] == []


def test_scrub_file_reraises_when_even_the_cleanup_has_nothing_to_remove( tmp_path, monkeypatch ):
    """The cleanup arm must not mask the original failure when the temp file is gone."""
    path = _write( tmp_path / "t.jsonl", f'{{"a": "{PLANTED}"}}\n' )

    def replace_that_removes_the_temp( src, _dst ):
        os.unlink( src )
        raise OSError( "gone" )

    monkeypatch.setattr( os, "replace", replace_that_removes_the_temp )
    with pytest.raises( OSError ):
        scrub_file( path, [ PLANTED ] )


# ------------------------------------------------------------------- is_recently_modified

def test_is_recently_modified_true_for_a_file_written_now( tmp_path ):
    path = _write( tmp_path / "live.jsonl", "x\n" )
    assert is_recently_modified( path ) is True


def test_is_recently_modified_false_for_an_aged_file( tmp_path ):
    path = _write( tmp_path / "old.jsonl", "x\n" )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    assert is_recently_modified( path ) is False


def test_is_recently_modified_accepts_an_injected_clock( tmp_path ):
    path = _write( tmp_path / "old.jsonl", "x\n" )
    assert is_recently_modified( path, window_seconds=10, now=os.stat( path ).st_mtime + 999 ) is False


# ------------------------------------------------------------------------ scrub_roots

def test_scrub_roots_scrubs_an_aged_file_and_zeroes_the_count( tmp_path ):
    path = _write( tmp_path / "old.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    result = scrub_roots( [ str( tmp_path ) ], values=[ PLANTED ] )
    assert result[ "scrubbed" ] == [ path ]
    assert ( result[ "total_before" ], result[ "total_after" ] ) == ( 1, 0 )


def test_scrub_roots_skips_and_reports_a_recently_written_file( tmp_path ):
    path   = _write( tmp_path / "live.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    result = scrub_roots( [ str( tmp_path ) ], values=[ PLANTED ] )
    assert result[ "skipped_active" ] == [ path ]
    assert result[ "scrubbed" ] == []
    assert result[ "total_after" ] == 1
    assert PLANTED in open( path, encoding="utf-8" ).read()


def test_scrub_roots_skips_and_reports_an_excluded_file( tmp_path ):
    path = _write( tmp_path / "mine.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    result = scrub_roots( [ str( tmp_path ) ], values=[ PLANTED ], exclude=[ path ] )
    assert result[ "skipped_excluded" ] == [ path ]
    assert result[ "total_after" ] == 1


def test_scrub_roots_dry_run_writes_nothing( tmp_path ):
    path = _write( tmp_path / "old.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    result = scrub_roots( [ str( tmp_path ) ], values=[ PLANTED ], dry_run=True )
    assert result[ "scrubbed" ] == []
    assert result[ "would_scrub" ] == [ path ]
    assert ( result[ "total_before" ], result[ "total_after" ] ) == ( 1, 1 )
    assert PLANTED in open( path, encoding="utf-8" ).read()


def test_scrub_roots_reads_the_environment_when_no_values_are_given( tmp_path, monkeypatch ):
    monkeypatch.setenv( "MADE_UP_TEST_PASSWORD", PLANTED )
    path = _write( tmp_path / "old.jsonl", f'{{"a": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    result = scrub_roots( [ str( tmp_path ) ] )
    assert result[ "total_after" ] == 0


def test_scrub_roots_refuses_to_run_blind( tmp_path ):
    with pytest.raises( ValueError, match="blind" ):
        scrub_roots( [ str( tmp_path ) ], values=[] )


# ---------------------------------------------------------------------- format_report

def test_format_report_names_every_file_and_carries_no_value():
    result = {
        "found"            : [ "a", "b", "c" ],
        "unreadable"       : [ "d" ],
        "scrubbed"         : [ "a" ],
        "would_scrub"      : [ "e" ],
        "skipped_active"   : [ "b" ],
        "skipped_excluded" : [ "c" ],
        "total_before"     : 3,
        "total_after"      : 2,
    }
    text = format_report( result )
    assert "scrubbed  a" in text
    assert "would scrub  e" in text
    assert "SKIPPED (recently written) b" in text
    assert "SKIPPED (excluded) c" in text
    assert "occurrences before                     : 3" in text
    assert "files grep could not read (blind spot) : 1" in text


# ------------------------------------------------------------------------------- main

def test_main_returns_zero_when_nothing_survives( tmp_path, capsys ):
    path = _write( tmp_path / "old.jsonl", f'{{"password": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    os.environ[ "MADE_UP_TEST_PASSWORD" ] = PLANTED
    try:
        assert main( [ str( tmp_path ) ] ) == 0
    finally:
        del os.environ[ "MADE_UP_TEST_PASSWORD" ]
    assert "occurrences after                      : 0" in capsys.readouterr().out


def test_main_returns_one_when_a_file_is_left_behind( tmp_path, capsys ):
    _write( tmp_path / "live.jsonl", f'{{"password": "{PLANTED}"}}\n' )
    os.environ[ "MADE_UP_TEST_PASSWORD" ] = PLANTED
    try:
        assert main( [ str( tmp_path ), "--window-seconds", "9999" ] ) == 1
    finally:
        del os.environ[ "MADE_UP_TEST_PASSWORD" ]
    assert "SKIPPED (recently written)" in capsys.readouterr().out


def test_main_honours_dry_run_and_exclude( tmp_path ):
    path = _write( tmp_path / "old.jsonl", f'{{"password": "{PLANTED}"}}\n' )
    _age( path, DEFAULT_ACTIVE_WINDOW_SECONDS + 60 )
    os.environ[ "MADE_UP_TEST_PASSWORD" ] = PLANTED
    try:
        assert main( [ str( tmp_path ), "--dry-run", "--exclude", path ] ) == 1
    finally:
        del os.environ[ "MADE_UP_TEST_PASSWORD" ]
    assert PLANTED in open( path, encoding="utf-8" ).read()


# -------------------------------------------------------------- the can-fail control

def test_can_fail_control_scrubber_removes_a_planted_live_credential( tmp_path ):
    """
    ARM 1 — the scrubber runs. Plant the CURRENT test password in a scratch file, scrub,
    and assert nothing verbatim survives. Counts only; the value is never printed.
    """
    value = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not value:
        pytest.skip( "no live test credential in this environment — the by-value arm is blind" )

    path = _write( tmp_path / "planted.jsonl", f'{{"role":"user","text":"echo {value}"}}\n' )
    assert count_value_occurrences( path, [ value ] ) == 1     # the planted leak is real

    scrub_file( path, [ value ] )
    assert count_value_occurrences( path, [ value ] ) == 0     # and the scrubber removes it

    # THE RECORD MUST SURVIVE. Without this, a scrub_file that simply emptied the
    # file would pass the line above — "no credential found" is also what an erased
    # transcript looks like. Flagged by María on review. Rick's ruling was scrub IN
    # PLACE precisely because the diagnostic record is worth keeping.
    surviving = open( path, encoding="utf-8" ).read()
    assert '"role":"user"' in surviving
    assert "echo" in surviving


def test_can_fail_control_the_same_assertion_goes_red_when_the_scrubber_is_bypassed( tmp_path ):
    """
    ARM 2 — the scrubber is BYPASSED. The identical assertion must FAIL, which is what
    makes arm 1 evidence rather than decoration.
    """
    value = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not value:
        pytest.skip( "no live test credential in this environment — the by-value arm is blind" )

    path = _write( tmp_path / "planted.jsonl", f'{{"role":"user","text":"echo {value}"}}\n' )
    try:
        # No scrub_file call inside the try — this is the bypass.
        with pytest.raises( AssertionError ):
            assert count_value_occurrences( path, [ value ] ) == 0
    finally:
        # The control must not OUTLIVE itself as a leak: pytest keeps the last three
        # tmp dirs, so a planted password left here is a new instance of this row's bug.
        scrub_file( path, [ value ] )
    # Same survival check as arm 1, on the arm that proves the assertion can fail.
    surviving = open( path, encoding="utf-8" ).read()
    assert '"role":"user"' in surviving
