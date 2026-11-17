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


# ── create_table_with_indexes ─────────────────────────────────────────────────────────────

CREATE_WIDGETS = "CREATE TABLE widgets ( id INTEGER PRIMARY KEY, name TEXT, size INTEGER )"
WIDGET_INDEXES = [ "CREATE INDEX idx_name ON widgets ( name )", "CREATE INDEX idx_size ON widgets ( size )" ]


class _Probe:
    """A connection the test can ask whether it was closed."""

    def __init__( self ):
        self.conn   = sqlite3.connect( ":memory:" )
        self.closed = False

    def __call__( self ):
        return self

    def cursor( self ): return self.conn.cursor()
    def commit( self ): self.conn.commit()

    def close( self ):
        self.closed = True
        self.conn.close()


def _ok( conn ):
    return h.validate_table( conn.conn, "widgets", 3, 2 )


def test_a_good_create_prints_each_step_with_the_marks_it_was_given_and_closes_the_connection( capsys ):
    probe = _Probe()
    assert h.create_table_with_indexes( probe, "widgets", CREATE_WIDGETS, WIDGET_INDEXES, _ok, table_done="    ✓ Table created", index_mark="✓ " ) is True
    assert capsys.readouterr().out == (
        "  Creating widgets table...\n    ✓ Table created\n  Creating indexes...\n    ✓ Index 1/2 created\n    ✓ Index 2/2 created\n"
        "  Validating schema...\n  ✓ Schema validated: 3 fields, 2 indexes\n" )
    assert probe.closed


def test_without_marks_the_table_line_and_the_tick_are_left_out_and_the_precheck_runs_first( capsys ):
    calls = []
    assert h.create_table_with_indexes( _Probe(), "widgets", CREATE_WIDGETS, WIDGET_INDEXES, _ok, precheck=lambda cursor: calls.append( cursor ) ) is True
    out = capsys.readouterr().out
    assert len( calls ) == 1 and "  Creating widgets table...\n  Creating indexes...\n    Index 1/2 created\n" in out and "Table created" not in out and "✓ Index" not in out


def test_a_failing_validation_returns_false_and_says_why_on_stderr( capsys ):
    probe = _Probe()
    assert h.create_table_with_indexes( probe, "widgets", CREATE_WIDGETS, WIDGET_INDEXES, lambda conn: { "success": False, "error": "planted" } ) is False
    assert "  ✗ Schema validation failed: planted\n" == capsys.readouterr().err and probe.closed


def test_a_sqlite_error_and_any_other_error_are_reported_as_false_and_the_connection_still_closes( capsys ):
    probe = _Probe()
    assert h.create_table_with_indexes( probe, "widgets", "CREATE NONSENSE", [], _ok ) is False
    assert "✗ SQLite error:" in capsys.readouterr().err and probe.closed

    probe = _Probe()
    def refuse( cursor ): raise RuntimeError( "no users" )
    assert h.create_table_with_indexes( probe, "widgets", CREATE_WIDGETS, [], _ok, precheck=refuse ) is False
    assert "  ✗ Unexpected error: no users\n" == capsys.readouterr().err and probe.closed


def test_a_connect_that_raises_is_reported_and_there_is_nothing_to_close( capsys ):
    def no_connection(): raise RuntimeError( "no database" )
    assert h.create_table_with_indexes( no_connection, "widgets", CREATE_WIDGETS, [], _ok ) is False
    assert "  ✗ Unexpected error: no database\n" == capsys.readouterr().err


# ── parse_service_account_args and print_key_report ───────────────────────────────────────

def test_the_service_account_arguments_default_and_take_each_option( monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "x" ] )
    args = h.parse_service_account_args( "desc", "epi" )
    assert ( args.email, args.description, args.env ) == ( "claude.code@deepily.ai", "", "dev" )

    monkeypatch.setattr( sys, "argv", [ "x", "--email=a@b.c", "--description=CI key", "--env=prod" ] )
    args = h.parse_service_account_args( "desc", "epi" )
    assert ( args.email, args.description, args.env ) == ( "a@b.c", "CI key", "prod" )


def test_an_unknown_environment_is_refused_and_help_prints_the_epilog_as_written( monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "x", "--env=qa" ] )
    with pytest.raises( SystemExit ) as refused: h.parse_service_account_args( "desc", "epi" )
    assert refused.value.code == 2 and "invalid choice: 'qa'" in capsys.readouterr().err

    monkeypatch.setattr( sys, "argv", [ "x", "--help" ] )
    with pytest.raises( SystemExit ) as helped: h.parse_service_account_args( "My description", "\nExamples:\n  line one\n    line two" )
    out = capsys.readouterr().out
    assert helped.value.code == 0 and "My description" in out and "\nExamples:\n  line one\n    line two" in out


def test_the_key_report_prints_banner_account_key_next_steps_and_notes_in_that_order( capsys ):
    h.print_key_report( "DONE", 10, "-", [ "Account: a" ], "KEY", "/f", [ "  1. one", "", "  2. two" ], [ "  - note" ] )
    assert capsys.readouterr().out == (
        "==========\n  DONE\n==========\n\nAccount: a\n\n🔑 API Key (save this - shown only once):\n----------\nKEY\n----------\n\n"
        "Key saved to: /f\n\nNext steps:\n  1. one\n\n  2. two\n\n⚠️  IMPORTANT:\n  - note\n\n" )
