"""
The SQLite service-account creator, covered against a real SQLite file in tmp_path.

`test_create_service_account_write_key.py` holds `write_key_to_file`. This file covers the
rest: the import-time bootstrap, key generation, account creation, key storage and `main`.

No test touches the real auth database or `src/conf/keys/`. `get_auth_db_connection` is replaced
with a factory for a throwaway file, and `main` is driven with the four steps replaced.
Two tests use real bcrypt. A stub cannot show that the stored hash verifies against the issued key.
The module runs work at import time (the LUPIN_ROOT bootstrap). The tests that cover it
re-import it, and the monkeypatch restores `sys.modules` and `sys.path` afterwards.
"""

import importlib
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import create_service_account as mod


MODNAME = "create_service_account"

SCHEMA = """
CREATE TABLE users ( id TEXT PRIMARY KEY, email TEXT, password_hash TEXT, created_at TEXT,
                     roles TEXT, is_active INTEGER, email_verified INTEGER );
CREATE TABLE api_keys ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, key_hash TEXT,
                        description TEXT, created_at TEXT, is_active INTEGER );
"""


class _Tracked( sqlite3.Connection ):
    """A connection that counts its closes, so the tests can see the finally block run."""
    closes = 0

    def close( self ):
        type( self ).closes += 1
        super().close()


@pytest.fixture
def db( tmp_path, monkeypatch ):
    """A throwaway auth database; returns a function that opens a fresh row-factory connection."""
    path = str( tmp_path / "auth.db" )
    setup = sqlite3.connect( path )
    setup.executescript( SCHEMA )
    setup.commit()
    setup.close()
    _Tracked.closes = 0

    def connect():
        conn = sqlite3.connect( path, factory=_Tracked )
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr( mod, "get_auth_db_connection", connect )
    monkeypatch.setattr( mod, "hash_password", lambda plain: "hashed:" + plain )
    return connect


def _insert_user( connect, email, roles ):
    conn = connect()
    conn.execute( "INSERT INTO users ( id, email, roles ) VALUES ( 'u-1', ?, ? )", ( email, json.dumps( roles ) ) )
    conn.commit()
    conn.close()


def _rows( connect, sql ):
    conn = connect()
    rows = conn.execute( sql ).fetchall()
    conn.close()
    return rows


# ── the import-time bootstrap ─────────────────────────────────────────────────────────────

def test_a_missing_lupin_root_exits_one_and_says_how_to_set_it( monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )

    with pytest.raises( SystemExit ) as e:
        importlib.import_module( MODNAME )

    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "LUPIN_ROOT environment variable not set" in err
    assert "export LUPIN_ROOT=/path/to/project"      in err


