"""
Make throwaway Postgres databases by cloning the vector template.

Provisioning builds ``lupin_template_vector`` once, with the vector extension installed.
A test that needs a scratch database clones it with a template-based clone, which
needs no superuser and no extension privilege. A missing template fails the test, never
skips it: a skip would read as green on a host that was never provisioned.
"""

import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

import cosa.utils.dotenv_password as dp

TEMPLATE_NAME = "lupin_template_vector"

_MISSING_CODE = "3D000"
_DENIED_CODE  = "42501"


def clone_server_url():
    """
    Build the base URL of the Postgres server the tests clone databases on.

    Requires:
        - DB_HOST and DB_PORT, when set, name the server; defaults are localhost and 5432

    Ensures:
        - Uses the test role's login when cosa.utils.dotenv_password.clone_login finds one
        - Otherwise uses DB_USER and DB_PASSWORD from the process, as the sites did before
        - Names the maintenance database "postgres", never a Lupin database
    """
    host  = os.environ.get( "DB_HOST", "localhost" )
    port  = int( os.environ.get( "DB_PORT", "5432" ) )
    login = dp.clone_login()
    if login is None: login = ( os.environ.get( "DB_USER", "lupin_dev" ), os.environ.get( "DB_PASSWORD", "" ) )
    return make_url( "postgresql+psycopg2://" ).set( username=login[ 0 ], password=login[ 1 ], host=host, port=port, database="postgres" ).render_as_string( hide_password=False )


def _admin_engine( server_url, engine_factory ):
    return engine_factory( server_url, isolation_level="AUTOCOMMIT" )


def create_from_template( server_url, name, engine_factory=create_engine ):
    """
    Create database ``name`` as a clone of the vector template and return its URL.

    Requires:
        - server_url names the maintenance database of a provisioned server
        - name is a lowercase identifier of letters, digits and underscores

    Ensures:
        - Returns the URL of the new database, with the same login as server_url
        - Fails the test, with the command that provisions the template, when it is absent
        - Fails the test when the login may not create databases
        - Lets an unreachable server's OperationalError through, so a site can skip on it
    """
    assert name.replace( "_", "" ).isalnum() and name == name.lower(), f"unsafe database name {name!r}"
    engine = _admin_engine( server_url, engine_factory )
    try:
        with engine.connect() as conn:
            conn.execute( text( f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_NAME}" ) )
    except ProgrammingError as error:
        code = getattr( error.orig, "pgcode", None )
        if code == _MISSING_CODE: pytest.fail( f"template {TEMPLATE_NAME} is missing: run db_roles --grants-only --apply" )
        if code == _DENIED_CODE: pytest.fail( "this login may not create databases" )
        raise
    finally:
        engine.dispose()
    return make_url( server_url ).set( database=name ).render_as_string( hide_password=False )


def drop_database( server_url, name, engine_factory=create_engine ):
    """
    Drop database ``name``, closing its connections first.

    Requires:
        - server_url names the maintenance database of the same server

    Ensures:
        - Does nothing when the database is already gone
    """
    engine = _admin_engine( server_url, engine_factory )
    try:
        with engine.connect() as conn:
            conn.execute( text( "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity WHERE datname = :n AND pid <> pg_backend_pid()" ), { "n": name } )
            conn.execute( text( f"DROP DATABASE IF EXISTS {name}" ) )
    finally:
        engine.dispose()


@contextmanager
def throwaway_database( server_url, name, engine_factory=create_engine ):
    """
    Yield the URL of a fresh clone of the template, and drop it on the way out.

    Ensures:
        - The drop runs when the body raises
        - Nothing is dropped when the clone itself failed
    """
    url = create_from_template( server_url, name, engine_factory )
    try:
        yield url
    finally:
        drop_database( server_url, name, engine_factory )
