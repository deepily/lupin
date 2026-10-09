"""
The spent-card record: its migration, its model, and the claim that lets one start win.

The table is made on SQLite through alembic's own operations for the migration tests, and from the
model for the repository tests. Two threads race on a file database to show the primary key decides.
"""

import importlib.util
import os
import threading
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
from cosa.rest.postgres_models import PodcastProxySpentCard

_MIGRATION = os.path.join( os.path.dirname( __file__ ), "..", "..", "migrations", "versions", "d4bf48f78a01_add_podcast_proxy_spent_cards.py" )
CARD = uuid.UUID( "11111111-1111-4111-8111-111111111111" )


def _migration():
    spec   = importlib.util.spec_from_file_location( "_mig_podcast_spent", _MIGRATION )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


@pytest.fixture
def conn():
    connection = create_engine( "sqlite://" ).connect()
    yield connection
    connection.close()


def _bind( module, connection, monkeypatch ):
    monkeypatch.setattr( module, "op", Operations( MigrationContext.configure( connection ) ) )


def test_the_migration_chains_from_the_current_head_and_names_its_revision():
    module = _migration()
    assert module.revision == "d4bf48f78a01" and module.down_revision == "b80513825c02"


def test_upgrade_makes_the_table_the_model_describes( conn, monkeypatch ):
    module = _migration()
    _bind( module, conn, monkeypatch )
    module.upgrade()
    made   = { c[ "name" ]: c for c in inspect( conn ).get_columns( "podcast_proxy_spent_cards" ) }
    wanted = { c.name: c for c in PodcastProxySpentCard.__table__.columns }
    assert set( made ) == set( wanted )
    assert { name: made[ name ][ "nullable" ] for name in made } == { name: wanted[ name ].nullable for name in wanted }
    assert inspect( conn ).get_pk_constraint( "podcast_proxy_spent_cards" )[ "constrained_columns" ] == [ "card_id" ]
    assert inspect( conn ).get_foreign_keys( "podcast_proxy_spent_cards" ) == [ ]


def test_upgrade_twice_changes_nothing_and_downgrade_removes_the_table( conn, monkeypatch ):
    module = _migration()
    _bind( module, conn, monkeypatch )
    module.upgrade()
    module.upgrade()
    assert inspect( conn ).has_table( "podcast_proxy_spent_cards" )
    module.downgrade()
    assert not inspect( conn ).has_table( "podcast_proxy_spent_cards" )
    module.downgrade()
    assert not inspect( conn ).has_table( "podcast_proxy_spent_cards" )


@pytest.fixture
def engine( tmp_path ):
    engine = create_engine( f"sqlite:///{tmp_path / 'spent.db'}", connect_args={ "timeout": 10 } )
    # SQLite has no uuid type: the card id is stored as 32 hex characters, which is how the column's type writes it.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE podcast_proxy_spent_cards ( card_id CHAR(32) PRIMARY KEY, spent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "started_by VARCHAR(255) NOT NULL, scope_path TEXT NOT NULL, sha256 VARCHAR(64) NOT NULL, job_id VARCHAR(64) )" )
    return engine


def _claim( session, card=CARD, by="maya b9537836" ):
    return PodcastProxySpentRepository( session ).claim( card, by, "lupin/io/tmp/a.md", "ab" * 32 )


def test_the_first_claim_wins_and_the_second_loses( engine ):
    with Session( engine ) as session:
        assert _claim( session ) is True
        assert _claim( session ) is False
        session.commit()
        row = session.get( PodcastProxySpentCard, CARD )
        assert row.started_by == "maya b9537836" and row.scope_path == "lupin/io/tmp/a.md" and row.sha256 == "ab" * 32 and row.job_id is None


def test_a_claim_committed_by_one_session_is_seen_by_the_next( engine ):
    with Session( engine ) as first:
        assert _claim( first ) is True
        first.commit()
    with Session( engine ) as second:
        assert PodcastProxySpentRepository( second ).is_spent( CARD ) is True
        assert _claim( second ) is False


def test_another_card_is_not_spent( engine ):
    with Session( engine ) as session:
        _claim( session )
        session.commit()
        other = uuid.UUID( "22222222-2222-4222-8222-222222222222" )
        assert PodcastProxySpentRepository( session ).is_spent( other ) is False
        assert _claim( session, other ) is True


def test_the_job_id_is_recorded_on_the_row( engine ):
    with Session( engine ) as session:
        _claim( session )
        PodcastProxySpentRepository( session ).record_job( CARD, "pg-1234abcd" )
        session.commit()
        assert session.get( PodcastProxySpentCard, CARD ).job_id == "pg-1234abcd"


def test_recording_a_job_for_an_unknown_card_does_nothing( engine ):
    with Session( engine ) as session:
        PodcastProxySpentRepository( session ).record_job( CARD, "pg-1" )
        session.commit()
        assert session.get( PodcastProxySpentCard, CARD ) is None


def test_releasing_a_claim_lets_the_card_start_again( engine ):
    with Session( engine ) as session:
        repo = PodcastProxySpentRepository( session )
        _claim( session )
        session.commit()
        assert repo.release( CARD ) is True
        session.commit()
        assert repo.is_spent( CARD ) is False and repo.release( CARD ) is False
        assert _claim( session ) is True


def test_two_starts_at_the_same_moment_let_exactly_one_through( engine ):
    sessions, barrier, results = sessionmaker( engine ), threading.Barrier( 2 ), [ ]
    def start( who ):
        with sessions() as session:
            barrier.wait()
            won = _claim( session, by=who )
            session.commit()
            results.append( ( who, won ) )
    threads = [ threading.Thread( target=start, args=( f"seat {n}", ) ) for n in range( 2 ) ]
    for thread in threads: thread.start()
    for thread in threads: thread.join( 30 )
    assert sorted( won for _, won in results ) == [ False, True ], results
    with sessions() as session:
        assert session.query( PodcastProxySpentCard ).count() == 1