def test_the_src_path_is_inserted_at_the_front_when_it_is_absent( tmp_path, monkeypatch ):
    monkeypatch.setattr( sys, "path", list( sys.path ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )
    wanted = os.path.join( str( tmp_path ), "src" )
    assert wanted not in sys.path

    importlib.import_module( MODNAME )

    assert sys.path[ 0 ] == wanted


def test_an_src_path_already_present_is_not_inserted_twice( monkeypatch ):
    monkeypatch.setattr( sys, "path", list( sys.path ) )
    here = os.path.join( os.environ[ "LUPIN_ROOT" ], "src" )
    if here not in sys.path:
        sys.path.insert( 0, here )
    before = sys.path.count( here )
    monkeypatch.delitem( sys.modules, MODNAME, raising=False )

    importlib.import_module( MODNAME )

    assert sys.path.count( here ) == before


# ── generate_api_key ──────────────────────────────────────────────────────────────────────

def test_the_api_key_carries_the_live_prefix_and_is_seventy_two_characters():
    key = mod.generate_api_key()

    assert key.startswith( "ck_live_" )
    assert len( key ) == 72


def test_two_generated_keys_are_never_the_same():
    assert mod.generate_api_key() != mod.generate_api_key()


# ── get_or_create_service_account ─────────────────────────────────────────────────────────

def test_a_new_service_account_is_created_with_the_service_role_and_a_hashed_placeholder( db, capsys ):
    user_id = mod.get_or_create_service_account( "svc@example.com", "desc" )

    ( row, ) = _rows( db, "SELECT * FROM users" )
    assert row[ "id" ] == user_id
    assert row[ "email" ] == "svc@example.com"
    assert json.loads( row[ "roles" ] ) == [ "service_account" ]
    assert row[ "is_active" ] == 1 and row[ "email_verified" ] == 1
    assert row[ "password_hash" ].startswith( "hashed:" )
    assert "Created service account: svc@example.com" in capsys.readouterr().out


def test_two_new_accounts_get_different_ids_and_different_placeholder_passwords( db ):
    first  = mod.get_or_create_service_account( "a@example.com", "" )
    second = mod.get_or_create_service_account( "b@example.com", "" )

    rows = { r[ "email" ]: r for r in _rows( db, "SELECT * FROM users" ) }
    assert first != second
    assert rows[ "a@example.com" ][ "password_hash" ] != rows[ "b@example.com" ][ "password_hash" ]


def test_an_existing_service_account_is_reused_rather_than_duplicated( db, capsys ):
    _insert_user( db, "svc@example.com", [ "service_account" ] )

    assert mod.get_or_create_service_account( "svc@example.com", "" ) == "u-1"
    assert len( _rows( db, "SELECT * FROM users" ) ) == 1
    assert "Using existing service account" in capsys.readouterr().out


def test_an_existing_human_account_is_refused_rather_than_given_an_api_key( db ):
    _insert_user( db, "human@example.com", [ "user" ] )

    with pytest.raises( RuntimeError, match="exists but is not a service account" ):
        mod.get_or_create_service_account( "human@example.com", "" )

    assert len( _rows( db, "SELECT * FROM users" ) ) == 1


def test_the_connection_is_closed_on_success_and_on_refusal( db ):
    mod.get_or_create_service_account( "svc@example.com", "" )
    assert _Tracked.closes == 1

    _insert_user( db, "human@example.com", [ "user" ] )
    closes_before = _Tracked.closes
    with pytest.raises( RuntimeError ):
        mod.get_or_create_service_account( "human@example.com", "" )

    assert _Tracked.closes == closes_before + 1


# ── store_api_key ─────────────────────────────────────────────────────────────────────────

def test_the_stored_hash_verifies_against_the_key_and_the_key_itself_is_not_stored( db, capsys ):
    import bcrypt

    key = mod.generate_api_key()
    key_id = mod.store_api_key( "u-1", key, "ci key" )

    ( row, ) = _rows( db, "SELECT * FROM api_keys" )
    assert row[ "id" ] == key_id
    assert row[ "user_id" ] == "u-1" and row[ "description" ] == "ci key" and row[ "is_active" ] == 1
    assert key not in row[ "key_hash" ]
    assert bcrypt.checkpw( key.encode( "utf-8" ), row[ "key_hash" ].encode( "utf-8" ) )
    assert f"key_id={key_id}" in capsys.readouterr().out


def test_a_second_key_gets_the_next_id_and_each_call_closes_its_connection( db ):
    first  = mod.store_api_key( "u-1", "ck_live_one", "" )
    second = mod.store_api_key( "u-1", "ck_live_two", "" )

    assert second == first + 1
    assert _Tracked.closes == 2


# ── main ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wired( monkeypatch, tmp_path ):
    """Replace the four steps with recorders; returns the list of calls in the order made."""
    calls = []
    key_file = tmp_path / "key-file"

    def get_or_create( email, description ):
        calls.append( ( "account", email, description ) )
        return "u-9"

    def store( user_id, api_key, description ):
        calls.append( ( "store", user_id, api_key, description ) )
        return 41

    def write( api_key, env ):
        calls.append( ( "file", api_key, env ) )
        return key_file

    monkeypatch.setattr( mod, "get_or_create_service_account", get_or_create )
    monkeypatch.setattr( mod, "generate_api_key", lambda: "ck_live_" + "X" * 64 )
    monkeypatch.setattr( mod, "store_api_key", store )
    monkeypatch.setattr( mod, "write_key_to_file", write )
    return calls


def test_the_happy_path_runs_the_steps_in_order_and_returns_zero( wired, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "csa" ] )

    assert mod.main() == 0

    assert [ c[ 0 ] for c in wired ] == [ "account", "store", "file" ]
    assert "SUCCESS: Service Account Created" in capsys.readouterr().out


def test_the_defaults_are_the_documented_email_and_the_dev_environment( wired, monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "csa" ] )

    mod.main()

    assert wired[ 0 ] == ( "account", "claude.code@deepily.ai", "" )
    assert wired[ 2 ][ 2 ] == "dev"


def test_the_flags_reach_the_steps_that_use_them( wired, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "csa", "--email=a@b.co", "--description=CI key", "--env=prod" ] )

    mod.main()

    assert wired[ 0 ] == ( "account", "a@b.co", "CI key" )
    assert wired[ 1 ][ 1 ] == "u-9" and wired[ 1 ][ 3 ] == "CI key"
    assert wired[ 2 ][ 2 ] == "prod"
    out = capsys.readouterr().out
    assert "Service Account: a@b.co" in out and "Environment: prod" in out and "Key ID: 41" in out


def test_the_full_key_is_printed_exactly_once( wired, monkeypatch, capsys ):
    monkeypatch.setattr( sys, "argv", [ "csa" ] )

    mod.main()

    assert capsys.readouterr().out.count( "ck_live_" + "X" * 64 ) == 1


def test_an_unknown_environment_is_rejected_by_the_parser( wired, monkeypatch ):
    monkeypatch.setattr( sys, "argv", [ "csa", "--env=moon" ] )

    with pytest.raises( SystemExit ) as e:
        mod.main()

    assert e.value.code == 2
    assert wired == []


def test_a_step_failure_returns_one_prints_the_error_and_never_prints_a_key( monkeypatch, capsys ):
    def boom( email, description ):
        raise RuntimeError( "no database" )

    monkeypatch.setattr( mod, "get_or_create_service_account", boom )
    monkeypatch.setattr( mod, "generate_api_key", lambda: pytest.fail( "a key was minted after the failure" ) )
    monkeypatch.setattr( sys, "argv", [ "csa" ] )

    assert mod.main() == 1

    cap = capsys.readouterr()
    assert "FAILED: Service Account Creation" in cap.out
    assert "Error: no database" in cap.err
    assert "ck_live_" not in cap.out
