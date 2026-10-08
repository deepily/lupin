"""
Unit tests for the template-clone helper and the login it builds.

A stub engine factory records every statement, so no server is needed. The real clone runs
in the real-Postgres smoke files.
"""

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

import cosa.utils.dotenv_password as dp
from tests.helpers import template_database as td

URL = "postgresql+psycopg2://alice:pw@db.example:5433/postgres"


class _Orig( Exception ):
    def __init__( self, pgcode ):
        super().__init__( "boom" )
        self.pgcode = pgcode


class _Conn:
    def __init__( self, log, raises ): self.log, self.raises = log, raises
    def __enter__( self ): return self
    def __exit__( self, *a ): return False
    def execute( self, statement, params=None ):
        self.log.append( ( str( statement ), params ) )
        if self.raises is not None and "CREATE DATABASE" in str( statement ): raise self.raises


class _Engine:
    def __init__( self, log, raises, url, kwargs ):
        self.log, self.raises, self.url, self.kwargs, self.disposed = log, raises, url, kwargs, False
    def connect( self ): return _Conn( self.log, self.raises )
    def dispose( self ): self.disposed = True


class _Factory:
    def __init__( self, raises=None ):
        self.log, self.raises, self.engines = [ ], raises, [ ]
    def __call__( self, url, **kwargs ):
        engine = _Engine( self.log, self.raises, url, kwargs )
        self.engines.append( engine )
        return engine
    def sql( self ): return [ s for s, _ in self.log ]


def _programming( code ): return ProgrammingError( "stmt", { }, _Orig( code ) )


def test_the_clone_statement_names_the_template_and_returns_the_new_url():
    factory = _Factory()
    url = td.create_from_template( URL, "scratch_one", factory )
    assert factory.sql() == [ "CREATE DATABASE scratch_one TEMPLATE lupin_template_vector" ]
    assert url == "postgresql+psycopg2://alice:pw@db.example:5433/scratch_one"
    assert factory.engines[ 0 ].kwargs == { "isolation_level": "AUTOCOMMIT" }
    assert factory.engines[ 0 ].disposed


def test_a_missing_template_fails_loudly_and_never_skips():
    with pytest.raises( pytest.fail.Exception ) as caught:
        td.create_from_template( URL, "scratch_one", _Factory( _programming( "3D000" ) ) )
    assert "db_roles --grants-only --apply" in str( caught.value )


def test_a_login_that_may_not_create_databases_fails_loudly():
    with pytest.raises( pytest.fail.Exception ) as caught:
        td.create_from_template( URL, "scratch_one", _Factory( _programming( "42501" ) ) )
    assert "may not create databases" in str( caught.value )


def test_any_other_database_error_passes_through_unchanged():
    error = _programming( "XX000" )
    with pytest.raises( ProgrammingError ) as caught:
        td.create_from_template( URL, "scratch_one", _Factory( error ) )
    assert caught.value is error


def test_an_unreachable_server_reaches_the_site_so_it_can_skip():
    error = OperationalError( "stmt", { }, _Orig( None ) )
    with pytest.raises( OperationalError ):
        td.create_from_template( URL, "scratch_one", _Factory( error ) )


@pytest.mark.parametrize( "name", [ "Upper", "has-dash", "semi;colon", "" ] )
def test_an_unsafe_name_is_refused_before_any_connection( name ):
    factory = _Factory()
    with pytest.raises( AssertionError ): td.create_from_template( URL, name, factory )
    assert factory.engines == [ ]


def test_the_drop_closes_connections_then_drops_with_a_bound_name():
    factory = _Factory()
    td.drop_database( URL, "scratch_one", factory )
    assert factory.log[ 0 ][ 1 ] == { "n": "scratch_one" }
    assert "pg_terminate_backend" in factory.sql()[ 0 ]
    assert factory.sql()[ 1 ] == "DROP DATABASE IF EXISTS scratch_one"
    assert factory.engines[ 0 ].disposed


def test_the_throwaway_database_drops_when_the_body_raises():
    factory = _Factory()
    with pytest.raises( RuntimeError ):
        with td.throwaway_database( URL, "scratch_one", factory ) as url:
            assert url.endswith( "/scratch_one" )
            raise RuntimeError( "body failed" )
    assert factory.sql()[ -1 ] == "DROP DATABASE IF EXISTS scratch_one"


