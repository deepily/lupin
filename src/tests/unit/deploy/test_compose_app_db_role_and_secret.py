"""
The two local app containers connect as `lupin_app`, reading a root-owned password file
(row 80513825, Rick's ruling 2026-10-03: "Extra group on the two app services").

Static: parses docker-compose.yml, no docker, no network. Venue :7999-eligible.
"""
import os

import pytest
import yaml

import cosa.utils.util as cu

APP_SERVICES = ( "lupin-rest-dev", "lupin-rest-test" )
SECRET_NAME  = "db_app_password"
SECRET_HOST  = "/etc/lupin/secrets/db_app_password"
SECRET_CTR   = "/run/secrets/db_app_password"


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
    assert svc[ "secrets" ]   == [ SECRET_NAME ]


def test_secret_comes_from_the_root_owned_host_file( compose ):
    assert compose[ "secrets" ] == { SECRET_NAME: { "file": SECRET_HOST } }


def test_only_the_two_app_services_get_the_group_or_the_secret( compose ):
    holders = sorted( n for n, s in compose[ "services" ].items() if "group_add" in s or "secrets" in s )
    assert holders == sorted( APP_SERVICES )


def test_postgres_publishes_on_loopback_only( compose ):
    ports = compose[ "services" ][ "postgres" ][ "ports" ]
    assert ports == [ "127.0.0.1:5432:5432" ]
