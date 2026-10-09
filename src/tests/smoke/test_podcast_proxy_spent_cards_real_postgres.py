"""
The spent-card claim race, run against a real Postgres.

The unit tests race two threads on a SQLite file. The claim relies on a savepoint and the primary key.
Both behave differently under Postgres, so only a real server can say that one start wins.

A replay of the SQL through docker exec psql was not enough. It would test statements typed here. It
would not test the repository code, the session handling or the table the migration builds. This file
connects from the host with psycopg2, over the bridge address of a throwaway container. No port is published.

Safety, in order: the name and label guards of the rollback file approve the container. Its address is
read from docker inspect. The connection is refused when that address is empty or is the real database's host.
The login password is random, made in the test, and never written to disk.
Venue: host-side, docker required. The merge gate's containers have no docker socket, so there it skips.
"""

import os
import secrets
import threading
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from test_db_roles_rollback_real_postgres import (   # noqa: F401  (fixtures are used by name)
    SUPERUSER, _docker, _labels_of, _psql, needs_docker, refuse_unless_throwaway, throwaway,
)

from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
from migrations.versions import d4bf48f78a01_add_podcast_proxy_spent_cards as migration

RACERS = 8


def bridge_address( name, real_hosts ):
    """
    The address of the throwaway container on the docker bridge.

    Requires:
        - name is a container the guards approved; real_hosts lists the hosts of the real database

    Ensures:
        - returns the address docker inspect reports for the container
        - raises RuntimeError when the address is empty or is one of real_hosts, before anything connects
    """
    shown = _docker( "inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", name )
    assert shown.returncode == 0, shown.stderr
    found = shown.stdout.split()
    address = found[ 0 ] if found else ""
    if not address: raise RuntimeError( f"SAFETY: docker reports no address for {name}" )
    if address in real_hosts: raise RuntimeError( f"SAFETY: {address} is the real database's host" )
    return address


def real_database_hosts():
    """The hosts the real database answers on: DB_HOST and the address of its container."""
    hosts = { os.environ.get( "DB_HOST", "" ), "localhost", "127.0.0.1" }
    shown = _docker( "inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", "lupin-postgres" )
    if shown.returncode == 0: hosts.update( shown.stdout.split() )
    return hosts


def test_the_address_guard_refuses_an_empty_address_and_the_real_host_before_connecting( monkeypatch ):
    class Done:
        def __init__( self, out ): self.returncode, self.stdout, self.stderr = 0, out, ""
    monkeypatch.setattr( __name__ + "._docker", lambda *args, **kwargs: Done( "  " ) )
    with pytest.raises( RuntimeError, match="no address" ): bridge_address( "lupin-dbroles-test-x", set() )
    monkeypatch.setattr( __name__ + "._docker", lambda *args, **kwargs: Done( "172.17.0.2 " ) )
    with pytest.raises( RuntimeError, match="real database" ): bridge_address( "lupin-dbroles-test-x", { "172.17.0.2" } )
    assert bridge_address( "lupin-dbroles-test-x", { "172.17.0.9" } ) == "172.17.0.2"


@pytest.fixture
def engine( throwaway ):
    """An engine on the throwaway server, with the spent-card table built by the real migration."""
    name = throwaway[ "name" ]
    refuse_unless_throwaway( name, _labels_of( name ) )
    password = secrets.token_hex( 16 )
    _psql( name, "postgres", f"ALTER ROLE {SUPERUSER} PASSWORD '{password}';\n" )
    address = bridge_address( name, real_database_hosts() )
    built   = create_engine( f"postgresql+psycopg2://{SUPERUSER}:{password}@{address}:5432/lupin_db_dev", pool_size=RACERS + 2 )
    try:
        with built.begin() as connection:
            with Operations.context( MigrationContext.configure( connection ) ):
                migration.upgrade()
        yield built
    finally:
        built.dispose()


def _claim( engine, card_id, started_by ):
    with Session( engine ) as session:
        won = PodcastProxySpentRepository( session ).claim( card_id, started_by, "demo/io/tmp/summary.md", "a" * 64 )
        session.commit()
        return won


def _rows( engine, card_id ):
    with engine.connect() as connection:
        return connection.execute( text( "SELECT started_by, job_id FROM podcast_proxy_spent_cards WHERE card_id = :id" ), { "id": card_id } ).all()


@needs_docker
def test_the_migration_builds_the_table_with_the_card_id_as_primary_key_and_runs_twice( engine ):
    names = inspect( engine )
    assert names.get_pk_constraint( "podcast_proxy_spent_cards" )[ "constrained_columns" ] == [ "card_id" ]
    with engine.begin() as connection:
        with Operations.context( MigrationContext.configure( connection ) ):
            migration.upgrade()
    assert inspect( engine ).get_table_names().count( "podcast_proxy_spent_cards" ) == 1


@needs_docker
def test_of_many_simultaneous_starts_of_one_card_exactly_one_wins_and_one_row_remains( engine ):
    card_id = uuid.uuid4()
    gate    = threading.Barrier( RACERS )
    results = [ ]
    def start( index ):
        gate.wait()
        results.append( _claim( engine, card_id, f"racer-{index}" ) )
    threads = [ threading.Thread( target=start, args=( index, ) ) for index in range( RACERS ) ]
    for thread in threads: thread.start()
    for thread in threads: thread.join( timeout=60 )
    assert sorted( results ) == [ False ] * ( RACERS - 1 ) + [ True ], results
    assert len( _rows( engine, card_id ) ) == 1


@needs_docker
def test_a_released_claim_is_won_again_and_a_claim_without_a_job_has_no_job_id( engine ):
    card_id = uuid.uuid4()
    assert _claim( engine, card_id, "first" ) is True and _claim( engine, card_id, "second" ) is False
    with Session( engine ) as session:
        assert PodcastProxySpentRepository( session ).get( card_id ).job_id is None
        assert PodcastProxySpentRepository( session ).release( card_id ) is True
        session.commit()
    assert _claim( engine, card_id, "third" ) is True
    assert [ row[ 0 ] for row in _rows( engine, card_id ) ] == [ "third" ]
