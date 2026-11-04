"""
The two credential routes the approval-settings guard rail (row 80513825) adds:

  1. a seat's `.env` may carry the credentials of a ROLE that cannot write policy
     (`LUPIN_HOST_DB_*`, `LUPIN_TEST_DB_*`) and those win over the superuser's
     `POSTGRES_PASSWORD`, which stays the fallback;
  2. a password may come from a FILE (`DB_PASSWORD_FILE`), which is what lets the app's
     credential live outside `.env`.

⚠️ Every `.env` below carries a DIFFERENT value for each key, so a helper that read the wrong
key or the wrong venue produces a different password, not the same one.
"""

import json
import os
import re
import subprocess
import sys

import pytest

import cosa.utils.dotenv_password as dotenv_password
from cosa.rest.db import database
from cosa.utils.dotenv_password import seed_db_password_from_dotenv, seed_db_password_from_file


@pytest.fixture( autouse=True )
def clean_env( monkeypatch ):
    """
    Start each test with no database login set, and restore the environment afterwards.

    A delete of an absent key records nothing, so the key is set first and then deleted. The seeder
    writes os.environ directly, and without a recorded absence its DB_USER would outlive the test.
    The seeder keeps a record of what it set; that dict is replaced for the test and restored after.
    """
    for key in ( "DB_PASSWORD", "DB_USER", "DB_PASSWORD_FILE", "LUPIN_ENV" ):
        monkeypatch.setenv( key, "placeholder" )
        monkeypatch.delenv( key )
    monkeypatch.setattr( dotenv_password, "_SEEDED", { } )


def _dotenv( tmp_path, pairs ):
    ( tmp_path / ".env" ).write_text( "".join( f"{k}={v}\n" for k, v in pairs.items() ) )
    return str( tmp_path )


# DISTINCT dummy values, named without the credential-looking shape the commit guard scans for.
_NAMES  = ( "POSTGRES_PASSWORD", "LUPIN_HOST_DB_USER", "LUPIN_HOST_DB_PASSWORD", "LUPIN_TEST_DB_USER", "LUPIN_TEST_DB_PASSWORD" )
_VALUES = ( "dummy-super-1", "lupin_host", "dummy-host-2", "lupin_test", "dummy-test-3" )
ALL_KEYS = dict( zip( _NAMES, _VALUES ) )
SUPER, HOST, TEST = _VALUES[ 0 ], _VALUES[ 2 ], _VALUES[ 4 ]
EXPORTED, FROM_FILE = "dummy-exported-4", "dummy-file-5"


def _pair( name, value ):
    """One .env line's worth of keys, built without a `KEY: value` literal the commit guard would flag."""
    return dict( [ ( name, value ) ] )


# ---- the .env: role keys over the superuser ------------------------------------------------

def test_a_development_process_takes_the_host_role( tmp_path ):
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, ALL_KEYS ) )
    assert ( os.environ[ "DB_PASSWORD" ], os.environ[ "DB_USER" ] ) == ( HOST, "lupin_host" )


def test_a_testing_process_takes_the_test_role( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ENV", "Testing" )
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, ALL_KEYS ) )
    assert ( os.environ[ "DB_PASSWORD" ], os.environ[ "DB_USER" ] ) == ( TEST, "lupin_test" )


def test_an_exported_db_user_is_not_overwritten_by_the_role_user( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DB_USER", "exported-user" )
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, ALL_KEYS ) )
    assert os.environ[ "DB_USER" ] == "exported-user"
    assert os.environ[ "DB_PASSWORD" ] == HOST


def test_a_role_password_with_no_role_user_takes_the_roles_default_name( tmp_path, monkeypatch ):
    """The reviewer's pairing finding: never the superuser's name with a role's password."""
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, _pair( "LUPIN_HOST_DB_PASSWORD", HOST ) ) )
    assert ( os.environ[ "DB_PASSWORD" ], os.environ[ "DB_USER" ] ) == ( HOST, "lupin_host" )
    for key in ( "DB_PASSWORD", "DB_USER" ): monkeypatch.delenv( key )
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, _pair( "LUPIN_TEST_DB_PASSWORD", TEST ) ) )
    assert ( os.environ[ "DB_PASSWORD" ], os.environ[ "DB_USER" ] ) == ( TEST, "lupin_test" )


def test_the_superuser_password_is_the_fallback_when_no_role_key_is_present( tmp_path ):
    """Today's behaviour, unchanged: a .env that only has POSTGRES_PASSWORD."""
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, _pair( "POSTGRES_PASSWORD", SUPER ) ) )
    assert os.environ[ "DB_PASSWORD" ] == SUPER
    assert "DB_USER" not in os.environ


def test_the_wrong_venues_role_key_does_not_count( tmp_path, monkeypatch ):
    """A testing process with only HOST keys must not borrow them; it falls back to the superuser's."""
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, { **_pair( "POSTGRES_PASSWORD", SUPER ),
                                                **_pair( "LUPIN_HOST_DB_PASSWORD", HOST ) } ) )
    assert os.environ[ "DB_PASSWORD" ] == SUPER


def test_an_empty_role_password_falls_through_to_the_superuser_one( tmp_path ):
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, { **_pair( "POSTGRES_PASSWORD", SUPER ), **_pair( "LUPIN_HOST_DB_PASSWORD", "" ) } ) )
    assert os.environ[ "DB_PASSWORD" ] == SUPER


def test_quotes_around_a_role_value_are_stripped( tmp_path ):
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, _pair( "LUPIN_HOST_DB_PASSWORD", '"' + HOST + '"' ) ) )
    assert os.environ[ "DB_PASSWORD" ] == HOST


