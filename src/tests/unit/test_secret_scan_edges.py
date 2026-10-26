"""
Edge guards for `src/scripts/secret_scan.py`.

Each case holds one decision the main test file leaves open.
Which blobs count as key material. Which values are only references.
Where a wrapped value ends. How the batch blob reader treats a bad spec.
"""

import subprocess
import sys

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )

import secret_scan


def test_a_list_holding_a_pem_header_is_key_material():
    assert secret_scan._carries_key_material( '["' + "-----" + "BEGIN PRIVATE KEY" + "-----" + '"]' ) is True


def test_a_blob_with_a_credential_field_and_a_long_base64_run_is_key_material():
    blob = '{"password": "' + "A" * 30 + '"}'
    assert secret_scan._carries_key_material( blob ) is True


def test_a_short_blob_and_a_short_list_are_not_key_material():
    assert secret_scan._carries_key_material( '{"a": "b"}' ) is False
    assert secret_scan._carries_key_material( '["a"]' ) is False


def test_a_double_slash_value_is_a_reference_only_when_it_ends_like_a_file():
    """A scheme-less URL path is judged by its suffix, not by the slash alone."""
    assert secret_scan._looks_like_a_reference( "//host/cfg.json" ) == "path"
    assert secret_scan._looks_like_a_reference( "//host/share/x" ) is None


def test_a_wrapped_value_stops_at_a_blank_line():
    joined, spaced, end = secret_scan._gather_block( [ "key: |", "   aa", "", "   bb" ], 0 )
    assert ( joined, spaced, end ) == ( "aa", "aa", 2 )


def test_a_wrapped_value_stops_at_the_first_line_not_indented_past_the_key():
    joined, spaced, end = secret_scan._gather_block( [ "  key: |", "    aa", "  other: 1" ], 0 )
    assert ( joined, spaced, end ) == ( "aa", "aa", 2 )


def test_a_wrapped_value_stops_at_a_whitespace_only_line_even_when_indented_past_the_key():
    """Such a line has indent past the key, so only the blank-line check ends the block."""
    joined, spaced, end = secret_scan._gather_block( [ "k: |", "  a", "      ", "  b" ], 0 )
    assert ( joined, spaced, end ) == ( "a", "a", 2 )


def test_batch_read_of_no_specs_yields_nothing_and_starts_no_process( monkeypatch ):
    monkeypatch.setattr( subprocess, "Popen", lambda *a, **k: pytest.fail( "no process for no specs" ) )
    assert list( secret_scan._batch_read( [ ] ) ) == [ ]


def test_batch_read_skips_a_spec_git_cannot_resolve_and_keeps_order( tmp_path ):
    def git( *args ):
        subprocess.run( [ "git", "-C", str( tmp_path ), *args ], check=True, capture_output=True )
    git( "init", "-q" )
    git( "config", "user.email", "g@example.com" )
    git( "config", "user.name", "g" )
    ( tmp_path / "a.txt" ).write_text( "alpha" )
    ( tmp_path / "b.txt" ).write_text( "beta" )
    git( "add", "-A" )
    git( "commit", "-q", "-m", "x" )
    got = list( secret_scan._batch_read( [ "HEAD:a.txt", "HEAD:nope.txt", "HEAD:b.txt" ], cwd=str( tmp_path ) ) )
    assert got == [ ( "HEAD:a.txt", "alpha" ), ( "HEAD:b.txt", "beta" ) ]


def test_batch_read_stops_at_a_header_with_no_line_end_and_keeps_what_it_read( monkeypatch ):
    """A cut-off reply must not turn its dangling header into a blob that was never read."""
    class _Proc:
        def __init__( self, *a, **k ): pass
        def communicate( self, _in ): return b"HEAD:a.txt blob 5\nalpha\nHEAD:b.txt blob 99999", None
    monkeypatch.setattr( subprocess, "Popen", _Proc )
    assert list( secret_scan._batch_read( [ "HEAD:a.txt", "HEAD:b.txt" ] ) ) == [ ( "HEAD:a.txt", "alpha" ) ]
