"""
The helper that gives a test block the test role's login.

A `.env` with the host and test role keys seeds the host role at startup. A test that only sets
LUPIN_ENV=testing then opens lupin_db_test as lupin_host, which may not connect there.
These tests use a scratch `.env` with placeholder passwords, so no database is touched.
"""

import os

import pytest

from cosa.utils import dotenv_password
from tests.helpers.testing_venue import reselected_for_testing

ENV_TEXT = ( "LUPIN_HOST_DB_USER=lupin_host\nLUPIN_HOST_DB_PASSWORD=hostpw\n"
             "LUPIN_TEST_DB_USER=lupin_test\nLUPIN_TEST_DB_PASSWORD=testpw\n" )


@pytest.fixture
def seeded( monkeypatch, tmp_path ):
    """Seed the host login from a scratch .env, as the first call under pytest does."""
    for key in ( "DB_USER", "DB_PASSWORD", "LUPIN_ENV", "DATABASE_URL", "DB_NAME" ):
        monkeypatch.setenv( key, "placeholder" )
        monkeypatch.delenv( key )
    monkeypatch.setattr( dotenv_password, "_SEEDED", { } )
    ( tmp_path / ".env" ).write_text( ENV_TEXT )
    dotenv_password.seed_db_password_from_dotenv( root=str( tmp_path ) )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" ), "the seed is not the host role"
    return tmp_path


def test_setting_the_env_alone_keeps_the_host_login_which_is_the_defect( seeded, monkeypatch ):
    """Control: the old test body shows the defect, so the next test means something."""
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    assert os.environ[ "DB_USER" ] == "lupin_host"


def test_the_block_runs_as_the_test_role_with_the_env_pinned( seeded, monkeypatch ):
    monkeypatch.setenv( "DATABASE_URL", "postgresql://elsewhere" )
    monkeypatch.setenv( "DB_NAME", "elsewhere" )
    with reselected_for_testing( str( seeded ) ) as chosen:
        assert chosen is True
        assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_test", "testpw" )
        assert os.environ[ "LUPIN_ENV" ] == "testing"
        assert "DATABASE_URL" not in os.environ and "DB_NAME" not in os.environ


def test_everything_is_put_back_on_exit_even_when_the_block_raises( seeded, monkeypatch ):
    monkeypatch.setenv( "DB_NAME", "kept" )
    before_seeded = dict( dotenv_password._SEEDED )
    with pytest.raises( RuntimeError ):
        with reselected_for_testing( str( seeded ) ):
            raise RuntimeError( "boom" )
    assert ( os.environ[ "DB_USER" ], os.environ[ "DB_PASSWORD" ] ) == ( "lupin_host", "hostpw" )
    assert "LUPIN_ENV" not in os.environ and os.environ[ "DB_NAME" ] == "kept"
    assert dotenv_password._SEEDED == before_seeded


def test_an_exported_login_is_left_alone_and_reported( seeded, monkeypatch ):
    monkeypatch.setenv( "DB_USER", "exported_user" )
    with reselected_for_testing( str( seeded ) ) as chosen:
        assert chosen is False and os.environ[ "DB_USER" ] == "exported_user"


def test_a_env_without_test_keys_keeps_the_host_login_and_says_so( seeded ):
    ( seeded / ".env" ).write_text( "LUPIN_HOST_DB_USER=lupin_host\nLUPIN_HOST_DB_PASSWORD=hostpw\n" )
    with reselected_for_testing( str( seeded ) ) as chosen:
        assert chosen is False and os.environ[ "DB_USER" ] == "lupin_host"


def test_unset_variables_stay_unset_after_the_block( seeded, monkeypatch ):
    monkeypatch.delenv( "DB_USER" )
    monkeypatch.delenv( "DB_PASSWORD" )
    dotenv_password._SEEDED.clear()
    with reselected_for_testing( str( seeded ) ):
        pass
    assert "DB_USER" not in os.environ and "DB_PASSWORD" not in os.environ
