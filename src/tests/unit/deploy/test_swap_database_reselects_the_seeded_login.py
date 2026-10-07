"""
swap_database picks the login again for the environment it moves to.

The login was chosen once, at the first get_database_url call, from the LUPIN_ENV of that moment.
A process started without LUPIN_ENV got lupin_host, then swap_database( "testing" ) pointed it at
lupin_db_test with that same role, which may not connect there. The rule under test: a login this
seeder chose is chosen again; a DB_USER or DB_PASSWORD the caller exported is never touched.

Venue: :7999 (unit, no server, no database; the engine factory is replaced).
"""

import functools
import os

import pytest

import cosa.rest.db.database as database
import cosa.utils.dotenv_password as dotenv_password

def _env( **pairs ):
    """The text of a .env file; built from names and values so no line reads as a credential."""
    return "".join( f"{key}={value}\n" for key, value in pairs.items() )


ENV_TEXT = _env( POSTGRES_PASSWORD="superpw", LUPIN_HOST_DB_PASSWORD="hostpw", LUPIN_TEST_DB_PASSWORD="testpw" )


class _FakeEngine:
    """Stands in for an Engine: remembers its URL, connects to nothing."""

    def __init__( self, url ):
        self.url = url

    def dispose( self ): pass

    def connect( self ): return self

    def __enter__( self ): return self

    def __exit__( self, *exc ): return False

    def execute( self, statement ): return None


class _Url:
    def __init__( self, text ):
        self.text     = text
        self.password = text.split( ":" )[ 2 ].split( "@" )[ 0 ]

    def __str__( self ): return self.text


@pytest.fixture
def swap( monkeypatch, tmp_path ):
    """A swap_database with the engine factory replaced and the .env read from tmp_path."""
    for key in ( "DB_PASSWORD", "DB_USER", "DB_PASSWORD_FILE", "LUPIN_ENV", "LUPIN_CLOUD_BACKED" ):
        monkeypatch.delenv( key, raising=False )
    ( tmp_path / ".env" ).write_text( ENV_TEXT )
    monkeypatch.setattr( dotenv_password, "_SEEDED", { } )
    monkeypatch.setattr( database, "seed_db_password_from_dotenv",
                         functools.partial( dotenv_password.seed_db_password_from_dotenv, root=str( tmp_path ) ) )
    monkeypatch.setattr( database, "reselect_seeded_login",
                         functools.partial( dotenv_password.reselect_seeded_login, root=str( tmp_path ) ) )
    monkeypatch.setattr( database, "create_engine", lambda url, **kw: _FakeEngine( _Url( url ) ) )
    for name in ( "engine", "SessionLocal", "ScopedSession" ):
        monkeypatch.setattr( database, name, _FakeEngine( _Url( "postgresql://x:y@h:1/d" ) ) if name == "engine" else None )
    monkeypatch.setattr( database, "sessionmaker", lambda **kw: None )
    monkeypatch.setattr( database, "scoped_session", lambda factory: None )
    return database.swap_database


def test_a_seeded_host_login_becomes_the_test_login_on_a_swap_to_testing( swap ):
    database.get_database_url()
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" )
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_test", "testpw" )
    assert str( database.engine.url ) == "postgresql+psycopg2://lupin_test:testpw@localhost:5432/lupin_db_test"


def test_moving_back_to_development_restores_the_first_login( swap ):
    database.get_database_url()
    swap( "testing" )
    swap( "development" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" )
    assert str( database.engine.url ) == "postgresql+psycopg2://lupin_host:hostpw@localhost:5432/lupin_db_dev"


def test_an_exported_login_is_left_alone_by_a_swap( swap, monkeypatch ):
    monkeypatch.setenv( "DB_USER", "exported_user" )
    monkeypatch.setenv( "DB_PASSWORD", "exported_pw" )
    database.get_database_url()
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "exported_user", "exported_pw" )
    assert str( database.engine.url ) == "postgresql+psycopg2://exported_user:exported_pw@localhost:5432/lupin_db_test"


def test_an_exported_user_with_a_seeded_password_is_left_alone( swap, monkeypatch ):
    monkeypatch.setenv( "DB_USER", "exported_user" )
    database.get_database_url()
    assert os.environ[ "DB_PASSWORD" ] == "hostpw"
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "exported_user", "hostpw" )


def test_a_login_changed_after_seeding_is_treated_as_exported( swap, monkeypatch ):
    database.get_database_url()
    monkeypatch.setenv( "DB_PASSWORD", "changed_since" )
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "changed_since" )


def test_a_swap_before_any_login_was_chosen_chooses_the_one_for_the_new_environment( swap ):
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_test", "testpw" )
    assert dotenv_password.reselect_seeded_login() is True


def test_the_previous_login_is_put_back_when_the_new_environment_finds_none( swap, tmp_path ):
    ( tmp_path / ".env" ).write_text( _env( LUPIN_HOST_DB_PASSWORD="hostpw" ) )
    database.get_database_url()
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" )
    swap( "development" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" )


def test_a_superuser_password_seeded_alone_is_chosen_again_too( swap, tmp_path ):
    ( tmp_path / ".env" ).write_text( _env( POSTGRES_PASSWORD="superpw", LUPIN_TEST_DB_PASSWORD="testpw" ) )
    database.get_database_url()
    assert os.environ[ "DB_PASSWORD" ] == "superpw" and "DB_USER" not in os.environ
    swap( "testing" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_test", "testpw" )
