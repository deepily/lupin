"""
The run databases port against a real Postgres server.

A clone appears, is counted, and is gone after the drop. The unit tests pin the SQL; this shows the server accepts it
and that a dropped database is really gone. It fails, never skips, when the server or the template is missing.
"""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from lupin_mcp.reuse_harness import databases
from lupin_mcp.reuse_harness import errors as err


def exists( server_url, name ):
    """Say whether the server lists a database of this name."""
    engine = create_engine( server_url, isolation_level="AUTOCOMMIT" )
    try:
        with engine.connect() as conn: return conn.execute( text( "SELECT count(*) FROM pg_database WHERE datname = :n" ), { "n" : name } ).scalar() == 1
    finally:
        engine.dispose()


def run_sql( server_url, name, *statements ):
    """Run statements in the named database."""
    engine = create_engine( make_url( server_url ).set( database=name ).render_as_string( hide_password=False ), isolation_level="AUTOCOMMIT" )
    try:
        with engine.connect() as conn:
            for statement in statements: conn.execute( text( statement ) )
    finally:
        engine.dispose()


def test_a_run_database_is_cloned_counted_and_dropped_on_a_real_server():
    url   = databases.maintenance_url()
    store = databases.Databases( url )
    name  = f"rrun_it_{uuid.uuid4().hex[ :12 ]}"
    store.create( name )
    try:
        assert exists( url, name ) is True
        with pytest.raises( err.HarnessError ) as caught: store.is_fresh( name )
        assert caught.value.code == err.DB_UNAVAILABLE
        run_sql( url, name, "CREATE TABLE users ( id int )", "CREATE TABLE notifications ( id int )" )
        assert store.is_fresh( name ) is True
        run_sql( url, name, "INSERT INTO users VALUES ( 1 )" )
        assert store.is_fresh( name ) is False
    finally:
        store.drop( name )
    assert exists( url, name ) is False
    store.drop( name )


def test_creating_a_database_that_exists_is_refused_and_names_the_database():
    url   = databases.maintenance_url()
    store = databases.Databases( url )
    name  = f"rrun_it_{uuid.uuid4().hex[ :12 ]}"
    store.create( name )
    try:
        with pytest.raises( err.HarnessError ) as caught: store.create( name )
        assert caught.value.code == err.DB_UNAVAILABLE and name in caught.value.detail
    finally:
        store.drop( name )