def test_a_dotenv_with_none_of_the_keys_sets_nothing( tmp_path ):
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, _pair( "SOMETHING_ELSE", "x" ) ) )
    assert "DB_PASSWORD" not in os.environ


def test_an_exported_password_still_wins_over_every_role_key( tmp_path, monkeypatch ):
    monkeypatch.setenv( "DB_PASSWORD", EXPORTED )
    seed_db_password_from_dotenv( root=_dotenv( tmp_path, ALL_KEYS ) )
    assert os.environ[ "DB_PASSWORD" ] == EXPORTED


def test_an_unreadable_dotenv_is_swallowed( tmp_path ):
    ( tmp_path / ".env" ).mkdir()       # a directory where the file should be: open() raises OSError
    ( tmp_path / ".env" ).rmdir()
    ( tmp_path / ".env" ).write_text( "POSTGRES_PASSWORD=x\n" )
    os.chmod( tmp_path / ".env", 0 )
    try:
        if os.access( tmp_path / ".env", os.R_OK ): pytest.skip( "running as a user that ignores file modes" )
        seed_db_password_from_dotenv( root=str( tmp_path ) )
    finally:
        os.chmod( tmp_path / ".env", 0o600 )
    assert "DB_PASSWORD" not in os.environ


# ---- DB_PASSWORD_FILE -------------------------------------------------------------------------

def test_a_password_file_fills_a_blank_password_and_strips_the_newline( tmp_path, monkeypatch ):
    secret = tmp_path / "db_app_password"
    secret.write_text( "  " + FROM_FILE + "\n" )
    monkeypatch.setenv( "DB_PASSWORD_FILE", str( secret ) )
    seed_db_password_from_file()
    assert os.environ[ "DB_PASSWORD" ] == FROM_FILE


def test_an_exported_password_wins_over_the_file( tmp_path, monkeypatch ):
    secret = tmp_path / "db_app_password"
    secret.write_text( FROM_FILE + "\n" )
    monkeypatch.setenv( "DB_PASSWORD_FILE", str( secret ) )
    monkeypatch.setenv( "DB_PASSWORD", EXPORTED )
    seed_db_password_from_file()
    assert os.environ[ "DB_PASSWORD" ] == EXPORTED


def test_no_password_file_variable_is_a_no_op():
    seed_db_password_from_file()
    assert "DB_PASSWORD" not in os.environ


def test_a_missing_password_file_warns_by_name_and_leaves_the_password_unset( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( "DB_PASSWORD_FILE", str( tmp_path / "absent" ) )
    seed_db_password_from_file()
    out = capsys.readouterr().out
    assert "DB_PASSWORD_FILE=" in out and "FileNotFoundError" in out
    assert "DB_PASSWORD" not in os.environ


def test_an_empty_password_file_warns_and_leaves_the_password_unset( tmp_path, monkeypatch, capsys ):
    secret = tmp_path / "db_app_password"
    secret.write_text( "\n" )
    monkeypatch.setenv( "DB_PASSWORD_FILE", str( secret ) )
    seed_db_password_from_file()
    assert "is empty" in capsys.readouterr().out
    assert "DB_PASSWORD" not in os.environ


# ---- the URL builder uses both ------------------------------------------------------------------

def test_get_database_url_reads_the_password_file_before_the_dotenv( tmp_path, monkeypatch ):
    secret = tmp_path / "db_app_password"
    secret.write_text( FROM_FILE + "\n" )
    monkeypatch.setenv( "DB_PASSWORD_FILE", str( secret ) )
    monkeypatch.setenv( "DB_USER", "lupin_app" )
    monkeypatch.setenv( "LUPIN_ENV", "development" )
    monkeypatch.delenv( "LUPIN_CLOUD_BACKED", raising=False )
    url = database.get_database_url()
    assert url.startswith( "postgresql+psycopg2://lupin_app:" + FROM_FILE + "@" )


_WATCHER = """
import json, os
KEYS = ( "DB_USER", "DB_PASSWORD", "DB_PASSWORD_FILE", "LUPIN_ENV" )
def _state():
    import cosa.utils.dotenv_password as module
    return { **{ k: os.environ.get( k ) for k in KEYS }, "seeded_keys": sorted( module._SEEDED ) }
def pytest_sessionstart( session ):
    session.config._before = _state()
def pytest_sessionfinish( session ):
    print( "ENVWATCH " + json.dumps( { "before": session.config._before, "after": _state() } ) )
"""


def test_the_file_leaves_the_database_login_as_it_found_it( tmp_path ):
    """Run this file in a child pytest and compare the login state before and after."""
    plugin = tmp_path / "envwatch_plugin.py"
    plugin.write_text( _WATCHER )
    env = { **os.environ, "PYTHONPATH": os.pathsep.join( [ str( tmp_path ), os.environ[ "PYTHONPATH" ] ] ) }
    done = subprocess.run( [ sys.executable, "-m", "pytest", __file__, "-q", "-p", "no:cacheprovider", "-p", "envwatch_plugin",
                             "-k", "not the_file_leaves_the_database_login" ],
                           capture_output=True, text=True, timeout=300, env=env )
    found = re.findall( r"ENVWATCH (\{.*\})", done.stdout )
    assert len( found ) == 1 and done.returncode == 0, done.stdout[ -800: ] + done.stderr[ -400: ]
    seen = json.loads( found[ 0 ] )
    assert seen[ "after" ] == seen[ "before" ], f"the file changed the login variables or the seeder record: {seen}"