def test_a_failed_clone_drops_nothing():
    factory = _Factory( _programming( "3D000" ) )
    with pytest.raises( pytest.fail.Exception ):
        with td.throwaway_database( URL, "scratch_one", factory ): pass
    assert not any( "DROP" in s for s in factory.sql() )


def test_the_server_url_uses_the_clone_login_with_the_env_host_and_port( monkeypatch ):
    monkeypatch.setattr( dp, "clone_login", lambda: ( "lupin_test", "tp" ) )
    monkeypatch.setenv( "DB_HOST", "h1" )
    monkeypatch.setenv( "DB_PORT", "5444" )
    assert td.clone_server_url() == "postgresql+psycopg2://lupin_test:tp@h1:5444/postgres"


def test_the_server_url_falls_back_to_the_process_login( monkeypatch ):
    monkeypatch.setattr( dp, "clone_login", lambda: None )
    monkeypatch.setenv( "DB_USER", "u1" )
    monkeypatch.setenv( "DB_PASSWORD", "p1" )
    monkeypatch.delenv( "DB_HOST", raising=False )
    monkeypatch.delenv( "DB_PORT", raising=False )
    assert td.clone_server_url() == "postgresql+psycopg2://u1:p1@localhost:5432/postgres"


def test_the_server_url_defaults_the_user_and_an_empty_password( monkeypatch ):
    monkeypatch.setattr( dp, "clone_login", lambda: None )
    monkeypatch.delenv( "DB_USER", raising=False )
    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    assert td.clone_server_url().startswith( "postgresql+psycopg2://lupin_dev:@localhost:5432/" )


# ---- cosa.utils.dotenv_password.clone_login -------------------------------------------------

def _env( tmp_path, text ):
    ( tmp_path / ".env" ).write_text( text )
    return str( tmp_path )


def test_the_login_reads_the_environment_first( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_TEST_DB_USER", "envu" )
    monkeypatch.setenv( "LUPIN_TEST_DB_PASSWORD", "envp" )
    assert dp.clone_login( _env( tmp_path, "LUPIN_TEST_DB_USER=fileu\nLUPIN_TEST_DB_PASSWORD=filep\n" ) ) == ( "envu", "envp" )


def test_the_login_reads_the_dotenv_when_the_environment_is_silent( monkeypatch, tmp_path ):
    monkeypatch.delenv( "LUPIN_TEST_DB_USER", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    assert dp.clone_login( _env( tmp_path, "LUPIN_TEST_DB_USER=fileu\nLUPIN_TEST_DB_PASSWORD=filep\n" ) ) == ( "fileu", "filep" )


def test_the_login_user_falls_back_to_the_test_role( monkeypatch, tmp_path ):
    monkeypatch.delenv( "LUPIN_TEST_DB_USER", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    assert dp.clone_login( _env( tmp_path, "LUPIN_TEST_DB_PASSWORD=filep\n" ) ) == ( "lupin_test", "filep" )


def test_an_environment_user_without_a_password_keeps_its_name_beside_the_file_password( monkeypatch, tmp_path ):
    monkeypatch.setenv( "LUPIN_TEST_DB_USER", "envu" )
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    assert dp.clone_login( _env( tmp_path, "LUPIN_TEST_DB_PASSWORD=filep\n" ) ) == ( "envu", "filep" )


def test_the_login_is_none_without_a_password_anywhere( monkeypatch, tmp_path ):
    monkeypatch.delenv( "LUPIN_TEST_DB_USER", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    assert dp.clone_login( _env( tmp_path, "POSTGRES_PASSWORD=super\n" ) ) is None
    assert dp.clone_login( str( tmp_path / "nowhere" ) ) is None


def test_the_login_never_changes_the_environment( monkeypatch, tmp_path ):
    monkeypatch.delenv( "LUPIN_TEST_DB_USER", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    dp.clone_login( _env( tmp_path, "LUPIN_TEST_DB_PASSWORD=filep\n" ) )
    import os
    assert "DB_PASSWORD" not in os.environ and "LUPIN_TEST_DB_PASSWORD" not in os.environ


def test_the_login_default_root_is_the_project_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_DB_PASSWORD", raising=False )
    seen = [ ]
    monkeypatch.setattr( dp, "_read_dotenv_values", lambda root, wanted: seen.append( root ) or { } )
    assert dp.clone_login() is None
    import os
    assert os.path.isfile( os.path.join( seen[ 0 ], "src", "cosa", "utils", "dotenv_password.py" ) )
