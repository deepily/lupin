#!/usr/bin/env python3
"""
The row-locked transition read must return the COMMITTED row even when this
session already holds that item.

WHY THIS FILE EXISTS. `TaskRepository.get_by_id_for_update` carried a docstring
promising "the second transaction ... reads the COMMITTED status, so validation
always sees fresh state" over a body that was `query().filter().with_for_update()
.first()`. `with_for_update()` serializes the row AT THE DATABASE; it does not
repopulate the Python attributes of an instance already in the session's identity
map. So the promise held only by CALL-SITE DISCIPLINE — every current caller
happens to make this the first load of that row in a fresh session — and nothing
in the suite would have noticed the day a caller stopped doing that.

WHERE THIS ENTERS. At the repository method, driving a REAL SQLAlchemy session
with a real identity map, with a second session committing in between. That is
the layer the defect lives at. The mock-session test next door
(test_task_repository.py) asserts the CHAIN; this one asserts the VALUE, and the
two fail for different reasons.

THE POSITIVE CONTROL IS NOT OPTIONAL. `test_the_fixture_can_see_a_stale_read`
performs the same sequence WITHOUT `.populate_existing()` and asserts the read
comes back STALE. Without it, a green here is compatible with a fixture that
could never have observed staleness at all, and the whole file would be
measuring itself.

SCOPE — SAY IT RATHER THAN IMPLY IT. The backend here is in-memory SQLite over a
constraint-stripped mirror of the task_items table, because the identity-map
behaviour under test is SQLAlchemy-layer and backend-independent: the ORM decides
whether to overwrite a mapped instance's attributes before any dialect is
involved. It is NOT a claim about Postgres row locking — SQLite ignores FOR
UPDATE. The Postgres half was measured separately by pocholo 📣 on real Postgres
16.14 (2026-09-06): after a second session commits, only
`.populate_existing()`, `session.refresh()` and raw SQL come back fresh.

:7999-eligible: in-memory only, no server, no persistent state, milliseconds.
"""
import os
import sys
import uuid

import pytest
from sqlalchemy import JSON, MetaData, String, create_engine, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Session
from sqlalchemy.schema import CheckConstraint

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.postgres_models import TaskItem
from cosa.rest.db.repositories.task_repository import TaskRepository


def _sqlite_mirror_engine():
    """
    An in-memory engine holding a SQLite-renderable copy of task_items.

    The live table carries Postgres-only column types (JSONB, INET) and a CHECK
    constraint using the jsonb containment operator, none of which SQLite can
    render. Those are stripped from a COPY of the table — the mapped class and
    its column NAMES are untouched, which is all the ORM needs to read and write
    through TaskItem. No global dialect compiler is registered, deliberately:
    that would leak into every other test in this process.
    """
    engine = create_engine( "sqlite://" )
    table  = TaskItem.__table__.to_metadata( MetaData() )

    for constraint in list( table.constraints ):
        if isinstance( constraint, CheckConstraint ): table.constraints.discard( constraint )

    for column in table.columns:
        if isinstance( column.type, JSONB ): column.type = JSON()
        if isinstance( column.type, INET ):  column.type = String( 64 )

    table.c.id.server_default = None                       # gen_random_uuid() is Postgres-only
    table.create( engine )
    return engine


@pytest.fixture
def engine():
    return _sqlite_mirror_engine()


@pytest.fixture
def seeded( engine ):
    """One queued item, committed and closed — the id is all that survives."""
    task_id = uuid.uuid4()
    with Session( engine ) as session:
        session.add( TaskItem(
            id         = task_id,
            item_class = "task",
            title      = "a row two sessions will both touch",
            project    = "lupin",
            status     = "queued",
            created_by = "rio",
            blocked_by = [],
        ) )
        session.commit()
    assert _committed_status( engine, task_id ) == "queued"   # the reference reader works
    return task_id


def _another_session_commits_done( engine, task_id ):
    """A SECOND session moves the row queued -> done and commits."""
    with Session( engine ) as other:
        other.query( TaskItem ).filter( TaskItem.id == task_id ).update( { "status": "done" } )
        other.commit()


def _committed_status( engine, task_id ):
    """
    The database's own answer, read outside the ORM — the reference side of
    every comparison in this file, so the expected value never comes from the
    same place as the observed one.

    The id is matched on its hyphen-free hex because SQLAlchemy's UUID type
    stores CHAR(32) on a backend with no native uuid; comparing against
    str(task_id) silently matches nothing and returns None, which reads as
    "the write did not land". The seeded fixture proves this reader works
    before any test relies on it.
    """
    with engine.connect() as connection:
        return connection.execute(
            text( "SELECT status FROM task_items "
                  "WHERE replace( lower( CAST( id AS TEXT ) ), '-', '' ) = :h" ),
            { "h": task_id.hex },
        ).scalar()


def test_the_for_update_read_refreshes_a_row_this_session_already_holds( engine, seeded ):
    """
    THE GUARD. Delete `.populate_existing()` from get_by_id_for_update and this
    goes red with `assert 'queued' == 'done'`, naming the stale value.
    """
    session = Session( engine )
    session.autoflush = False                              # matches SessionLocal (db/database.py:247)
    held = session.query( TaskItem ).filter( TaskItem.id == seeded ).first()
    assert held.status == "queued"                         # the session now holds the row

    _another_session_commits_done( engine, seeded )
    assert _committed_status( engine, seeded ) == "done"    # the write really landed

    reread = TaskRepository( session ).get_by_id_for_update( seeded )

    assert reread is held                                  # same identity-mapped object...
    assert reread.status == "done"                         # ...and its attributes were repopulated
    session.close()


def test_the_fixture_can_see_a_stale_read( engine, seeded ):
    """
    POSITIVE CONTROL. The identical sequence WITHOUT `.populate_existing()`
    returns the pre-commit value. This is what makes the guard above evidence
    rather than a green that could never have been anything else.
    """
    session = Session( engine )
    session.autoflush = False
    held = session.query( TaskItem ).filter( TaskItem.id == seeded ).first()

    _another_session_commits_done( engine, seeded )
    assert _committed_status( engine, seeded ) == "done"

    stale = ( session.query( TaskItem )
              .filter( TaskItem.id == seeded )
              .with_for_update()
              .first() )

    assert stale is held
    assert stale.status == "queued"                        # the lock did NOT make it fresh
    session.close()


def test_a_missing_row_is_still_none_under_the_refreshing_read( engine ):
    """`.populate_existing()` must not change the not-found contract."""
    with Session( engine ) as session:
        assert TaskRepository( session ).get_by_id_for_update( uuid.uuid4() ) is None
