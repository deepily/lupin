"""
S5 END-TO-END — a broadcast ack is SAVED, and comes back with its broadcast and its
seat. Store row 4f320c27 (parent bug 1c7da903).

THE SINGLE GATE THIS FILE IS. Every other test in this change is hermetic: the
watcher's persist is checked against a fake repository, and the read endpoint is
checked against a repository spy. Both halves can be individually perfect and still
not meet in the middle — a payload written under one key and read under another, a
JSONB filter that never matches, a fold keyed on a field the writer does not set.
That is the "looks fixed, recovers nothing" state the plan names, and only a run
that WRITES through the real watcher and READS through the real query can rule it
out. Nothing here is mocked between the two ends but the commons topic itself.

🔴 MARÍA'S CASE IS ASSERTED HERE, NOT ONLY IN THE UNIT TIER. An ack that reached a
live socket is marked delivered the moment it is saved. The undelivered drain skips
delivered rows by design and must keep doing so — so the test asserts BOTH sides of
that fork in one run, on one row: the per-broadcast read returns it, and the
undelivered drain does not. Asserting only the first would pass on an implementation
that had quietly turned the ack into a missed-notification replay.

VENUE — :7999-eligible (AI-discretionary), by the same call María made for
`test_migration_answer_delivered_at_roundtrip.py` and for the same reasons. It
creates and DROPS its OWN uniquely-named throwaway database, mutates nothing that
outlives the test, needs no server monopoly, runs in seconds, and SKIPS rather than
fails when Postgres is unreachable. It does not touch :8000 and takes no monopoly.

WHY IT CANNOT BE HERMETIC. The read's whole contract is a JSONB expression
(`payload->>'broadcast_id'`) against a JSONB column. SQLite has neither, and a
metadata-only double cannot model the one thing under test. A real Postgres is not
a convenience here; it is the instrument.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from alembic import command

import cosa.rest.commons_ack_watcher as watcher_module
import cosa.rest.routers.notifications as notif
from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.postgres_models import Notification


_THROWAWAY_DB = f"broadcast_ack_e2e_{os.getpid()}"

_BROADCAST_ID = "11111111-aaaa-4bbb-8ccc-222222222222"
_SESSION_ID   = "f19a8996-2fdc-425d-82bc-0e99f3cd8db2"


def _server_url():
    """
    Borrow a credential-correct Postgres server URL via the suite's canonical
    test-DB path. Only host/port/credentials are used — every write below lands in
    a separate, uniquely-named THROWAWAY database, never lupin_db_test. Returns the
    URL OBJECT (it carries the REAL password); callers must NOT str() it.
    """
    db_module.swap_database( "testing" )
    return db_module.engine.url


@pytest.fixture( scope="module" )
def throwaway_db_url():
    """Create an empty throwaway DB, migrate it to head, yield its URL, drop it."""
    server_url = _server_url()
    try:
        eng = create_engine( server_url, isolation_level="AUTOCOMMIT" )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping the broadcast-ack end-to-end: {e}" )

    url = server_url.set( database=_THROWAWAY_DB )
    command.upgrade( build_alembic_config( database_url=url.render_as_string( hide_password=False ) ), "head" )
    yield url

    eng = create_engine( server_url, isolation_level="AUTOCOMMIT" )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    eng.dispose()


@pytest.fixture( scope="module" )
def engine( throwaway_db_url ):
    eng = create_engine( throwaway_db_url )
    yield eng
    eng.dispose()


@pytest.fixture
def broadcaster_id( engine ):
    """
    A real `users` row, because `notifications.recipient_id` is a FK to it — a
    fabricated UUID is refused by the database, which is itself part of what this
    test proves reaches a real schema.
    """
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text( "INSERT INTO users ( id, email, password_hash, created_at ) "
                  "VALUES ( :id, :email, :pw, now() )" ),
            { "id": str( user_id ), "email": f"ack-e2e-{user_id}@example.invalid",
              # never a real hash, and never verifiable — this account exists only to
              # satisfy the FK inside a database that is dropped at teardown
              "pw": "not-a-credential-throwaway-fixture" }
        )
    return user_id


@pytest.fixture
def real_db( engine, monkeypatch ):
    """
    Point the watcher's `get_db` at the throwaway database.

    This is the ONLY substitution in the file, and it swaps a connection string —
    not behaviour. Everything downstream of it is the production code path.
    """
    Session = sessionmaker( bind=engine )

    class _Ctx:
        def __enter__( self ):
            self.session = Session()
            return self.session
        def __exit__( self, exc_type, *_ ):
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
            self.session.close()
            return False

    monkeypatch.setattr( watcher_module, "get_db", lambda: _Ctx() )
    return Session


def _entry( session_id=_SESSION_ID, persona="Mr. Radio" ):
    return {
        "sender_session_id" : session_id,
        "persona_name"      : persona,
        "persona_icon"      : "🦉",
        "persona_color"     : "#FFA000",
    }


def _ack_once( broadcaster_id, real_db, entry=None, status="completed", push=None ):
    """Drive ONE ack through the real watcher, exactly as tick() would."""
    pushed = [] if push is None else push
    w = CommonsAckWatcher(
        store                = object(),
        push_notification_fn = lambda **kwargs: pushed.append( kwargs ),
        debug                = True,
    )
    w._push_ack_event(
        entry or _entry(), _BROADCAST_ID, str( broadcaster_id ),
        { "status": status, "body_summary": "⚠️ :7999 is bouncing NOW — hold notifications…" }
    )
    return pushed


def _read_back( real_db, broadcaster_id, broadcast_id=_BROADCAST_ID ):
    """Read through the REAL repo query and the REAL router projector."""
    session = real_db()
    try:
        rows = NotificationRepository( session ).get_latest_acks_for_broadcast(
            broadcaster_id, broadcast_id )
        return [ notif._project_broadcast_ack( r ) for r in rows ]
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════

class TestASavedAckComesBackWithItsBroadcastAndSeat:

    def test_the_ack_is_readable_after_the_watcher_wrote_it( self, broadcaster_id, real_db ):
        """
        🔴 THE GATE. Write through the watcher, read through the query, and the
        broadcast and the seat both survive the round trip. If this fails, the two
        halves do not meet and every hermetic test in this change was measuring its
        own fixture.
        """
        _ack_once( broadcaster_id, real_db )
        acks = _read_back( real_db, broadcaster_id )

        assert len( acks ) == 1, acks
        ack = acks[ 0 ]
        assert ack[ "broadcast_id" ]  == _BROADCAST_ID
        assert ack[ "session_id" ]    == _SESSION_ID
        assert ack[ "persona_name" ]  == "Mr. Radio"
        assert ack[ "persona_icon" ]  == "🦉"
        assert ack[ "persona_color" ] == "#FFA000"
        assert ack[ "ack_status" ]    == "completed"

    def test_the_saved_row_and_the_live_push_describe_the_same_ack( self, broadcaster_id, real_db ):
        """Both halves of the S3 contract, compared against each other rather than separately."""
        pushed = _ack_once( broadcaster_id, real_db )
        saved  = _read_back( real_db, broadcaster_id )[ 0 ]
        assert len( pushed ) == 1
        assert pushed[ 0 ][ "payload" ][ "broadcast_id" ] == saved[ "broadcast_id" ]
        assert pushed[ 0 ][ "payload" ][ "session_id" ]   == saved[ "session_id" ]
        assert pushed[ 0 ][ "type" ] == "commons_broadcast_ack"

    def test_another_broadcasts_acks_are_not_in_this_broadcasts_tally( self, broadcaster_id, real_db ):
        """
        🔴 THE JSONB FILTER MUST ACTUALLY DISCRIMINATE. A predicate that matched
        everything would pass every test above — each of them writes one row and
        reads one row back.
        """
        _ack_once( broadcaster_id, real_db )
        assert _read_back( real_db, broadcaster_id, broadcast_id="a-different-broadcast" ) == []

    def test_a_second_seats_ack_joins_the_same_tally( self, broadcaster_id, real_db ):
        _ack_once( broadcaster_id, real_db )
        _ack_once( broadcaster_id, real_db, entry=_entry( session_id="be26cc2d-9ab0-43fd-8725-628eda59c98b",
                                                          persona="maria" ) )
        personas = sorted( a[ "persona_name" ] for a in _read_back( real_db, broadcaster_id ) )
        assert personas == [ "Mr. Radio", "maria" ]

    def test_a_seat_that_acks_twice_counts_once_with_its_latest_status( self, broadcaster_id, real_db ):
        """
        A seat re-acks when its status changes. Against the real ordering, the tally
        must show that seat ONCE, carrying the newer status.
        """
        _ack_once( broadcaster_id, real_db, status="pending" )
        _ack_once( broadcaster_id, real_db, status="completed" )
        acks = _read_back( real_db, broadcaster_id )
        assert len( acks ) == 1, acks
        assert acks[ 0 ][ "ack_status" ] == "completed"

    def test_a_broadcast_nobody_acked_reads_back_empty_rather_than_erroring( self, broadcaster_id, real_db ):
        assert _read_back( real_db, broadcaster_id, broadcast_id="never-acked" ) == []


class TestMariasCaseAnAckDeliveredToALiveSocketFirst:

    def test_it_is_marked_delivered_the_moment_it_is_saved( self, broadcaster_id, real_db ):
        """The premise of the case, stated as a fact about the row rather than assumed."""
        _ack_once( broadcaster_id, real_db )
        session = real_db()
        try:
            states = [ r.state for r in session.query( Notification ).filter(
                Notification.recipient_id == broadcaster_id ).all() ]
        finally:
            session.close()
        assert states == [ "delivered" ]

    def test_a_DELIVERED_ack_still_appears_in_the_per_broadcast_read( self, broadcaster_id, real_db ):
        """
        🔴 MARÍA'S REQUIREMENT. The browser was open, the ack was delivered on the
        spot, and the tally must still survive a reload. A read that inherited the
        undelivered drain's skip-delivered filter returns [] here.
        """
        _ack_once( broadcaster_id, real_db )
        acks = _read_back( real_db, broadcaster_id )
        assert len( acks ) == 1
        assert acks[ 0 ][ "state" ] == "delivered"

    def test_the_SAME_delivered_ack_is_absent_from_the_undelivered_drain( self, broadcaster_id, real_db ):
        """
        🔴 THE OTHER SIDE OF THE FORK, ON THE SAME ROW. The drain's skip-delivered
        filter stays exactly as it was — and it must, or every ack the fleet ever
        sends replays on reconnect as a bodiless "missed notification". Asserting
        only the read above would pass on that regression.
        """
        _ack_once( broadcaster_id, real_db )
        session = real_db()
        try:
            missed = NotificationRepository( session ).get_undelivered_for_recipient( broadcaster_id )
        finally:
            session.close()
        assert missed == [], f"an ack must never enter the AFK inbox, found {missed!r}"

    def test_the_undelivered_control_can_still_see_an_undelivered_row( self, broadcaster_id, real_db ):
        """
        The emptiness above is worth nothing until the same drain has been watched
        returning something. One ordinary created-state row, same recipient, same
        query — it comes back, so the empty answer above is about the ack's state
        and not about a query that finds nothing at all.
        """
        _ack_once( broadcaster_id, real_db )
        session = real_db()
        try:
            repo = NotificationRepository( session )
            repo.create_notification(
                sender_id="claude.code@lupin.deepily.ai", recipient_id=broadcaster_id,
                message="an ordinary undelivered notification", type="task", priority="medium" )
            session.commit()
            missed = repo.get_undelivered_for_recipient( broadcaster_id )
        finally:
            session.close()
        assert len( missed ) == 1
        assert missed[ 0 ].message == "an ordinary undelivered notification"


class TestThePartialIndexIsBuiltAndUsable:

    def test_the_migration_left_a_VALID_partial_index_over_the_ack_rows( self, engine ):
        """
        `CREATE INDEX CONCURRENTLY` that races or aborts leaves an INVALID index that
        Postgres silently declines to use — the query stays correct and quietly scans
        the whole forever-kept table. Only a live server can tell the two apart.
        """
        with engine.connect() as conn:
            row = conn.execute( text(
                "SELECT i.indisvalid, i.indisready, pg_get_indexdef( i.indexrelid ) "
                "FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE c.relname = 'idx_notifications_ack_broadcast'"
            ) ).first()
        assert row is not None, "migration 9184990becdf must have built idx_notifications_ack_broadcast"
        indisvalid, indisready, indexdef = row
        assert indisvalid is True, "the CONCURRENTLY build must have completed"
        assert indisready is True
        assert "recipient_id"  in indexdef, indexdef
        assert "broadcast_id"  in indexdef, indexdef
        assert "commons_broadcast_ack" in indexdef, indexdef
