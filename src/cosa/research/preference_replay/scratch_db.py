"""
A scratch SQLite copy of the tables the extractor replay reads and writes.

The replay never touches the live database.
It loads an export into this throwaway copy, runs the extractor against it, and drops it.
SQLite renders the two Postgres-only column types as plain text.
It also reads a UUID made only of digits and "e" back as a float.
A real export holds random ids, so that happens about five times in a million.
A load that meets one fails loudly instead of changing a row.
"""

import uuid
from contextlib import contextmanager

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from cosa.rest.postgres_models import Notification, PredictionLog, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment

TABLES = ( Notification, PredictionLog, PreferencePrinciple, PreferenceEvidence )


@compiles( JSONB, "sqlite" )
def _jsonb_as_json( element, compiler, **kw ):
    """
    Render JSONB as JSON when the dialect is SQLite.

    Requires:
        - element is a JSONB column type

    Ensures:
        - returns "JSON"
    """
    return "JSON"


@compiles( Vector, "sqlite" )
def _vector_as_text( element, compiler, **kw ):
    """
    Render a pgvector column as text when the dialect is SQLite.

    Requires:
        - element is a Vector column type

    Ensures:
        - returns "TEXT"
    """
    return "TEXT"


@contextmanager
def scratch_session():
    """
    Open a session over empty in-memory copies of the replay's tables.

    Ensures:
        - yields an active session that works from any thread, because one connection is shared
        - the engine is disposed when the block ends
    """
    engine = create_engine( "sqlite://", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    for model in TABLES: model.__table__.create( engine )
    with Session( engine ) as session:
        yield session
    engine.dispose()


def session_scope( session ):
    """
    Wrap an open session as the context manager the extractor job's factory returns.

    Requires:
        - session is an active SQLAlchemy session

    Ensures:
        - returns a context manager that yields the same session and commits when the block ends cleanly
    """
    @contextmanager
    def scope():
        yield session
        session.commit()
    return scope()


def load_export( session, export ):
    """
    Insert every notification of a context export into the scratch copy.

    Requires:
        - session is an active session over the scratch tables
        - export has "targets", each with target_notification, and "records", each with notification

    Ensures:
        - returns the number of notifications inserted, each id once, targets and context records together
        - ids and the recipient become UUIDs and every timestamp column an aware datetime
        - a key the Notification table has no column for is dropped
    """
    columns = Notification.__table__.columns
    seen    = {}
    for record in export[ "records" ].values(): seen[ record[ "notification" ][ "id" ] ] = record[ "notification" ]
    for target in export[ "targets" ]: seen[ target[ "target_notification" ][ "id" ] ] = target[ "target_notification" ]
    for raw in seen.values():
        row = { key: value for key, value in raw.items() if key in columns }
        row[ "id" ]           = uuid.UUID( row[ "id" ] )
        row[ "recipient_id" ] = uuid.UUID( row[ "recipient_id" ] )
        for name, column in columns.items():
            if isinstance( column.type, DateTime ) and isinstance( row.get( name ), str ): row[ name ] = aware_moment( row[ name ] )
        session.add( Notification( **row ) )
    session.commit()
    return len( seen )
