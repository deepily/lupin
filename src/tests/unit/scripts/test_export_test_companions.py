"""
Tests for the companion export that feeds the VM's test database.

Every test names the change that reddens it. No database is opened: fetch is passed in, and the one
test of fetch_rows swaps the engine module for a recording fake.
"""

import json
import os
import re
import sys
import types

import pytest
import runpy

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import export_test_companions as mod


def _user( email, uid ):
    return { "id": uid, "email": email, "password_hash": "h'ash\\x", "created_at": "2026-01-01 00:00:00+00:00",
             "email_verified": True, "is_active": True, "roles": [ "user", "admin" ] }


def _all_users():
    return [ _user( e, f"00000000-0000-0000-0000-00000000000{i}" ) for i, e in enumerate( mod.COMPANION_EMAILS ) ]


def _key( n ):
    return { "id": f"10000000-0000-0000-0000-00000000000{n}", "user_id": "00000000-0000-0000-0000-000000000000", "key_hash": "kh",
             "description": "d", "is_active": True, "created_at": "2026-01-01 00:00:00+00:00", "last_used_at": None }


def _run( argv, users, keys ):
    out, err = [], []
    code = mod.main( argv, out=out.append, err=err.append, fetch=lambda: ( users, keys ) )
    return code, out, err


def test_sql_literal_doubles_quotes_and_leaves_backslashes_alone():
    assert mod.sql_literal( "a'b\\c" ) == "'a''b\\c'"


def test_the_script_upserts_users_protected_then_keys_in_one_transaction():
    code, out, err = _run( [], _all_users(), [ _key( 1 ) ] )
    sql = out[ 0 ]
    assert code == 0 and err == [] and len( out ) == 1
    assert sql.startswith( "BEGIN;\nINSERT INTO users" ) and sql.rstrip().endswith( "COMMIT;" )
    assert sql.index( "INSERT INTO users" ) < sql.index( "INSERT INTO api_keys" ) < sql.index( "COMMIT;" )
    assert "is_protected" in sql.split( "INSERT INTO api_keys" )[ 0 ] and "is_protected" not in sql.split( "INSERT INTO api_keys" )[ 1 ]
    assert "ON CONFLICT ( id ) DO UPDATE SET email = EXCLUDED.email, password_hash = EXCLUDED.password_hash" in sql


def test_the_json_payload_round_trips_the_rows_with_the_quote_escaped():
    users = _all_users()
    sql   = mod.build_sql( users, [] )
    lit   = re.search( r"jsonb_to_recordset\( '(.*)'::jsonb \)", sql, re.S ).group( 1 )
    assert json.loads( lit.replace( "''", "'" ) ) == users and "h''ash" in sql


def test_no_keys_means_no_keys_statement():
    assert "api_keys" not in mod.build_sql( _all_users(), [] )


def test_a_missing_primary_admin_exports_nothing_and_exits_2():
    users = [ u for u in _all_users() if u[ "email" ] != mod.ADMIN_EMAIL ]
    code, out, err = _run( [], users, [] )
    assert code == 2 and out == [] and any( "PRIMARY ADMIN" in e for e in err ) and any( mod.ADMIN_EMAIL in e for e in err )


def test_another_missing_companion_is_named_but_the_export_still_goes_out():
    users = [ u for u in _all_users() if u[ "email" ] != mod.COMPANION_EMAILS[ -1 ] ]
    code, out, err = _run( [], users, [] )
    assert code == 0 and len( out ) == 1 and err == [ f"companion {mod.COMPANION_EMAILS[ -1 ]} not found in the source database" ]


def test_check_prints_counts_and_no_row_value_and_exits_0_when_all_six_are_there():
    code, out, _ = _run( [ "--check" ], _all_users(), [ _key( 1 ), _key( 2 ) ] )
    assert code == 0 and out == [ "companions: users=6 api_keys=2 missing=[]" ]
    assert "ash" not in out[ 0 ] and "BEGIN" not in out[ 0 ]


def test_check_exits_2_and_lists_whoever_is_missing():
    users = [ u for u in _all_users() if u[ "email" ] != mod.COMPANION_EMAILS[ 2 ] ]
    code, out, _ = _run( [ "--check" ], users, [] )
    assert code == 2 and mod.COMPANION_EMAILS[ 2 ] in out[ 0 ] and "users=5" in out[ 0 ]


def test_main_reads_argv_from_the_process_when_none_is_given( monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "x", "--check" ] )
    out = []
    assert mod.main( out=out.append, fetch=lambda: ( _all_users(), [] ) ) == 0 and out[ 0 ].startswith( "companions:" )


def test_the_default_error_sink_writes_to_stderr( capsys ):
    mod.main( [], out=lambda t: None, fetch=lambda: ( [], [] ) )
    assert mod.ADMIN_EMAIL in capsys.readouterr().err


def test_fetch_rows_asks_for_the_companion_emails_only_and_returns_dicts( monkeypatch ):
    asked = []

    class _Result:
        def __init__( self, rows ): self.rows = rows
        def mappings( self ): return iter( self.rows )

    class _Conn:
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
        def execute( self, statement, params ):
            asked.append( ( str( statement ), params ) )
            return _Result( [ { "id": "u" } ] if "FROM users WHERE" in str( statement ) else [ { "id": "k" } ] )

    fake = types.ModuleType( "cosa.rest.db.database" )
    fake.engine = types.SimpleNamespace( connect=lambda: _Conn() )
    monkeypatch.setitem( sys.modules, "cosa.rest.db.database", fake )
    users, keys = mod.fetch_rows()
    assert users == [ { "id": "u" } ] and keys == [ { "id": "k" } ]
    assert [ p for _, p in asked ] == [ { "emails": mod.COMPANION_EMAILS } ] * 2
    assert all( s.lstrip().upper().startswith( "SELECT" ) for s, _ in asked )


def test_it_refuses_to_load_without_lupin_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT" )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        runpy.run_path( mod.__file__ )
