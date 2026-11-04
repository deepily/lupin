#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pins the helpers the one-off admin scripts share.

run_create_script owns the banners and exit codes of the table-creation scripts.
validate_table checks a table's shape. write_key_file writes the key file.
"""

import os
import sqlite3
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import pytest

from cosa.utils import admin_script_helpers as h


# ── run_create_script ─────────────────────────────────────────────────────────────────────

def test_a_true_create_prints_the_success_banner_and_returns_zero( capsys ):
    assert h.run_create_script( "Title", "Subtitle", "Thing created", lambda: True ) == 0

    out = capsys.readouterr().out
    assert out.startswith( "=" * 50 + "\n  Title\n  Subtitle\n" + "=" * 50 + "\n\n" )
    assert "  ✓ SUCCESS: Thing created" in out and "FAILED" not in out


def test_a_false_create_prints_the_failure_banner_and_returns_one( capsys ):
    assert h.run_create_script( "Title", "Subtitle", "Thing created", lambda: False ) == 1

    out = capsys.readouterr().out
    assert "  ✗ FAILED: See errors above" in out and "SUCCESS" not in out


def test_a_raising_create_returns_one_and_names_the_error_on_stderr( capsys ):
    def boom():
        raise RuntimeError( "disk gone" )

    assert h.run_create_script( "Title", "Subtitle", "Thing created", boom ) == 1

    err = capsys.readouterr().err
    assert "✗ FATAL ERROR: disk gone" in err and "RuntimeError" in err


# ── validate_table ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = sqlite3.connect( ":memory:" )
    c.execute( "CREATE TABLE widgets ( id INTEGER PRIMARY KEY, name TEXT, size INTEGER )" )
    c.execute( "CREATE INDEX idx_name ON widgets ( name )" )
    c.execute( "CREATE INDEX idx_size ON widgets ( size )" )
    yield c
    c.close()


def test_a_table_with_the_right_counts_validates( conn ):
    assert h.validate_table( conn, "widgets", 3, 2 ) == { "success": True, "field_count": 3, "index_count": 2 }


def test_a_missing_table_is_named( conn ):
    assert h.validate_table( conn, "gadgets", 3, 2 ) == { "success": False, "error": "Table 'gadgets' not found" }


def test_a_wrong_field_count_reports_the_count_found( conn ):
    result = h.validate_table( conn, "widgets", 4, 2 )

    assert result == { "success": False, "error": "Expected 4 fields, found 3", "field_count": 3 }


def test_a_wrong_index_count_reports_the_count_found_and_ignores_the_primary_key_index( conn ):
    result = h.validate_table( conn, "widgets", 3, 3 )

    assert result == { "success": False, "error": "Expected 3 indexes, found 2", "index_count": 2 }


def test_too_many_fields_is_a_mismatch_too( conn ):
    result = h.validate_table( conn, "widgets", 2, 2 )

    assert result == { "success": False, "error": "Expected 2 fields, found 3", "field_count": 3 }


def test_too_many_indexes_is_a_mismatch_too( conn ):
    result = h.validate_table( conn, "widgets", 3, 1 )

    assert result == { "success": False, "error": "Expected 1 indexes, found 2", "index_count": 2 }


def test_a_failing_query_is_reported_not_raised():
    closed = sqlite3.connect( ":memory:" )
    closed.close()

    result = h.validate_table( closed, "widgets", 3, 2 )

    assert result[ "success" ] is False and result[ "error" ].startswith( "Validation query failed: " )


# ── write_key_file ────────────────────────────────────────────────────────────────────────

def test_the_key_file_is_written_owner_only_under_conf_keys_and_announced( tmp_path, capsys ):
    path = h.write_key_file( str( tmp_path ), "ck_live_abc", "prod" )

    assert path == tmp_path / "src" / "conf" / "keys" / "notification-api-claude-code-prod"
    assert path.read_text() == "ck_live_abc\n"
    assert oct( path.stat().st_mode & 0o777 ) == "0o600"
    out = capsys.readouterr().out
    assert f"Wrote key to file: {path}" in out and "Permissions set: 600" in out


def test_an_existing_key_file_is_replaced_not_appended_to( tmp_path ):
    h.write_key_file( tmp_path, "ck_live_first", "dev" )
    path = h.write_key_file( tmp_path, "ck_live_second", "dev" )

    assert path.read_text() == "ck_live_second\n"
