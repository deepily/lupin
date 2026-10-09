"""
The local app containers connect through compose secret files, not the superuser password.

Rick ruled "extra group on the two app services" for the app login. The test container also mounts the
test role's file. This file parses docker-compose.yml, so it needs no docker and no network.
Venue: :7999-eligible.
"""
import os

import pytest
import yaml

import cosa.utils.util as cu

APP_SERVICES = ( "lupin-rest-dev", "lupin-rest-test" )
SECRET_NAME  = "db_app_password"
SECRET_HOST  = "/etc/lupin/secrets/db_app_password"
SECRET_CTR   = "/run/secrets/db_app_password"
TEST_SECRET  = "db_test_password"
TEST_HOST    = "/etc/lupin/secrets/db_test_password"
TEST_CTR     = "/run/secrets/db_test_password"


@pytest.fixture( scope="module" )
def compose():
    with open( os.path.join( cu.get_project_root(), "docker-compose.yml" ) ) as fh:
        return yaml.safe_load( fh )


@pytest.mark.parametrize( "name", APP_SERVICES )
def test_app_service_connects_as_lupin_app_from_a_file( compose, name ):
    env = compose[ "services" ][ name ][ "environment" ]
    assert env[ "DB_USER" ]          == "lupin_app"
    assert env[ "DB_PASSWORD_FILE" ] == SECRET_CTR
    assert "DB_PASSWORD" not in env, "the superuser password must not reach the app container"


@pytest.mark.parametrize( "name", APP_SERVICES )
def test_app_service_reads_the_file_through_group_1002_not_a_new_uid( compose, name ):
    svc = compose[ "services" ][ name ]
    assert svc[ "user" ]      == "1001:1001", "no uid change: io/ src/ projects/ are 744, owner-only"
    assert svc[ "group_add" ] == [ "1002" ]
    assert svc[ "secrets" ]   == ( [ SECRET_NAME, TEST_SECRET ] if name == "lupin-rest-test" else [ SECRET_NAME ] )


def test_secret_comes_from_the_root_owned_host_file( compose ):
    assert compose[ "secrets" ] == { SECRET_NAME: { "file": SECRET_HOST }, TEST_SECRET: { "file": TEST_HOST } }


def test_the_test_login_secret_reaches_the_test_service_only( compose ):
    env = compose[ "services" ][ "lupin-rest-test" ][ "environment" ]
    assert env[ "LUPIN_TEST_DB_USER" ] == "lupin_test"
    assert env[ "LUPIN_TEST_DB_PASSWORD_FILE" ] == TEST_CTR
    assert "LUPIN_TEST_DB_PASSWORD" not in env, "the password itself must not sit in the environment"
    dev = compose[ "services" ][ "lupin-rest-dev" ]
    assert TEST_SECRET not in dev[ "secrets" ], "the dev server must not mount the test role file"
    assert not any( k.startswith( "LUPIN_TEST_DB_" ) for k in dev[ "environment" ] ), "the dev server must not name the test login"
    holders = sorted( n for n, s in compose[ "services" ].items() if TEST_SECRET in s.get( "secrets", [ ] ) )
    assert holders == [ "lupin-rest-test" ]


def test_only_the_two_app_services_get_the_group_or_the_secret( compose ):
    holders = sorted( n for n, s in compose[ "services" ].items() if "group_add" in s or "secrets" in s )
    assert holders == sorted( APP_SERVICES )


def test_postgres_publishes_on_loopback_only( compose ):
    ports = compose[ "services" ][ "postgres" ][ "ports" ]
    assert ports == [ "127.0.0.1:5432:5432" ]
